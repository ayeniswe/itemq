from __future__ import annotations

from dataclasses import dataclass
import logging
import mimetypes
from pathlib import Path
import threading
from typing import Callable, Iterable, Tuple
from notion_client import Client as NotionClient, extract_database_id

from config import MEDIA_ROOT
from db import (
    update_inventory_notion_page_id,
    update_inventory_notion_sync_flags,
    update_inventory_notion_sync_status,
)
from services.barcode import generate_barcode

logger = logging.getLogger(__name__)


@dataclass
class NotionJobResult:
    status: str
    payload: dict | None = None


@dataclass
class InventoryBackupSyncSnapshot:
    state: str = "idle"
    message: str | None = None
    detail: str | None = None
    current_item: str | None = None
    total_steps: int = 0
    completed_steps: int = 0
    total_rows: int = 0
    synced_rows: int = 0
    failed_rows: int = 0
    total_images: int = 0
    synced_images: int = 0
    failed_images: int = 0

    @property
    def percent(self) -> int:
        if self.total_steps <= 0:
            return 100 if self.state == "completed" else 0
        return min(100, int((self.completed_steps / self.total_steps) * 100))

    @property
    def running(self) -> bool:
        return self.state == "running"

    @property
    def canceling(self) -> bool:
        return self.state == "canceling"


class NotionWorker:

    def __init__(self):
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, task: Callable[[threading.Event], None]) -> None:
        if self.running:
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=task,
                                        args=(self._stop_event, ),
                                        daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self.running:
            self._stop_event.set()


class InventoryBackupSyncWorker:

    def __init__(self):
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._snapshot = InventoryBackupSyncSnapshot()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def snapshot(self) -> InventoryBackupSyncSnapshot:
        with self._lock:
            return InventoryBackupSyncSnapshot(**self._snapshot.__dict__)

    def start(self, token: str, database_id: str, items: Iterable[dict]) -> bool:
        if self.running:
            with self._lock:
                self._snapshot.message = "Sync already in progress."
            return False

        local_items = [dict(item) for item in items if item.get("source") == "local"]
        total_images = sum(1 for item in local_items if _resolve_inventory_image_path(item.get("image_path")))
        total_steps = len(local_items) + total_images

        if not local_items:
            with self._lock:
                self._snapshot = InventoryBackupSyncSnapshot(
                    state="completed",
                    message="Nothing to sync.",
                    detail="No local inventory rows were found for backup.",
                )
            return True

        with self._lock:
            self._stop_event.clear()
            self._snapshot = InventoryBackupSyncSnapshot(
                state="running",
                message="Syncing inventory backup to Notion…",
                detail="Preparing rows and images for upload.",
                total_steps=total_steps,
                total_rows=len(local_items),
                total_images=total_images,
            )

        self._thread = threading.Thread(
            target=self._run,
            args=(token, database_id, local_items),
            daemon=True,
        )
        self._thread.start()
        return True

    def _run(self, token: str, database_id: str, items: list[dict]) -> None:
        try:
            sync_local_inventory_backup_to_notion(
                token,
                database_id,
                items,
                stop_event=self._stop_event,
                progress_callback=self._apply_progress,
            )
            with self._lock:
                canceled = self._stop_event.is_set()
                failures = self._snapshot.failed_rows + self._snapshot.failed_images
                self._snapshot.state = "canceled" if canceled else "completed"
                self._snapshot.current_item = None
                if canceled:
                    self._snapshot.message = "Notion sync canceled."
                elif failures:
                    self._snapshot.message = "Notion sync finished with some issues."
                else:
                    self._snapshot.message = "Notion sync finished."
                self._snapshot.detail = (
                    f"{self._snapshot.synced_rows}/{self._snapshot.total_rows} rows synced, "
                    f"{self._snapshot.synced_images}/{self._snapshot.total_images} images uploaded."
                )
        except Exception as exc:
            logger.exception("Inventory backup sync crashed: %s", exc)
            with self._lock:
                self._snapshot.state = "failed"
                self._snapshot.current_item = None
                self._snapshot.message = "Notion sync failed."
                self._snapshot.detail = str(exc)

    def stop(self) -> bool:
        if not self.running:
            return False

        self._stop_event.set()
        with self._lock:
            self._snapshot.state = "canceling"
            self._snapshot.message = "Canceling Notion sync…"
            self._snapshot.detail = "Waiting for the current Notion request to finish."
        return True

    def _apply_progress(self, event: dict) -> None:
        with self._lock:
            current_item = event.get("current_item")
            if current_item:
                self._snapshot.current_item = current_item

            if event.get("step_completed"):
                self._snapshot.completed_steps = min(
                    self._snapshot.total_steps,
                    self._snapshot.completed_steps + 1,
                )

            row_status = event.get("row_status")
            if row_status == "synced":
                self._snapshot.synced_rows += 1
            elif row_status == "failed":
                self._snapshot.failed_rows += 1

            image_status = event.get("image_status")
            if image_status == "synced":
                self._snapshot.synced_images += 1
            elif image_status == "failed":
                self._snapshot.failed_images += 1

            detail = event.get("detail")
            if detail:
                self._snapshot.detail = detail


def schedule_local_inventory_item_sync(
    token: str,
    database_id: str,
    item: dict,
) -> None:
    worker = threading.Thread(
        target=sync_local_inventory_backup_to_notion,
        args=(token, database_id, [dict(item)]),
        daemon=True,
    )
    worker.start()


def connect_to_notion(token: str, database_url: str) -> Tuple[str, str]:
    # Initialize Notion client
    notion = NotionClient(auth=token)
    
    database_id = extract_database_id(database_url)

    # Lightweight validation call (will raise if invalid)
    db = notion.databases.retrieve(database_id=database_id)

    # Extract human-readable database name from schema
    db_name = "".join(
        part.get("plain_text", "")
        for part in db.get("title", [])
    )

    setattr(validate_notion_schema, "_notion_token", token)
    
    return database_id, db_name


# NOTE: validate_notion_schema expects the Notion token to be attached at runtime
def validate_notion_schema(database_id: str) -> tuple[bool, str | None]:
    # Validate that the Notion database contains required properties
    # Required:
    # - Barcode: rich_text or title
    # - Name: title or rich_text
    # - Quantity: number

    try:
        # Reuse an unauthenticated client is not possible here; schema validation
        # assumes the caller already validated access via connect_to_notion.
        # Therefore we create a client from the global environment.
        token = None
        if hasattr(validate_notion_schema, "_notion_token"):
            token = getattr(validate_notion_schema, "_notion_token")
        if token is None:
            return False, "Notion token not available for schema validation"

        notion = NotionClient(auth=token)
        db = notion.databases.retrieve(database_id=database_id)
        sources = [
            notion.data_sources.retrieve(data_source_id=src.get("id"))
            for src in db.get("data_sources")
        ]
    except Exception as e:
        return False, f"Failed to retrieve database schema: {e}"

    required = {
        "Barcode": {"rich_text", "title"},
        "Name": {"title", "rich_text"},
        "Quantity": {"number"},
    }

    for src in sources:
        source_label = (
            src.get("title", [{}])[0].get("plain_text")
            or src.get("id", "unknown")
        )
        properties = src.get("properties", {})

        for prop_name, allowed_types in required.items():
            prop = properties.get(prop_name)
            if not prop:
                return False, f"Missing required property '{prop_name}' in data source '{source_label}'"

            prop_type = prop.get("type")
            if prop_type not in allowed_types:
                return (
                    False,
                    f"Invalid type for '{prop_name}' in data source '{source_label}': "
                    f"expected {', '.join(sorted(allowed_types))}, but got {prop_type} nnnrnenrnenrnenrenrnenrnenrenrnenrnenrnenrenrnenrnenrenrnenrenrnrenr",
                )

    return True, None


def fetch_database_rows(token: str, database_id: str) -> Iterable[dict]:
    notion = NotionClient(auth=token)

    # Retrieve database and all data sources
    db = notion.databases.retrieve(database_id=database_id)
    sources = [
        notion.data_sources.retrieve(data_source_id=src.get("id"))
        for src in db.get("data_sources", [])
    ]

    # Iterate through every data source and gather rows
    for src in sources:
        source_id = src.get("id")
        query = None

        while True:
            query = notion.data_sources.query(
                data_source_id=source_id,
                filter_properties=[
                    "Barcode",
                    "Name",
                    "Quantity",
                ],
                start_cursor=query.get("next_cursor") if query else None,
            )

            results = query.get("results", [])
            if not results:
                break

            for row in results:
                props = row.get("properties", {})

                barcode_prop = props.get("Barcode", {})
                barcode_parts = (
                    barcode_prop.get("rich_text")
                    or barcode_prop.get("title")
                    or []
                )
                barcode = "".join(
                    rt.get("plain_text", "")
                    for rt in barcode_parts
                )
                if not barcode.strip():
                    barcode = generate_barcode()
                    property_payload = _build_barcode_property(barcode_prop, barcode)
                    try:
                        notion.pages.update(
                            page_id=row.get("id"),
                            properties={
                                "Barcode": property_payload,
                            },
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to update Notion barcode for row %s: %s",
                            row.get("id"),
                            exc,
                        )

                name_prop = props.get("Name", {})
                name_parts = (
                    name_prop.get("title")
                    or name_prop.get("rich_text")
                    or []
                )
                name = "".join(
                    rt.get("plain_text", "")
                    for rt in name_parts
                )

                quantity = props.get("Quantity", {}).get("number") or 0

                yield {
                    "barcode": barcode,
                    "name": name,
                    "quantity": quantity,
                }

            if not query.get("has_more"):
                break


def update_notion_quantity_by_barcode(
    token: str,
    database_id: str,
    barcode: str,
    quantity: int,
) -> int:
    notion = NotionClient(auth=token)

    db = notion.databases.retrieve(database_id=database_id)
    sources = [
        notion.data_sources.retrieve(data_source_id=src.get("id"))
        for src in db.get("data_sources", [])
    ]

    updated = 0

    for src in sources:
        source_id = src.get("id")
        barcode_prop = src.get("properties", {}).get("Barcode", {})
        prop_type = barcode_prop.get("type")

        if prop_type == "title":
            filter_payload = {
                "property": "Barcode",
                "title": {"equals": barcode},
            }
        else:
            filter_payload = {
                "property": "Barcode",
                "rich_text": {"equals": barcode},
            }

        query = None
        while True:
            query = notion.data_sources.query(
                data_source_id=source_id,
                filter=filter_payload,
                start_cursor=query.get("next_cursor") if query else None,
            )

            results = query.get("results", [])
            if not results:
                break

            for row in results:
                notion.pages.update(
                    page_id=row.get("id"),
                    properties={
                        "Quantity": {"number": quantity},
                    },
                )
                updated += 1

            if not query.get("has_more"):
                break

    return updated


def _build_barcode_property(barcode_prop: dict, barcode: str) -> dict:
    prop_type = barcode_prop.get("type")
    if prop_type == "title":
        return {
            "title": [
                {
                    "text": {
                        "content": barcode,
                    }
                }
            ]
        }
    return {
        "rich_text": [
            {
                "text": {
                    "content": barcode,
                }
            }
        ]
    }


def upsert_notion_inventory_item(
    token: str,
    database_id: str,
    item: dict,
) -> str | None:
    item_name = (item.get("name") or "").strip() or "<unnamed>"
    barcode = (item.get("barcode") or "").strip()
    try:
        notion = NotionClient(auth=token)
        source = _get_primary_data_source(notion, database_id)
        if source is None:
            logger.warning(
                "Skipping Notion row sync for item=%r barcode=%r: no data source found for database %s",
                item_name,
                barcode,
                database_id,
            )
            return None
        source_id = source["id"]
        properties = source.get("properties", {})
        barcode_prop = properties.get("Barcode", {})
        prop_type = barcode_prop.get("type")
        filter_payload = _build_barcode_filter(prop_type, barcode)
        if not filter_payload and barcode:
            logger.warning(
                "Skipping Notion row lookup for item=%r barcode=%r: unsupported Barcode property type %r",
                item_name,
                barcode,
                prop_type,
            )

        existing_page_id = None
        if filter_payload:
            query = notion.data_sources.query(
                data_source_id=source_id,
                filter=filter_payload,
            )
            results = query.get("results", [])
            if results:
                if len(results) > 1:
                    logger.warning(
                        "Multiple Notion rows matched barcode=%r for item=%r; updating first match page_id=%s",
                        barcode,
                        item_name,
                        results[0].get("id"),
                    )
                existing_page_id = results[0].get("id")

        payload = _build_inventory_properties(properties, item)
        if existing_page_id:
            notion.pages.update(page_id=existing_page_id, properties=payload)
            return existing_page_id

        created = notion.pages.create(
            parent={"data_source_id": source_id},
            properties=payload,
        )
        return created.get("id")
    except Exception as exc:
        logger.exception(
            "Failed to sync local inventory item to Notion for item=%r barcode=%r: %s",
            item_name,
            barcode,
            exc,
        )
        return None


def update_notion_inventory_image(
    token: str,
    database_id: str,
    image_path: str,
    page_id: str | None = None,
    barcode: str | None = None,
    stop_event: threading.Event | None = None,
) -> bool:
    barcode = (barcode or "").strip()
    try:
        if stop_event and stop_event.is_set():
            return False
        notion = NotionClient(auth=token)
        source = _get_primary_data_source(notion, database_id)
        if source is None:
            logger.warning(
                "Skipping Notion image sync for barcode=%r image_path=%r: no data source found for database %s",
                barcode,
                image_path,
                database_id,
            )
            return False
        source_id = source["id"]
        properties = source.get("properties", {})

        resolved_path = _resolve_inventory_image_path(image_path)
        if resolved_path is None:
            logger.warning(
                "Skipping Notion image sync for barcode=%r image_path=%r: file not found on disk",
                barcode,
                image_path,
            )
            return False

        target_page_id = page_id
        if target_page_id is None:
            barcode_prop = properties.get("Barcode", {})
            prop_type = barcode_prop.get("type")
            filter_payload = _build_barcode_filter(prop_type, barcode)
            if not filter_payload:
                logger.warning(
                    "Skipping Notion image sync for barcode=%r image_path=%r: unsupported Barcode property type %r",
                    barcode,
                    image_path,
                    prop_type,
                )
                return False

            query = notion.data_sources.query(
                data_source_id=source_id,
                filter=filter_payload,
            )
            results = query.get("results", [])
            if not results:
                logger.warning(
                    "Skipping Notion image sync for barcode=%r image_path=%r: no matching Notion row found",
                    barcode,
                    image_path,
                )
                return False
            target_page_id = results[0].get("id")

        filename = resolved_path.name
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        if stop_event and stop_event.is_set():
            return False
        upload = notion.file_uploads.create(
            filename=filename,
            content_type=content_type,
        )
        upload_id = upload.get("id")
        if not upload_id:
            logger.warning(
                "Failed to create Notion file upload for barcode=%r image_path=%r: missing upload id in response",
                barcode,
                image_path,
            )
            return False

        if stop_event and stop_event.is_set():
            return False
        with resolved_path.open("rb") as file_obj:
            notion.file_uploads.send(
                upload_id,
                file=(filename, file_obj, content_type),
            )

        if stop_event and stop_event.is_set():
            return False
        notion.pages.update(
            page_id=target_page_id,
            cover={
                "type": "file_upload",
                "file_upload": {
                    "id": upload_id
                }
            }
        )
        return True
    except Exception as exc:
        logger.exception(
            "Failed to sync inventory image to Notion for barcode=%r image_path=%r: %s",
            barcode,
            image_path,
            exc,
        )
        return False


def sync_local_inventory_backup_to_notion(
    token: str,
    database_id: str,
    items: Iterable[dict],
    stop_event: threading.Event | None = None,
    progress_callback: Callable[[dict], None] | None = None,
) -> tuple[int, int]:
    synced_rows = 0
    synced_images = 0

    for item in items:
        if stop_event and stop_event.is_set():
            break
        if item.get("source") != "local":
            continue

        item_name = (item.get("name") or item.get("barcode") or "Inventory item").strip()
        image_path = (item.get("image_path") or "").strip()
        has_image = _resolve_inventory_image_path(image_path) is not None

        page_id = upsert_notion_inventory_item(token, database_id, item)
        row_ok = page_id is not None
        item_id = item.get("id")
        if row_ok:
            synced_rows += 1
            if item_id:
                update_inventory_notion_page_id(int(item_id), page_id)
                update_inventory_notion_sync_flags(
                    int(item_id),
                    notion_row_synced=True,
                    notion_cover_synced=bool(item.get("notion_cover_synced")),
                )
        elif item_id:
            update_inventory_notion_sync_flags(
                int(item_id),
                notion_row_synced=False,
                notion_cover_synced=bool(item.get("notion_cover_synced")),
            )
            update_inventory_notion_sync_status(int(item_id), "failed")

        if progress_callback:
            progress_callback(
                {
                    "current_item": item_name,
                    "step_completed": True,
                    "row_status": "synced" if row_ok else "failed",
                    "detail": f"Row synced for {item_name}." if row_ok else f"Row sync failed for {item_name}.",
                }
            )

        if not has_image:
            if item_id:
                update_inventory_notion_sync_status(
                    int(item_id),
                    "synced" if row_ok else "failed",
                )
            continue

        if stop_event and stop_event.is_set():
            break

        image_ok = False
        if page_id is not None:
            image_ok = update_notion_inventory_image(
                token,
                database_id,
                image_path,
                page_id=page_id,
                barcode=item.get("barcode"),
                stop_event=stop_event,
            )
            if image_ok:
                synced_images += 1
        if item_id:
            update_inventory_notion_sync_flags(
                int(item_id),
                notion_row_synced=bool(item.get("notion_row_synced")) or row_ok,
                notion_cover_synced=image_ok,
            )
            update_inventory_notion_sync_status(
                int(item_id),
                "synced" if row_ok and image_ok else "failed",
            )

        if progress_callback:
            progress_callback(
                {
                    "current_item": item_name,
                    "step_completed": True,
                    "image_status": "synced" if image_ok else "failed",
                    "detail": (
                        f"Image uploaded for {item_name}."
                        if image_ok
                        else f"Image upload failed for {item_name}."
                    ),
                }
            )

    return synced_rows, synced_images


def _resolve_inventory_image_path(image_path: str | None) -> Path | None:
    if not image_path:
        return None

    path = Path(image_path)
    if not path.is_absolute():
        path = MEDIA_ROOT / path
    if not path.exists() or not path.is_file():
        return None
    return path


def _get_primary_data_source(notion: NotionClient, database_id: str) -> dict | None:
    db = notion.databases.retrieve(database_id=database_id)
    sources = [
        notion.data_sources.retrieve(data_source_id=src.get("id"))
        for src in db.get("data_sources", [])
    ]
    if not sources:
        return None
    return sources[0]


def _build_barcode_filter(prop_type: str | None, barcode: str) -> dict | None:
    if not barcode:
        return None
    if prop_type == "title":
        return {"property": "Barcode", "title": {"equals": barcode}}
    if prop_type == "rich_text":
        return {"property": "Barcode", "rich_text": {"equals": barcode}}
    return None


def _build_inventory_properties(properties: dict, item: dict) -> dict:
    payload: dict = {}

    def set_text(name: str, value: str | None):
        prop = properties.get(name)
        if not prop or not value:
            return
        prop_type = prop.get("type")
        if prop_type == "title":
            payload[name] = {"title": [{"text": {"content": value}}]}
        elif prop_type == "rich_text":
            payload[name] = {"rich_text": [{"text": {"content": value}}]}
        elif prop_type == "select":
            payload[name] = {"select": {"name": value}}
        elif prop_type == "multi_select":
            payload[name] = {"multi_select": [{"name": value}]}

    def set_number(name: str, value: int | None):
        prop = properties.get(name)
        if not prop or value is None:
            return
        if prop.get("type") == "number":
            payload[name] = {"number": int(value)}

    def set_date(name: str, value: str | None):
        prop = properties.get(name)
        if not prop or not value:
            return
        if prop.get("type") == "date":
            payload[name] = {"date": {"start": value}}

    set_text("Name", item.get("name"))
    set_text("Barcode", item.get("barcode"))
    set_number("Quantity", item.get("quantity"))
    set_text("Group Name", item.get("group_name"))
    set_text("Collection", item.get("collection_name"))
    set_text("Collection Category", item.get("collection_category"))
    set_text("Occasion", item.get("occasion"))
    set_text("Season", item.get("season"))
    set_text("Holiday", item.get("holiday"))
    set_text("Emotion", item.get("emotion"))
    set_text("Color", item.get("color"))
    set_text("Event", item.get("event_name"))
    set_text("Event Location", item.get("event_location"))
    set_text("Event Notes", item.get("event_notes"))
    set_date("Event Date", item.get("event_date"))

    return payload
