import json
from pydantic import BaseModel

class Plugin(BaseModel):
    id: int
    name: str
    enabled: bool
    config: dict | None

    @staticmethod
    def from_row(row) -> "Plugin | None":
        if row is None:
            return None

        config = json.loads(row[3]) if row[3] else None

        return Plugin(
            id=row[0],
            name=row[1],
            enabled=bool(row[2]),
            config=config,
        )


# InventoryItem model
class InventoryItem(BaseModel):
    id: int
    name: str
    barcode: str
    quantity: int
    image_path: str | None
    image_hash: str | None
    group_name: str | None
    collection_name: str | None
    collection_category: str | None
    occasion: str | None
    season: str | None
    holiday: str | None
    emotion: str | None
    color: str | None
    event_name: str | None
    event_date: str | None
    event_location: str | None
    event_notes: str | None
    notion_page_id: str | None
    source: str
    created_at: str

    @staticmethod
    def from_row(row) -> "InventoryItem | None":
        if row is None:
            return None

        return InventoryItem(
            id=row[0],
            name=row[1],
            barcode=row[2],
            quantity=row[3],
            image_path=row[4],
            image_hash=row[5],
            group_name=row[6],
            collection_name=row[7],
            collection_category=row[8],
            occasion=row[9],
            season=row[10],
            holiday=row[11],
            emotion=row[12],
            color=row[13],
            event_name=row[14],
            event_date=row[15],
            event_location=row[16],
            event_notes=row[17],
            notion_page_id=row[18],
            source=row[19],
            created_at=row[20],
        )
