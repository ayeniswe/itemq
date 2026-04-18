ALTER TABLE inventory ADD COLUMN notion_row_synced INTEGER NOT NULL DEFAULT 0;
ALTER TABLE inventory ADD COLUMN notion_cover_synced INTEGER NOT NULL DEFAULT 0;
ALTER TABLE inventory ADD COLUMN notion_sync_status TEXT NOT NULL DEFAULT 'pending';
