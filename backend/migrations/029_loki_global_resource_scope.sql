-- migration: sqlite-foreign-keys-off
-- Extend governed Resource Identity only after the additive 028 foundation.

-- SQLite cannot alter CHECK constraints in place. Keep legacy child foreign
-- keys pointing at the canonical table name while rebuilding the identity.
-- sqlite-only
PRAGMA legacy_alter_table = ON;

-- sqlite-only
ALTER TABLE platform_resource RENAME TO platform_resource_pre_global_scope;

-- sqlite-only
CREATE TABLE platform_resource (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  resource_kind TEXT NOT NULL
    CHECK (resource_kind IN ('database', 'redis', 'loki')),
  scope_type TEXT NOT NULL
    CHECK (scope_type IN ('global', 'environment', 'base', 'workshop')),
  environment_id TEXT REFERENCES platform_environment(id),
  base_id TEXT REFERENCES platform_base(id),
  workshop_id TEXT REFERENCES platform_workshop(id),
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled', 'archived')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (
    (scope_type = 'global' AND environment_id IS NULL
      AND base_id IS NULL AND workshop_id IS NULL)
    OR
    (scope_type = 'environment' AND environment_id IS NOT NULL
      AND base_id IS NULL AND workshop_id IS NULL)
    OR
    (scope_type = 'base' AND environment_id IS NOT NULL
      AND base_id IS NOT NULL AND workshop_id IS NULL)
    OR
    (scope_type = 'workshop' AND environment_id IS NOT NULL
      AND base_id IS NOT NULL AND workshop_id IS NOT NULL)
  )
);

-- sqlite-only
INSERT INTO platform_resource
  (id, code, name, resource_kind, scope_type, environment_id, base_id,
   workshop_id, status, revision, created_by, created_at, updated_at)
SELECT id, code, name, resource_kind, scope_type, environment_id, base_id,
       workshop_id, status, revision, created_by, created_at, updated_at
  FROM platform_resource_pre_global_scope;

-- sqlite-only
DROP TABLE platform_resource_pre_global_scope;

-- sqlite-only
CREATE INDEX idx_platform_resource_scope
  ON platform_resource(scope_type, environment_id, base_id, workshop_id);

-- sqlite-only
CREATE INDEX idx_platform_resource_kind_status
  ON platform_resource(resource_kind, status);

-- sqlite-only
PRAGMA legacy_alter_table = OFF;

-- postgres-only
ALTER TABLE platform_resource
  DROP CONSTRAINT platform_resource_scope_type_check;

-- postgres-only
ALTER TABLE platform_resource
  DROP CONSTRAINT platform_resource_check;

-- postgres-only
ALTER TABLE platform_resource
  ALTER COLUMN environment_id DROP NOT NULL;

-- postgres-only
ALTER TABLE platform_resource
  ADD CONSTRAINT platform_resource_scope_type_check
  CHECK (scope_type IN ('global', 'environment', 'base', 'workshop'));

-- postgres-only
ALTER TABLE platform_resource
  ADD CONSTRAINT platform_resource_scope_shape_check
  CHECK (
    (scope_type = 'global' AND environment_id IS NULL
      AND base_id IS NULL AND workshop_id IS NULL)
    OR
    (scope_type = 'environment' AND environment_id IS NOT NULL
      AND base_id IS NULL AND workshop_id IS NULL)
    OR
    (scope_type = 'base' AND environment_id IS NOT NULL
      AND base_id IS NOT NULL AND workshop_id IS NULL)
    OR
    (scope_type = 'workshop' AND environment_id IS NOT NULL
      AND base_id IS NOT NULL AND workshop_id IS NOT NULL)
  );

CREATE TABLE IF NOT EXISTS loki_resource_draft_test_session (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES platform_resource(id),
  draft_id TEXT NOT NULL REFERENCES platform_resource_draft(id) ON DELETE CASCADE,
  draft_revision INTEGER NOT NULL CHECK (draft_revision >= 1),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  actor_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'EXPIRED')),
  expires_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(id, resource_id, draft_id, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_loki_draft_test_session_lookup
  ON loki_resource_draft_test_session(
    resource_id,
    actor_id,
    status,
    expires_at
  );

CREATE TABLE IF NOT EXISTS loki_scope_policy_health_observation (
  id TEXT PRIMARY KEY,
  policy_revision_id TEXT NOT NULL REFERENCES loki_scope_policy_revision(id),
  health_status TEXT NOT NULL
    CHECK (health_status IN ('HEALTHY', 'EMPTY', 'DEGRADED')),
  match_count INTEGER NOT NULL DEFAULT 0 CHECK (match_count >= 0),
  truncated INTEGER NOT NULL DEFAULT 0 CHECK (truncated IN (0, 1)),
  result_summary_json TEXT NOT NULL DEFAULT '{}',
  safe_error_summary TEXT NOT NULL DEFAULT '',
  observed_by TEXT NOT NULL DEFAULT '',
  observed_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_loki_scope_health_revision
  ON loki_scope_policy_health_observation(policy_revision_id, observed_at);
