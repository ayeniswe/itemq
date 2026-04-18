import sqlite3
from pathlib import Path
from typing import Literal, Protocol, Iterable, Optional

from config import MEDIA_ROOT
import json


DEFAULT_DB_NAME = "itemq.db"
MIGRATIONS_DIR = Path("migrations")
BASE_SQL_PATH = MIGRATIONS_DIR / "models.sql"


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
        image_hash: Optional[str],
        group_name: Optional[str],
        collection_name: Optional[str],
        collection_category: Optional[str],
        occasion: Optional[str],
        season: Optional[str],
        holiday: Optional[str],
        emotion: Optional[str],
        color: Optional[str],
        event_name: Optional[str],
        event_date: Optional[str],
        event_location: Optional[str],
        event_notes: Optional[str],
        notion_page_id: Optional[str],
    ) -> int: ...

    def list_inventory(
        self,
        include_notion: bool,
        filters: dict[str, str | None],
        limit: int,
        offset: int,
    ) -> Iterable[sqlite3.Row]: ...

    def count_inventory(
        self,
        include_notion: bool,
        filters: dict[str, str | None],
    ) -> int: ...

    def get_inventory_totals(self, include_notion: bool) -> dict[str, int]: ...

    def update_inventory_quantity(self, item_id: int, quantity: int) -> None: ...

    def update_inventory_name(self, item_id: int, name: str) -> None: ...

    def update_inventory_image(self, item_id: int, image_path: Optional[str]) -> None: ...

    def update_inventory_image_hash(self, item_id: int, image_hash: Optional[str]) -> None: ...

    def update_inventory_notion_page_id(
        self,
        item_id: int,
        notion_page_id: Optional[str],
    ) -> None: ...

    def update_inventory_notion_sync_flags(
        self,
        item_id: int,
        notion_row_synced: bool,
        notion_cover_synced: bool,
    ) -> None: ...

    def update_inventory_notion_sync_status(
        self,
        item_id: int,
        notion_sync_status: str,
    ) -> None: ...

    def reset_inventory_notion_syncing_to_pending(self) -> None: ...

    def update_inventory_details(
        self,
        item_id: int,
        group_name: Optional[str],
        collection_name: Optional[str],
        collection_category: Optional[str],
        occasion: Optional[str],
        season: Optional[str],
        holiday: Optional[str],
        emotion: Optional[str],
        color: Optional[str],
        event_name: Optional[str],
        event_date: Optional[str],
        event_location: Optional[str],
        event_notes: Optional[str],
    ) -> None: ...

    def delete_inventory_by_source(self, source: str) -> None: ...

    def delete_inventory_item(self, item_id: int) -> None: ...

    def get_plugin(self, name: Literal["notion", "local"]) -> Optional[sqlite3.Row]: ...

    def upsert_plugin(self, name: str, enabled: bool, config: dict | None) -> None: ...

    def update_plugin_enabled(self, name: str, enabled: bool) -> None: ...

    def update_plugin_config(self, name: str, config: dict | None) -> None: ...

    def get_inventory_item(self, item_id: int) -> Optional[sqlite3.Row]: ...

    def get_inventory_item_by_barcode(
        self, barcode: str
    ) -> Optional[sqlite3.Row]: ...

    def get_inventory_items_by_ids(
        self,
        item_ids: Iterable[int],
    ) -> Iterable[sqlite3.Row]: ...

    def list_inventory_with_labels(
        self,
        include_notion: bool,
        filters: dict[str, str | None],
        limit: int,
        offset: int,
    ) -> Iterable[sqlite3.Row]: ...

    def count_inventory_with_labels(
        self,
        include_notion: bool,
        filters: dict[str, str | None],
    ) -> int: ...

    def get_inventory_filter_options(
        self,
        include_notion: bool,
    ) -> dict[str, list[str]]: ...

    def get_inventory_items_with_labels_by_ids(
        self,
        item_ids: Iterable[int],
    ) -> Iterable[sqlite3.Row]: ...

    def upsert_barcode_labels(
        self,
        entries: Iterable[tuple[int, str, str, str, int]],
    ) -> None: ...

    def get_dashboard_metrics(self, low_stock_threshold: int) -> dict[str, int]: ...

    def has_migration(self, name: str) -> bool: ...

    def record_migration(self, name: str) -> None: ...

    def apply_sql_migration(self, name: str, sql: str) -> None: ...

    # History / undo
    def add_history_entry(
        self,
        action: str,
        summary: str,
        before_state: dict | list | None,
        after_state: dict | list | None,
    ) -> int: ...

    def list_history(self, limit: int = 50) -> Iterable[sqlite3.Row]: ...

    def get_history_entry(self, history_id: int) -> Optional[sqlite3.Row]: ...

    def mark_history_undone(self, history_id: int) -> None: ...

    def update_inventory_full(self, item_id: int, state: dict) -> None: ...

    def mark_history_redone(self, history_id: int) -> None: ...

    def latest_pending_history(self) -> Optional[sqlite3.Row]: ...

    def latest_redo_candidate(self) -> Optional[sqlite3.Row]: ...

    # History / undo
    def add_history_entry(
        self,
        action: str,
        summary: str,
        before_state: dict | list | None,
        after_state: dict | list | None,
    ) -> int: ...

    def list_history(self, limit: int = 50) -> Iterable[sqlite3.Row]: ...

    def get_history_entry(self, history_id: int) -> Optional[sqlite3.Row]: ...

    def mark_history_undone(self, history_id: int) -> None: ...


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
        # Expose a tiny helper to check if an image file actually exists on disk
        self.conn.create_function("file_exists", 1, self._file_exists)

    def _file_exists(self, image_path: Optional[str]) -> int:
        if not image_path:
            return 0
        path = Path(image_path)
        if not path.is_absolute():
            path = MEDIA_ROOT / path
        return 1 if path.exists() else 0

    def close(self):
        if self.conn:
            self.conn.close()

    def init_schema(self):
        with self.conn:
            self.conn.executescript(BASE_SQL_PATH.read_text())
            self._apply_pending_migrations()
            self._ensure_inventory_columns()
            self._ensure_history_table()
            
    def has_migration(self, name: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM schema_migrations WHERE name = ?",
            (name,),
        ).fetchone()
        return row is not None

    def record_migration(self, name: str) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO schema_migrations (name) VALUES (?)",
            (name,),
        )

    def apply_sql_migration(self, name: str, sql: str) -> None:
        if self.has_migration(name):
            return
        self.conn.executescript(sql)
        self.record_migration(name)

    def _apply_pending_migrations(self) -> None:
        if not MIGRATIONS_DIR.exists():
            return

        migration_files = sorted(
            path
            for path in MIGRATIONS_DIR.glob("*.sql")
            if path.name != "models.sql"
        )

        for migration_path in migration_files:
            migration_name = migration_path.name
            if self.has_migration(migration_name):
                continue
            self.apply_sql_migration(migration_name, migration_path.read_text())

    def _ensure_inventory_columns(self) -> None:
        columns = {
            row["name"]: row["type"]
            for row in self.conn.execute("PRAGMA table_info(inventory)").fetchall()
        }
        desired_columns = {
            "image_hash": {
                "type": "TEXT",
                "migration": "legacy_add_inventory_image_hash",
            },
            "group_name": {
                "type": "TEXT",
                "migration": "legacy_add_inventory_group_name",
            },
            "collection_name": {
                "type": "TEXT",
                "migration": "legacy_add_inventory_collection_name",
            },
            "collection_category": {
                "type": "TEXT",
                "migration": "legacy_add_inventory_collection_category",
            },
            "occasion": {
                "type": "TEXT",
                "migration": "legacy_add_inventory_occasion",
            },
            "season": {
                "type": "TEXT",
                "migration": "legacy_add_inventory_season",
            },
            "holiday": {
                "type": "TEXT",
                "migration": "legacy_add_inventory_holiday",
            },
            "emotion": {
                "type": "TEXT",
                "migration": "legacy_add_inventory_emotion",
            },
            "color": {
                "type": "TEXT",
                "migration": "legacy_add_inventory_color",
            },
            "event_name": {
                "type": "TEXT",
                "migration": "legacy_add_inventory_event_name",
            },
            "event_date": {
                "type": "TEXT",
                "migration": "legacy_add_inventory_event_date",
            },
            "event_location": {
                "type": "TEXT",
                "migration": "legacy_add_inventory_event_location",
            },
            "event_notes": {
                "type": "TEXT",
                "migration": "legacy_add_inventory_event_notes",
            },
            "notion_page_id": {
                "type": "TEXT",
                "migration": "legacy_add_inventory_notion_page_id",
            },
            "notion_row_synced": {
                "type": "INTEGER NOT NULL DEFAULT 0",
                "migration": "legacy_add_inventory_notion_row_synced",
            },
            "notion_cover_synced": {
                "type": "INTEGER NOT NULL DEFAULT 0",
                "migration": "legacy_add_inventory_notion_cover_synced",
            },
            "notion_sync_status": {
                "type": "TEXT NOT NULL DEFAULT 'pending'",
                "migration": "legacy_add_inventory_notion_sync_status",
            },
        }

        for column, spec in desired_columns.items():
            if column not in columns:
                self.apply_sql_migration(
                    spec["migration"],
                    f"ALTER TABLE inventory ADD COLUMN {column} {spec['type']};"
                )

    def _ensure_history_table(self) -> None:
        exists = self.conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table' AND name='inventory_history'
            """
        ).fetchone()
        if not exists:
            self.conn.executescript(BASE_SQL_PATH.read_text())

    def _ensure_history_table(self) -> None:
        exists = self.conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type='table' AND name='inventory_history'
            """
        ).fetchone()
        if not exists:
            self.conn.executescript(
                BASE_SQL_PATH.read_text()
            )

    # -------- Inventory Ops --------

    def add_inventory_item(
        self,
        name: str,
        barcode: str,
        quantity: int = 0,
        source: str = "local",
        image_path: Optional[str] = None,
        image_hash: Optional[str] = None,
        group_name: Optional[str] = None,
        collection_name: Optional[str] = None,
        collection_category: Optional[str] = None,
        occasion: Optional[str] = None,
        season: Optional[str] = None,
        holiday: Optional[str] = None,
        emotion: Optional[str] = None,
        color: Optional[str] = None,
        event_name: Optional[str] = None,
        event_date: Optional[str] = None,
        event_location: Optional[str] = None,
        event_notes: Optional[str] = None,
        notion_page_id: Optional[str] = None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO inventory (
                name,
                barcode,
                quantity,
                source,
                image_path,
                image_hash,
                group_name,
                collection_name,
                collection_category,
                occasion,
                season,
                holiday,
                emotion,
                color,
                event_name,
                event_date,
                event_location,
                event_notes,
                notion_page_id,
                notion_row_synced,
                notion_cover_synced,
                notion_sync_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, 'pending')
            """,
            (
                name,
                barcode,
                quantity,
                source,
                image_path,
                image_hash,
                group_name,
                collection_name,
                collection_category,
                occasion,
                season,
                holiday,
                emotion,
                color,
                event_name,
                event_date,
                event_location,
                event_notes,
                notion_page_id,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def _build_inventory_filters(
        self,
        include_notion: bool,
        filters: dict[str, str | None],
        table_alias: str = "inventory",
    ) -> tuple[str, list[object]]:
        conditions = []
        params: list[object] = []

        if not include_notion:
            conditions.append(f"{table_alias}.source = 'local'")

        search = (filters.get("search") or "").strip()
        search_case = (filters.get("search_case") or "insensitive").strip().lower()
        case_sensitive = search_case == "sensitive"
        if search:
            search_tokens = [token for token in search.split() if token]
            search_columns = [
                "name",
                "barcode",
                "group_name",
                "collection_name",
                "collection_category",
                "occasion",
                "season",
                "holiday",
                "emotion",
                "color",
                "event_name",
                "event_date",
                "event_location",
                "event_notes",
            ]
            token_groups = []
            for token in search_tokens:
                needle = token if case_sensitive else token.lower()
                token_conditions = []
                for column in search_columns:
                    if case_sensitive:
                        token_conditions.append(
                            f"INSTR(COALESCE({table_alias}.{column}, ''), ?) > 0"
                        )
                    else:
                        token_conditions.append(
                            f"INSTR(LOWER(COALESCE({table_alias}.{column}, '')), ?) > 0"
                        )
                    params.append(needle)
                token_groups.append("(" + " OR ".join(token_conditions) + ")")
            if token_groups:
                conditions.append("(" + " AND ".join(token_groups) + ")")

        filter_columns = {
            "group_name": "group_name",
            "collection_name": "collection_name",
            "collection_category": "collection_category",
            "occasion": "occasion",
            "season": "season",
            "holiday": "holiday",
            "emotion": "emotion",
            "color": "color",
            "event_name": "event_name",
        }

        for filter_key, column in filter_columns.items():
            value = (filters.get(filter_key) or "").strip()
            if value:
                conditions.append(f"{table_alias}.{column} = ?")
                params.append(value)

        created_from = (filters.get("created_from") or "").strip()
        if created_from:
            conditions.append(f"datetime({table_alias}.created_at) >= datetime(?)")
            params.append(created_from)

        created_to = (filters.get("created_to") or "").strip()
        if created_to:
            conditions.append(f"datetime({table_alias}.created_at) <= datetime(?)")
            params.append(created_to)

        image_status = (filters.get("image_status") or "").strip().lower()
        if image_status == "missing":
            # Missing explicit path, empty string, file not present, or known placeholder filenames
            conditions.append(
                "("
                f" {table_alias}.image_path IS NULL OR "
                f" TRIM({table_alias}.image_path) = '' OR "
                f" file_exists({table_alias}.image_path) = 0 OR "
                f" LOWER({table_alias}.image_path) LIKE '%default%' OR "
                f" LOWER({table_alias}.image_path) LIKE '%placeholder%'"
                ")"
            )
        elif image_status == "present":
            conditions.append(
                "("
                f" {table_alias}.image_path IS NOT NULL AND "
                f" TRIM({table_alias}.image_path) <> '' AND "
                f" file_exists({table_alias}.image_path) = 1"
                ")"
            )

        where_clause = ""
        if conditions:
            where_clause = " WHERE " + " AND ".join(conditions)

        return where_clause, params

    def _inventory_select_fields(self) -> str:
        return """
            id,
            name,
            barcode,
            quantity,
            image_path,
            image_hash,
            group_name,
            collection_name,
            collection_category,
            occasion,
            season,
            holiday,
            emotion,
            color,
            event_name,
            event_date,
            event_location,
            event_notes,
            notion_page_id,
            notion_row_synced,
            notion_cover_synced,
            notion_sync_status,
            source,
            created_at
        """

    def list_inventory(
        self,
        include_notion: bool = False,
        filters: dict[str, str | None] | None = None,
        limit: int = 25,
        offset: int = 0,
    ):
        filters = filters or {}
        where_clause, params = self._build_inventory_filters(include_notion, filters)
        query = f"""
            SELECT {self._inventory_select_fields()}
            FROM inventory
            {where_clause}
            ORDER BY barcode COLLATE NOCASE ASC, created_at DESC
            LIMIT ? OFFSET ?
        """
        return self.conn.execute(query, (*params, limit, offset)).fetchall()

    def count_inventory(
        self,
        include_notion: bool,
        filters: dict[str, str | None] | None = None,
    ) -> int:
        filters = filters or {}
        where_clause, params = self._build_inventory_filters(include_notion, filters)
        query = f"SELECT COUNT(*) AS count FROM inventory {where_clause}"
        return int(self.conn.execute(query, params).fetchone()["count"] or 0)

    def get_inventory_totals(self, include_notion: bool) -> dict[str, int]:
        where_clause, params = self._build_inventory_filters(
            include_notion, {}, table_alias="inventory"
        )
        query = f"""
            SELECT COUNT(*) AS count, COALESCE(SUM(quantity), 0) AS total_quantity
            FROM inventory
            {where_clause}
        """
        row = self.conn.execute(query, params).fetchone()
        return {
            "total_items": int(row["count"] or 0),
            "total_quantity": int(row["total_quantity"] or 0),
        }

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

    def update_inventory_image(self, item_id: int, image_path: Optional[str]):
        self.conn.execute(
            "UPDATE inventory SET image_path = ? WHERE id = ?",
            (image_path, item_id),
        )
        self.conn.commit()

    def update_inventory_image_hash(self, item_id: int, image_hash: Optional[str]):
        self.conn.execute(
            "UPDATE inventory SET image_hash = ? WHERE id = ?",
            (image_hash, item_id),
        )
        self.conn.commit()

    def update_inventory_notion_page_id(
        self,
        item_id: int,
        notion_page_id: Optional[str],
    ) -> None:
        self.conn.execute(
            "UPDATE inventory SET notion_page_id = ? WHERE id = ?",
            (notion_page_id, item_id),
        )
        self.conn.commit()

    def update_inventory_notion_sync_flags(
        self,
        item_id: int,
        notion_row_synced: bool,
        notion_cover_synced: bool,
    ) -> None:
        self.conn.execute(
            """
            UPDATE inventory
            SET notion_row_synced = ?, notion_cover_synced = ?
            WHERE id = ?
            """,
            (int(notion_row_synced), int(notion_cover_synced), item_id),
        )
        self.conn.commit()

    def update_inventory_notion_sync_status(
        self,
        item_id: int,
        notion_sync_status: str,
    ) -> None:
        self.conn.execute(
            "UPDATE inventory SET notion_sync_status = ? WHERE id = ?",
            (notion_sync_status, item_id),
        )
        self.conn.commit()

    def reset_inventory_notion_syncing_to_pending(self) -> None:
        self.conn.execute(
            """
            UPDATE inventory
            SET notion_sync_status = 'pending'
            WHERE source = 'local' AND notion_sync_status = 'syncing'
            """
        )
        self.conn.commit()

    def update_inventory_details(
        self,
        item_id: int,
        group_name: Optional[str],
        collection_name: Optional[str],
        collection_category: Optional[str],
        occasion: Optional[str],
        season: Optional[str],
        holiday: Optional[str],
        emotion: Optional[str],
        color: Optional[str],
        event_name: Optional[str],
        event_date: Optional[str],
        event_location: Optional[str],
        event_notes: Optional[str],
    ) -> None:
        self.conn.execute(
            """
            UPDATE inventory
            SET group_name = ?,
                collection_name = ?,
                collection_category = ?,
                occasion = ?,
                season = ?,
                holiday = ?,
                emotion = ?,
                color = ?,
                event_name = ?,
                event_date = ?,
                event_location = ?,
                event_notes = ?
            WHERE id = ?
            """,
            (
                group_name,
                collection_name,
                collection_category,
                occasion,
                season,
                holiday,
                emotion,
                color,
                event_name,
                event_date,
                event_location,
                event_notes,
                item_id,
            ),
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
            f"""
            SELECT {self._inventory_select_fields()}
            FROM inventory
            WHERE id = ?
            """,
            (item_id,),
        ).fetchone()

    def get_inventory_item_by_barcode(self, barcode: str):
        return self.conn.execute(
            f"""
            SELECT {self._inventory_select_fields()}
            FROM inventory
            WHERE barcode = ?
            """,
            (barcode,),
        ).fetchone()

    def get_inventory_items_by_ids(self, item_ids: Iterable[int]):
        ids = list(item_ids)
        if not ids:
            return []
        placeholders = ", ".join("?" for _ in ids)
        return self.conn.execute(
            f"""
            SELECT {self._inventory_select_fields()}
            FROM inventory
            WHERE id IN ({placeholders})
            ORDER BY barcode COLLATE NOCASE ASC, created_at DESC
            """,
            ids,
        ).fetchall()

    def list_inventory_with_labels(
        self,
        include_notion: bool = False,
        filters: dict[str, str | None] | None = None,
        limit: int = 25,
        offset: int = 0,
    ):
        filters = filters or {}
        base_query = """
            SELECT inventory.id,
                   inventory.name,
                   inventory.barcode,
                   inventory.quantity,
                   inventory.image_path,
                   inventory.image_hash,
                   inventory.group_name,
                   inventory.collection_name,
                   inventory.collection_category,
                   inventory.occasion,
                   inventory.season,
                   inventory.holiday,
                   inventory.emotion,
                   inventory.color,
                   inventory.event_name,
                   inventory.event_date,
                   inventory.event_location,
                   inventory.event_notes,
                   inventory.notion_page_id,
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
        where_clause, params = self._build_inventory_filters(
            include_notion, filters, table_alias="inventory"
        )
        query = (
            base_query
            + where_clause
            + " ORDER BY inventory.barcode COLLATE NOCASE ASC, inventory.created_at DESC"
            + " LIMIT ? OFFSET ?"
        )
        return self.conn.execute(query, (*params, limit, offset)).fetchall()

    def list_inventory_label_state(
        self,
        include_notion: bool = False,
        filters: dict[str, str | None] | None = None,
    ):
        """
        Lightweight listing that returns only selection-relevant fields.
        """
        filters = filters or {}
        where_clause, params = self._build_inventory_filters(
            include_notion, filters, table_alias="inventory"
        )
        query = f"""
            SELECT
                inventory.id AS id,
                barcode_labels.image_path AS label_path,
                barcode_labels.quantity AS label_quantity
            FROM inventory
            LEFT JOIN barcode_labels
                ON barcode_labels.inventory_id = inventory.id
            {where_clause}
        """
        return self.conn.execute(query, params).fetchall()

    def count_inventory_with_labels(
        self,
        include_notion: bool,
        filters: dict[str, str | None] | None = None,
    ) -> int:
        filters = filters or {}
        where_clause, params = self._build_inventory_filters(
            include_notion, filters, table_alias="inventory"
        )
        query = f"""
            SELECT COUNT(*) AS count
            FROM inventory
            LEFT JOIN barcode_labels
                ON barcode_labels.inventory_id = inventory.id
            {where_clause}
        """
        return int(self.conn.execute(query, params).fetchone()["count"] or 0)

    def get_inventory_filter_options(self, include_notion: bool) -> dict[str, list[str]]:
        filters = {}
        where_clause, params = self._build_inventory_filters(include_notion, {})
        filter_where = where_clause or " WHERE 1=1"
        fields = [
            "group_name",
            "collection_name",
            "collection_category",
            "occasion",
            "season",
            "holiday",
            "emotion",
            "color",
            "event_name",
        ]
        for field in fields:
            query = f"""
                SELECT DISTINCT {field} AS value
                FROM inventory
                {filter_where}
                AND {field} IS NOT NULL
                AND TRIM({field}) != ''
                ORDER BY {field} COLLATE NOCASE ASC
            """
            rows = self.conn.execute(query, params).fetchall()
            filters[field] = [row["value"] for row in rows]
        return filters

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
                   inventory.image_hash,
                   inventory.group_name,
                   inventory.collection_name,
                   inventory.collection_category,
                   inventory.occasion,
                   inventory.season,
                   inventory.holiday,
                   inventory.emotion,
                   inventory.color,
                   inventory.event_name,
                   inventory.event_date,
                   inventory.event_location,
                   inventory.event_notes,
                   inventory.notion_page_id,
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
            ORDER BY inventory.barcode COLLATE NOCASE ASC, inventory.created_at DESC
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
        total_quantity = self.conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS total_quantity FROM inventory"
        ).fetchone()["total_quantity"]
        low_stock_count = self.conn.execute(
            "SELECT COUNT(*) AS count FROM inventory WHERE quantity <= ?",
            (low_stock_threshold,),
        ).fetchone()["count"]

        return {
            "total_items": int(inventory_count or 0),
            "total_quantity": int(total_quantity or 0),
            "low_stock": int(low_stock_count or 0),
        }

    # -------- History / Undo --------

    def add_history_entry(
        self,
        action: str,
        summary: str,
        before_state: dict | list | None,
        after_state: dict | list | None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO inventory_history (action, summary, before_state, after_state)
            VALUES (?, ?, json(?), json(?))
            """,
            (
                action,
                summary,
                json.dumps(before_state) if before_state is not None else None,
                json.dumps(after_state) if after_state is not None else None,
            ),
        )
        self.conn.commit()
        return cursor.lastrowid

    def list_history(self, limit: int = 50):
        return self.conn.execute(
            """
            SELECT id, action, summary, before_state, after_state, created_at, undone_at
            FROM inventory_history
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def get_history_entry(self, history_id: int):
        return self.conn.execute(
            """
            SELECT id, action, summary, before_state, after_state, created_at, undone_at
            FROM inventory_history
            WHERE id = ?
            """,
            (history_id,),
        ).fetchone()

    def mark_history_undone(self, history_id: int) -> None:
        self.conn.execute(
            "UPDATE inventory_history SET undone_at = CURRENT_TIMESTAMP WHERE id = ?",
            (history_id,),
        )
        self.conn.commit()

    def mark_history_redone(self, history_id: int) -> None:
        self.conn.execute(
            "UPDATE inventory_history SET undone_at = NULL WHERE id = ?",
            (history_id,),
        )
        self.conn.commit()

    def latest_pending_history(self):
        return self.conn.execute(
            """
            SELECT id, action, summary, before_state, after_state, created_at, undone_at
            FROM inventory_history
            WHERE undone_at IS NULL
            ORDER BY created_at DESC
            LIMIT 1
            """
        ).fetchone()

    def latest_redo_candidate(self):
        return self.conn.execute(
            """
            SELECT id, action, summary, before_state, after_state, created_at, undone_at
            FROM inventory_history
            WHERE undone_at IS NOT NULL
            ORDER BY undone_at DESC, created_at DESC
            LIMIT 1
            """
        ).fetchone()

    def update_inventory_full(self, item_id: int, state: dict) -> None:
        self.conn.execute(
            """
            UPDATE inventory
            SET name = ?,
                barcode = ?,
                quantity = ?,
                image_path = ?,
                image_hash = ?,
                group_name = ?,
                collection_name = ?,
                collection_category = ?,
                occasion = ?,
                season = ?,
                holiday = ?,
                emotion = ?,
                color = ?,
                event_name = ?,
                event_date = ?,
                event_location = ?,
                event_notes = ?,
                notion_page_id = ?,
                notion_row_synced = ?,
                notion_cover_synced = ?,
                notion_sync_status = ?,
                source = ?\n            WHERE id = ?\n            """,
            (
                state.get("name"),
                state.get("barcode"),
                state.get("quantity"),
                state.get("image_path"),
                state.get("image_hash"),
                state.get("group_name"),
                state.get("collection_name"),
                state.get("collection_category"),
                state.get("occasion"),
                state.get("season"),
                state.get("holiday"),
                state.get("emotion"),
                state.get("color"),
                state.get("event_name"),
                state.get("event_date"),
                state.get("event_location"),
                state.get("event_notes"),
                state.get("notion_page_id"),
                int(bool(state.get("notion_row_synced"))),
                int(bool(state.get("notion_cover_synced"))),
                state.get("notion_sync_status", "pending"),
                state.get("source", "local"),
                item_id,
            ),
        )
        self.conn.commit()

    # -------- History / Undo --------

    def add_history_entry(
        self,
        action: str,
        summary: str,
        before_state: dict | list | None,
        after_state: dict | list | None,
    ) -> int:
        cursor = self.conn.execute(
            """
            INSERT INTO inventory_history (action, summary, before_state, after_state)
            VALUES (?, ?, json(?), json(?))
            """,
            (action, summary, json.dumps(before_state) if before_state is not None else None,
             json.dumps(after_state) if after_state is not None else None),
        )
        self.conn.commit()
        return cursor.lastrowid

    def list_history(self, limit: int = 50):
        return self.conn.execute(
            """
            SELECT id, action, summary, before_state, after_state, created_at, undone_at
            FROM inventory_history
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    def get_history_entry(self, history_id: int):
        return self.conn.execute(
            """
            SELECT id, action, summary, before_state, after_state, created_at, undone_at
            FROM inventory_history
            WHERE id = ?
            """,
            (history_id,),
        ).fetchone()

    def mark_history_undone(self, history_id: int) -> None:
        self.conn.execute(
            "UPDATE inventory_history SET undone_at = CURRENT_TIMESTAMP WHERE id = ?",
            (history_id,),
        )
        self.conn.commit()

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
    quantity: int = 0,
    source: str = "local",
    image_path: Optional[str] = None,
    image_hash: Optional[str] = None,
    group_name: Optional[str] = None,
    collection_name: Optional[str] = None,
    collection_category: Optional[str] = None,
    occasion: Optional[str] = None,
    season: Optional[str] = None,
    holiday: Optional[str] = None,
    emotion: Optional[str] = None,
    color: Optional[str] = None,
    event_name: Optional[str] = None,
    event_date: Optional[str] = None,
    event_location: Optional[str] = None,
    event_notes: Optional[str] = None,
    notion_page_id: Optional[str] = None,
) -> int:
    return get_db().add_inventory_item(
        name,
        barcode,
        quantity,
        source,
        image_path,
        image_hash,
        group_name,
        collection_name,
        collection_category,
        occasion,
        season,
        holiday,
        emotion,
        color,
        event_name,
        event_date,
        event_location,
        event_notes,
        notion_page_id,
    )


def list_inventory(
    include_notion: bool = False,
    filters: dict[str, str | None] | None = None,
    limit: int = 25,
    offset: int = 0,
):
    return get_db().list_inventory(include_notion, filters or {}, limit, offset)


def count_inventory(
    include_notion: bool = False,
    filters: dict[str, str | None] | None = None,
):
    return get_db().count_inventory(include_notion, filters or {})


def get_inventory_totals(include_notion: bool = False) -> dict[str, int]:
    return get_db().get_inventory_totals(include_notion)


def update_inventory_quantity(item_id: int, quantity: int):
    get_db().update_inventory_quantity(item_id, quantity)


def update_inventory_name(item_id: int, name: str):
    get_db().update_inventory_name(item_id, name)


def update_inventory_image(item_id: int, image_path: Optional[str]):
    get_db().update_inventory_image(item_id, image_path)


def update_inventory_image_hash(item_id: int, image_hash: Optional[str]):
    get_db().update_inventory_image_hash(item_id, image_hash)


def update_inventory_notion_page_id(item_id: int, notion_page_id: Optional[str]):
    get_db().update_inventory_notion_page_id(item_id, notion_page_id)


def update_inventory_notion_sync_flags(
    item_id: int,
    notion_row_synced: bool,
    notion_cover_synced: bool,
):
    get_db().update_inventory_notion_sync_flags(
        item_id,
        notion_row_synced,
        notion_cover_synced,
    )


def update_inventory_notion_sync_status(item_id: int, notion_sync_status: str):
    get_db().update_inventory_notion_sync_status(item_id, notion_sync_status)


def reset_inventory_notion_syncing_to_pending():
    get_db().reset_inventory_notion_syncing_to_pending()


def update_inventory_details(
    item_id: int,
    group_name: Optional[str],
    collection_name: Optional[str],
    collection_category: Optional[str],
    occasion: Optional[str],
    season: Optional[str],
    holiday: Optional[str],
    emotion: Optional[str],
    color: Optional[str],
    event_name: Optional[str],
    event_date: Optional[str],
    event_location: Optional[str],
    event_notes: Optional[str],
):
    get_db().update_inventory_details(
        item_id,
        group_name,
        collection_name,
        collection_category,
        occasion,
        season,
        holiday,
        emotion,
        color,
        event_name,
        event_date,
        event_location,
        event_notes,
    )

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


def get_inventory_item_by_barcode(barcode: str):
    return get_db().get_inventory_item_by_barcode(barcode)


def get_inventory_items_by_ids(item_ids: Iterable[int]):
    return get_db().get_inventory_items_by_ids(item_ids)


def list_inventory_with_labels(include_notion: bool = False):
    return get_db().list_inventory_with_labels(include_notion)


def list_inventory_with_labels_paginated(
    include_notion: bool = False,
    filters: dict[str, str | None] | None = None,
    limit: int = 25,
    offset: int = 0,
):
    return get_db().list_inventory_with_labels(
        include_notion,
        filters or {},
        limit,
        offset,
    )


def list_inventory_label_state(
    include_notion: bool = False,
    filters: dict[str, str | None] | None = None,
):
    return get_db().list_inventory_label_state(
        include_notion,
        filters or {},
    )


def count_inventory_with_labels(
    include_notion: bool = False,
    filters: dict[str, str | None] | None = None,
):
    return get_db().count_inventory_with_labels(include_notion, filters or {})

def get_inventory_filter_options(include_notion: bool = False):
    return get_db().get_inventory_filter_options(include_notion)


def get_inventory_items_with_labels_by_ids(item_ids: Iterable[int]):
    return get_db().get_inventory_items_with_labels_by_ids(item_ids)


def upsert_barcode_labels(
    entries: Iterable[tuple[int, str, str, str, int]],
) -> None:
    get_db().upsert_barcode_labels(entries)


def get_dashboard_metrics(low_stock_threshold: int = 3) -> dict[str, int]:
    return get_db().get_dashboard_metrics(low_stock_threshold)


# -------- History / Undo helpers --------

def add_history_entry(action: str, summary: str, before_state, after_state) -> int:
    return get_db().add_history_entry(action, summary, before_state, after_state)


def list_history(limit: int = 50):
    return get_db().list_history(limit)


def get_history_entry(history_id: int):
    return get_db().get_history_entry(history_id)


def mark_history_undone(history_id: int) -> None:
    return get_db().mark_history_undone(history_id)


def update_inventory_full(item_id: int, state: dict) -> None:
    return get_db().update_inventory_full(item_id, state)


def mark_history_redone(history_id: int) -> None:
    return get_db().mark_history_redone(history_id)


def latest_pending_history():
    return get_db().latest_pending_history()


def latest_redo_candidate():
    return get_db().latest_redo_candidate()
