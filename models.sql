CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    barcode TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    image_path TEXT,
    image_hash TEXT,
    group_name TEXT,
    collection_name TEXT,
    collection_category TEXT,
    occasion TEXT,
    season TEXT,
    holiday TEXT,
    emotion TEXT,
    color TEXT,
    event_name TEXT,
    event_date TEXT,
    event_location TEXT,
    event_notes TEXT,
    notion_page_id TEXT,
    source TEXT NOT NULL DEFAULT 'local' CHECK (source IN ('local', 'notion')),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (barcode) ON CONFLICT IGNORE
);

CREATE TABLE IF NOT EXISTS plugins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 0,
    config JSON
);

CREATE TABLE IF NOT EXISTS barcode_labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    inventory_id INTEGER NOT NULL UNIQUE,
    barcode_value TEXT NOT NULL,
    format TEXT NOT NULL,
    image_path TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    generated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (inventory_id) REFERENCES inventory(id)
);

-- Tracks user-visible changes for undo/history
CREATE TABLE IF NOT EXISTS inventory_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    action TEXT NOT NULL,
    summary TEXT NOT NULL,
    before_state JSON,
    after_state JSON,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    undone_at DATETIME
);

-- =========================
-- MIGRATIONS
-- =========================

-- [2026-04-18] add_notion_sync_fields_to_inventory
-- Adds notion_row_synced, notion_cover_synced, and notion_sync_status columns

ALTER TABLE inventory ADD COLUMN notion_row_synced INTEGER NOT NULL DEFAULT 0;
ALTER TABLE inventory ADD COLUMN notion_cover_synced INTEGER NOT NULL DEFAULT 0;
ALTER TABLE inventory ADD COLUMN notion_sync_status TEXT NOT NULL DEFAULT 'pending';
