from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
from typing import Callable, Iterable, Tuple
from notion_client import Client as NotionClient, extract_database_id

from services.barcode import generate_barcode

logger = logging.getLogger(__name__)


@dataclass
class NotionJobResult:
    status: str
    payload: dict | None = None


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
) -> None:
    try:
        notion = NotionClient(auth=token)
        source = _get_primary_data_source(notion, database_id)
        if source is None:
            return
        source_id = source["id"]
        properties = source.get("properties", {})
        barcode_prop = properties.get("Barcode", {})
        prop_type = barcode_prop.get("type")
        filter_payload = _build_barcode_filter(prop_type, item.get("barcode", ""))

        existing_page_id = None
        if filter_payload:
            query = notion.data_sources.query(
                data_source_id=source_id,
                filter=filter_payload,
            )
            results = query.get("results", [])
            if results:
                existing_page_id = results[0].get("id")

        payload = _build_inventory_properties(properties, item)
        if existing_page_id:
            notion.pages.update(page_id=existing_page_id, properties=payload)
            return

        notion.pages.create(
            parent={"data_source_id": source_id},
            properties=payload,
        )
    except Exception as exc:
        logger.warning("Failed to sync local inventory item to Notion: %s", exc)


def update_notion_inventory_image(
    token: str,
    database_id: str,
    image_url: str,
    barcode: str | None = None,
) -> None:
    try:
        notion = NotionClient(auth=token)
        source = _get_primary_data_source(notion, database_id)
        if source is None:
            return
        source_id = source["id"]
        properties = source.get("properties", {})
        image_field = None
        for name, prop in properties.items():
            if name.lower() in {"image", "images"} and prop.get("type") == "files":
                image_field = name
                break
        if image_field is None:
            return

        barcode_prop = properties.get("Barcode", {})
        prop_type = barcode_prop.get("type")
        filter_payload = _build_barcode_filter(prop_type, barcode or "")
        if not filter_payload:
            return

        query = notion.data_sources.query(
            data_source_id=source_id,
            filter=filter_payload,
        )
        results = query.get("results", [])
        if not results:
            return

        page_id = results[0].get("id")
        notion.pages.update(
            page_id=page_id,
            properties={
                image_field: {
                    "files": [
                        {
                            "type": "external",
                            "name": "Inventory image",
                            "external": {"url": image_url},
                        }
                    ]
                }
            },
        )
    except Exception as exc:
        logger.warning("Failed to sync inventory image to Notion: %s", exc)


def sync_local_inventory_backup_to_notion(
    token: str,
    database_id: str,
    items: Iterable[dict],
    base_url: str,
) -> tuple[int, int]:
    synced_rows = 0
    synced_images = 0

    for item in items:
        if item.get("source") != "local":
            continue

        upsert_notion_inventory_item(token, database_id, item)
        synced_rows += 1

        image_path = (item.get("image_path") or "").strip()
        if not image_path:
            continue

        image_url = f"{base_url}/media/{image_path}"
        update_notion_inventory_image(
            token,
            database_id,
            image_url,
            barcode=item.get("barcode"),
        )
        synced_images += 1

    return synced_rows, synced_images


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
