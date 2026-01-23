from __future__ import annotations

from dataclasses import dataclass
import logging
import threading
import time
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
    setattr(fetch_database_rows, "_notion_token", token)

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


def fetch_database_rows(database_id: str) -> Iterable[dict]:
    # Requires token injected by connect_to_notion
    token = None
    if hasattr(fetch_database_rows, "_notion_token"):
        token = getattr(fetch_database_rows, "_notion_token")

    if token is None:
        raise RuntimeError("Notion token not available for row fetching")

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

                quantity = props["Quantity"]["number"]

                yield {
                    "barcode": barcode,
                    "name": name,
                    "quantity": quantity,
                }

            if not query.get("has_more"):
                break


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
