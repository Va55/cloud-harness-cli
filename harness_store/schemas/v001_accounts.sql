-- v001_accounts.sql
-- Account metadata table

CREATE TABLE IF NOT EXISTS accounts (
    id TEXT PRIMARY KEY,
    name TEXT,
    ou_path TEXT,
    status TEXT DEFAULT 'ACTIVE',       -- ACTIVE|SUSPENDED
    regions_enabled TEXT,               -- JSON array of region names
    last_seen TIMESTAMP DEFAULT (datetime('now')),
    discovered_at TIMESTAMP DEFAULT (datetime('now')),
    discovery_source TEXT DEFAULT 'organizations'  -- organizations|manual
);

CREATE INDEX IF NOT EXISTS idx_accounts_status ON accounts(status);
CREATE INDEX IF NOT EXISTS idx_accounts_discovered ON accounts(discovered_at);

-- Insert or update metadata for schema version
INSERT OR IGNORE INTO metadata (key, value) VALUES ('schema_version', '1');
