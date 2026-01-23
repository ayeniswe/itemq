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
            source=row[5],
            created_at=row[6],
        )