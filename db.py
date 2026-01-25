import sqlite3
from pathlib import Path
from typing import Literal, Protocol, Iterable, Optional
import json

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

    def delete_inventory_by_source(self, source: str) -> None: ...

    def delete_inventory_item(self, item_id: int) -> None: ...

    def get_plugin(self, name: Literal["notion", "local"]) -> Optional[sqlite3.Row]: ...

    def upsert_plugin(self, name: str, enabled: bool, config: dict | None) -> None: ...

    def update_plugin_enabled(self, name: str, enabled: bool) -> None: ...

    def update_plugin_config(self, name: str, config: dict | None) -> None: ...

    def get_inventory_item(self, item_id: int) -> Optional[sqlite3.Row]: ...

    def get_inventory_items_by_ids(
        self,
        item_ids: Iterable[int],
    ) -> Iterable[sqlite3.Row]: ...

    def list_inventory_with_labels(
        self,
        include_notion: bool,
    ) -> Iterable[sqlite3.Row]: ...

    def get_inventory_items_with_labels_by_ids(
        self,
        item_ids: Iterable[int],
    ) -> Iterable[sqlite3.Row]: ...

    def upsert_barcode_labels(
        self,
        entries: Iterable[tuple[int, str, str, str, int]],
    ) -> None: ...

    def get_dashboard_metrics(self, low_stock_threshold: int) -> dict[str, int]: ...


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

    def delete_inventory_by_source(self, source: str):
        self.conn.execute(
            "DELETE FROM inventory WHERE source = ?",
            (source,),
        )
        self.conn.commit()

    def delete_inventory_item(self, item_id: int):
        self.conn.execute(
            "DELETE FROM barcode_labels WHERE inventory_id = ?",
            (item_id,),
        )
        self.conn.execute(
            "DELETE FROM inventory WHERE id = ?",
            (item_id,),
        )
        self.conn.commit()

    def get_inventory_item(self, item_id: int):
        return self.conn.execute(
            "SELECT id, name, barcode, quantity, image_path, source, created_at FROM inventory WHERE id = ?",
            (item_id,),
        ).fetchone()

    def get_inventory_items_by_ids(self, item_ids: Iterable[int]):
        ids = list(item_ids)
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        return self.conn.execute(
            f"""
            SELECT id, name, barcode, quantity, image_path, source, created_at
            FROM inventory
            WHERE id IN ({placeholders})
            ORDER BY created_at DESC
            """,
            ids,
        ).fetchall()

    def list_inventory_with_labels(self, include_notion: bool = False):
        base_query = """
            SELECT inventory.id,
                   inventory.name,
                   inventory.barcode,
                   inventory.quantity,
                   inventory.image_path,
                   inventory.source,
                   inventory.created_at,
                   barcode_labels.image_path AS label_path,
                   barcode_labels.format AS label_format,
                   barcode_labels.quantity AS label_quantity,
                   barcode_labels.generated_at AS label_generated_at
            FROM inventory
            LEFT JOIN barcode_labels
                ON barcode_labels.inventory_id = inventory.id
        """
        if include_notion:
            query = base_query + " ORDER BY inventory.created_at DESC"
            return self.conn.execute(query).fetchall()

        query = (
            base_query
            + " WHERE inventory.source = 'local' ORDER BY inventory.created_at DESC"
        )
        return self.conn.execute(query).fetchall()

    def get_inventory_items_with_labels_by_ids(
        self,
        item_ids: Iterable[int],
    ) -> Iterable[sqlite3.Row]:
        ids = list(item_ids)
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        return self.conn.execute(
            f"""
            SELECT inventory.id,
                   inventory.name,
                   inventory.barcode,
                   inventory.quantity,
                   inventory.image_path,
                   inventory.source,
                   inventory.created_at,
                   barcode_labels.image_path AS label_path,
                   barcode_labels.format AS label_format,
                   barcode_labels.quantity AS label_quantity,
                   barcode_labels.generated_at AS label_generated_at
            FROM inventory
            LEFT JOIN barcode_labels
                ON barcode_labels.inventory_id = inventory.id
            WHERE inventory.id IN ({placeholders})
            ORDER BY inventory.created_at DESC
            """,
            ids,
        ).fetchall()

    def upsert_barcode_labels(
        self,
        entries: Iterable[tuple[int, str, str, str, int]],
    ) -> None:
        self.conn.executemany(
            """
            INSERT INTO barcode_labels (inventory_id, barcode_value, format, image_path, quantity)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(inventory_id) DO UPDATE SET
                barcode_value = excluded.barcode_value,
                format = excluded.format,
                image_path = excluded.image_path,
                quantity = excluded.quantity,
                generated_at = CURRENT_TIMESTAMP
            """,
            list(entries),
        )
        self.conn.commit()

    def get_dashboard_metrics(self, low_stock_threshold: int) -> dict[str, int]:
        inventory_count = self.conn.execute(
            "SELECT COUNT(*) AS count FROM inventory"
        ).fetchone()["count"]
        barcode_count = self.conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS count FROM barcode_labels"
        ).fetchone()["count"]
        low_stock_count = self.conn.execute(
            "SELECT COUNT(*) AS count FROM inventory WHERE quantity <= ?",
            (low_stock_threshold,),
        ).fetchone()["count"]

        return {
            "total_items": int(inventory_count or 0),
            "total_barcodes": int(barcode_count or 0),
            "low_stock": int(low_stock_count or 0),
        }

    # -------- Plugin Ops --------

    def get_plugin(self, name: Literal["notion", "local"]) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT id, name, enabled, config FROM plugins WHERE name = ?",
            (name,),
        ).fetchone()

    def upsert_plugin(self, name: str, enabled: bool, config: dict | None) -> None:
        payload = json.dumps(config) if config is not None else None
        self.conn.execute(
            """
            INSERT INTO plugins (name, enabled, config)
            VALUES (?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET
                enabled = excluded.enabled,
                config = excluded.config
            """,
            (name, int(enabled), payload),
        )
        self.conn.commit()

    def update_plugin_enabled(self, name: str, enabled: bool) -> None:
        self.conn.execute(
            "UPDATE plugins SET enabled = ? WHERE name = ?",
            (int(enabled), name),
        )
        self.conn.commit()

    def update_plugin_config(self, name: str, config: dict | None) -> None:
        payload = json.dumps(config) if config is not None else None
        self.conn.execute(
            "UPDATE plugins SET config = ? WHERE name = ?",
            (payload, name),
        )
        self.conn.commit()


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


def delete_inventory_by_source(source: str):
    get_db().delete_inventory_by_source(source)


def delete_inventory_item(item_id: int):
    get_db().delete_inventory_item(item_id)


def get_plugin(name: Literal["notion", "local"]) -> sqlite3.Row:
    return get_db().get_plugin(name)


def upsert_plugin(name: str, enabled: bool, config: dict | None) -> None:
    get_db().upsert_plugin(name, enabled, config)


def update_plugin_enabled(name: str, enabled: bool) -> None:
    get_db().update_plugin_enabled(name, enabled)


def update_plugin_config(name: str, config: dict | None) -> None:
    get_db().update_plugin_config(name, config)


def get_inventory_item(item_id: int):
    return get_db().get_inventory_item(item_id)


def get_inventory_items_by_ids(item_ids: Iterable[int]):
    return get_db().get_inventory_items_by_ids(item_ids)


def list_inventory_with_labels(include_notion: bool = False):
    return get_db().list_inventory_with_labels(include_notion)


def get_inventory_items_with_labels_by_ids(item_ids: Iterable[int]):
    return get_db().get_inventory_items_with_labels_by_ids(item_ids)


def upsert_barcode_labels(
    entries: Iterable[tuple[int, str, str, str, int]],
) -> None:
    get_db().upsert_barcode_labels(entries)


def get_dashboard_metrics(low_stock_threshold: int = 3) -> dict[str, int]:
    return get_db().get_dashboard_metrics(low_stock_threshold)
