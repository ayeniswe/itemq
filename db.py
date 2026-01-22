import json
import sqlite3
from pathlib import Path
from typing import Protocol, Iterable, Optional

DEFAULT_DB_NAME = "itemq.db"


# =============================
# Database Protocol (Contract)
# =============================

class InventoryDB(Protocol):
    def add_inventory_item(
        self,
        name: str,
        barcode: str,
        quantity: int,
        source: str,
        image_path: Optional[str],
    ) -> int: ...

    def list_inventory(self, include_notion: bool) -> Iterable[sqlite3.Row]: ...

    def update_inventory_quantity(self, item_id: int, quantity: int) -> None: ...

    def update_inventory_name(self, item_id: int, name: str) -> None: ...

    def update_inventory_image(self, item_id: int, image_path: str) -> None: ...

    def upsert_plugin(
        self,
        name: str,
        enabled: bool,
        config: Optional[dict],
    ) -> None: ...

    def get_plugin(self, name: str) -> Optional[dict]: ...


# =============================
# SQLite Implementation
# =============================

class SQLiteInventoryDB:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn: sqlite3.Connection | None = None

    def connect(self):
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        if self.conn:
            self.conn.close()

    def init_schema(self):
        with self.conn:
            self.conn.executescript(Path("models.sql").read_text())

    # -------- Inventory Ops --------

    def add_inventory_item(
        self,
        name: str,
        barcode: str,
        quantity: int = 1,
        source: str = "local",
        image_path: Optional[str] = None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO inventory (name, barcode, quantity, source, image_path)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, barcode, quantity, source, image_path),
        )
        self.conn.commit()
        return cursor.lastrowid

    def list_inventory(self, include_notion: bool = False):
        if include_notion:
            return self.conn.execute(
                """
                SELECT id, name, barcode, quantity, image_path, source, created_at
                FROM inventory
                ORDER BY created_at DESC
                """
            ).fetchall()

        return self.conn.execute(
            """
            SELECT id, name, barcode, quantity, image_path, source, created_at
            FROM inventory
            WHERE source = 'local'
            ORDER BY created_at DESC
            """
        ).fetchall()

    def update_inventory_quantity(self, item_id: int, quantity: int):
        self.conn.execute(
            "UPDATE inventory SET quantity = ? WHERE id = ?",
            (quantity, item_id),
        )
        self.conn.commit()

    def update_inventory_name(self, item_id: int, name: str):
        self.conn.execute(
            "UPDATE inventory SET name = ? WHERE id = ?",
            (name, item_id),
        )
        self.conn.commit()

    def update_inventory_image(self, item_id: int, image_path: str):
        self.conn.execute(
            "UPDATE inventory SET image_path = ? WHERE id = ?",
            (image_path, item_id),
        )
        self.conn.commit()

    # -------- Plugin Ops --------

    def upsert_plugin(
        self,
        name: str,
        enabled: bool,
        config: Optional[dict] = None,
    ) -> None:
        payload = json.dumps(config or {})
        existing = self.conn.execute(
            "SELECT id FROM plugins WHERE name = ? ORDER BY id DESC LIMIT 1",
            (name,),
        ).fetchone()

        if existing:
            self.conn.execute(
                "UPDATE plugins SET enabled = ?, config = ? WHERE id = ?",
                (1 if enabled else 0, payload, existing["id"]),
            )
        else:
            self.conn.execute(
                "INSERT INTO plugins (name, enabled, config) VALUES (?, ?, ?)",
                (name, 1 if enabled else 0, payload),
            )

        self.conn.commit()

    def get_plugin(self, name: str) -> Optional[dict]:
        row = self.conn.execute(
            "SELECT id, name, enabled, config FROM plugins WHERE name = ?"
            " ORDER BY id DESC LIMIT 1",
            (name,),
        ).fetchone()

        if not row:
            return None

        return {
            "id": row["id"],
            "name": row["name"],
            "enabled": bool(row["enabled"]),
            "config": json.loads(row["config"]) if row["config"] else {},
        }


# =============================
# DB Factory / Singleton
# =============================

_db: InventoryDB | None = None


def init_db(db_path: Path, backend: str = "sqlite") -> InventoryDB:
    global _db

    if backend == "sqlite":
        db = SQLiteInventoryDB(db_path)
    else:
        raise ValueError(f"Unsupported backend: {backend}")

    db.connect()
    db.init_schema()
    _db = db
    return db


def get_db() -> InventoryDB:
    if _db is None:
        raise RuntimeError("Database not initialized")
    return _db


# =============================
# Backwards-Compatible Helpers
# =============================

def add_inventory_item(
    name: str,
    barcode: str,
    quantity: int = 1,
    source: str = "local",
    image_path: Optional[str] = None,
) -> int:
    return get_db().add_inventory_item(
        name, barcode, quantity, source, image_path
    )


def list_inventory(include_notion: bool = False):
    return get_db().list_inventory(include_notion)


def update_inventory_quantity(item_id: int, quantity: int):
    get_db().update_inventory_quantity(item_id, quantity)


def update_inventory_name(item_id: int, name: str):
    get_db().update_inventory_name(item_id, name)


def update_inventory_image(item_id: int, image_path: str):
    get_db().update_inventory_image(item_id, image_path)


def upsert_plugin(
    name: str,
    enabled: bool,
    config: Optional[dict] = None,
):
    get_db().upsert_plugin(name, enabled, config)


def get_plugin(name: str) -> Optional[dict]:
    return get_db().get_plugin(name)
