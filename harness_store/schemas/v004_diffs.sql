-- v004_diffs.sql
-- Resource diff tracking between inventory snapshots

CREATE TABLE IF NOT EXISTS resource_diffs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_a INTEGER NOT NULL REFERENCES inventory_snapshots(id),
    snapshot_b INTEGER NOT NULL REFERENCES inventory_snapshots(id),
    resource_id TEXT NOT NULL,
    change_type TEXT NOT NULL CHECK (change_type IN ('added', 'removed', 'modified')),
    path TEXT,
    old_value TEXT,
    new_value TEXT
);

CREATE INDEX IF NOT EXISTS idx_diffs_snapshot_a ON resource_diffs(snapshot_a);
CREATE INDEX IF NOT EXISTS idx_diffs_snapshot_b ON resource_diffs(snapshot_b);
