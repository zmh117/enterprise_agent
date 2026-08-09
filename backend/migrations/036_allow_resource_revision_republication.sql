-- migration: sqlite-foreign-keys-off

-- sqlite-only
CREATE TABLE mcp_resource_revision_v2 (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES mcp_resource(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  kind TEXT NOT NULL CHECK (kind IN ('DATABASE', 'REDIS', 'LOKI')),
  manifest_json TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  verification_id TEXT NOT NULL REFERENCES mcp_resource_verification(id),
  revision_status TEXT NOT NULL DEFAULT 'PUBLISHED'
    CHECK (revision_status IN ('PUBLISHED', 'DISABLED', 'ARCHIVED')),
  published_by TEXT NOT NULL REFERENCES app_user(id),
  published_at TEXT NOT NULL,
  UNIQUE(resource_id, revision)
);

-- sqlite-only
INSERT INTO mcp_resource_revision_v2
  (id, resource_id, revision, kind, manifest_json, content_hash,
   verification_id, revision_status, published_by, published_at)
SELECT id, resource_id, revision, kind, manifest_json, content_hash,
       verification_id, revision_status, published_by, published_at
  FROM mcp_resource_revision;

-- sqlite-only
DROP TABLE mcp_resource_revision;

-- sqlite-only
ALTER TABLE mcp_resource_revision_v2 RENAME TO mcp_resource_revision;

-- sqlite-only
CREATE INDEX idx_mcp_resource_revision_status
  ON mcp_resource_revision(resource_id, revision_status, revision);

-- postgres-only
ALTER TABLE mcp_resource_revision
  DROP CONSTRAINT IF EXISTS mcp_resource_revision_resource_id_content_hash_key;
