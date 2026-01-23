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
