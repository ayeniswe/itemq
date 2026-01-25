CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    barcode TEXT NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 1,
    image_path TEXT,
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
