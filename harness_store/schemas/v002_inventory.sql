-- v002_inventory.sql
-- Resource inventory storage

CREATE TABLE IF NOT EXISTS inventory_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL REFERENCES accounts(id),
    region TEXT NOT NULL,
    service TEXT NOT NULL,
    collected_at TIMESTAMP NOT NULL DEFAULT (datetime('now')),
    schema_version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS resources (
    snapshot_id INTEGER NOT NULL REFERENCES inventory_snapshots(id),
    resource_id TEXT NOT NULL,
    arn TEXT,
    account_id TEXT NOT NULL,
    region TEXT NOT NULL,
    service TEXT NOT NULL,
    tags_json TEXT,                     -- JSON
    state TEXT,
    raw_json TEXT,                      -- full response for future use
    PRIMARY KEY (snapshot_id, resource_id)
);

CREATE INDEX IF NOT EXISTS idx_resources_account_region_service ON resources(account_id, region, service);
CREATE INDEX IF NOT EXISTS idx_resources_arn ON resources(arn);
CREATE INDEX IF NOT EXISTS idx_resources_snapshot ON resources(snapshot_id);
