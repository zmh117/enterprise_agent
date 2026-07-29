CREATE TABLE IF NOT EXISTS runtime_snapshot_generation (
  id TEXT PRIMARY KEY,
  generation_no INTEGER NOT NULL UNIQUE CHECK (generation_no >= 1),
  published_digest TEXT NOT NULL CHECK (length(published_digest) = 64),
  snapshot_digest TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL
    CHECK (status IN ('BUILDING', 'ACTIVE', 'FAILED', 'SUPERSEDED')),
  resource_count INTEGER NOT NULL DEFAULT 0 CHECK (resource_count >= 0),
  application_count INTEGER NOT NULL DEFAULT 0 CHECK (application_count >= 0),
  snapshot_json TEXT NOT NULL DEFAULT '{}',
  error_code TEXT NOT NULL DEFAULT '',
  error_summary TEXT NOT NULL DEFAULT '',
  built_at TEXT NOT NULL,
  activated_at TEXT,
  CHECK (status != 'ACTIVE' OR length(snapshot_digest) = 64)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_runtime_snapshot_generation_active
  ON runtime_snapshot_generation(status)
  WHERE status = 'ACTIVE';
CREATE INDEX IF NOT EXISTS idx_runtime_snapshot_generation_published
  ON runtime_snapshot_generation(published_digest, generation_no);

CREATE TABLE IF NOT EXISTS tool_resource_runtime_state (
  resource_revision_id TEXT NOT NULL
    REFERENCES platform_resource_revision(id),
  generation_id TEXT NOT NULL
    REFERENCES runtime_snapshot_generation(id),
  effective_revision_id TEXT
    REFERENCES platform_resource_revision(id),
  status TEXT NOT NULL
    CHECK (status IN ('READY', 'DEGRADED', 'BLOCKED', 'DISABLED')),
  resolved_secret_versions_json TEXT NOT NULL DEFAULT '{}',
  last_known_good_generation_id TEXT
    REFERENCES runtime_snapshot_generation(id),
  error_code TEXT NOT NULL DEFAULT '',
  error_summary TEXT NOT NULL DEFAULT '',
  checked_at TEXT NOT NULL,
  PRIMARY KEY(resource_revision_id, generation_id)
);

CREATE INDEX IF NOT EXISTS idx_resource_runtime_state_status
  ON tool_resource_runtime_state(generation_id, status);
CREATE INDEX IF NOT EXISTS idx_resource_runtime_state_effective
  ON tool_resource_runtime_state(effective_revision_id, generation_id);

CREATE TABLE IF NOT EXISTS business_application_runtime_state (
  application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  generation_id TEXT NOT NULL
    REFERENCES runtime_snapshot_generation(id),
  effective_application_publication_id TEXT
    REFERENCES business_application_publication(id),
  status TEXT NOT NULL
    CHECK (status IN ('READY', 'DEGRADED', 'BLOCKED')),
  last_known_good_generation_id TEXT
    REFERENCES runtime_snapshot_generation(id),
  reason_codes_json TEXT NOT NULL DEFAULT '[]',
  updated_at TEXT NOT NULL,
  PRIMARY KEY(application_publication_id, generation_id)
);

CREATE INDEX IF NOT EXISTS idx_application_runtime_state_status
  ON business_application_runtime_state(generation_id, status);
CREATE INDEX IF NOT EXISTS idx_application_runtime_state_effective
  ON business_application_runtime_state(
    effective_application_publication_id,
    generation_id
  );

CREATE TABLE IF NOT EXISTS resource_reset_operation (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL
    CHECK (
      status IN (
        'REPORTED',
        'PREPARING',
        'PREPARED',
        'CONFIRMED',
        'APPLYING',
        'APPLIED',
        'VERIFIED',
        'ABORTED',
        'FAILED'
      )
    ),
  target_kinds_json TEXT NOT NULL DEFAULT '[]',
  inventory_digest TEXT NOT NULL DEFAULT '',
  database_fingerprint TEXT NOT NULL DEFAULT '',
  backup_reference TEXT NOT NULL DEFAULT '',
  impact_summary_json TEXT NOT NULL DEFAULT '{}',
  prepared_by TEXT NOT NULL DEFAULT '',
  prepared_at TEXT,
  confirmed_by TEXT NOT NULL DEFAULT '',
  confirmed_at TEXT,
  applied_by TEXT NOT NULL DEFAULT '',
  applied_at TEXT,
  verified_by TEXT NOT NULL DEFAULT '',
  verified_at TEXT,
  correlation_id TEXT NOT NULL,
  error_code TEXT NOT NULL DEFAULT '',
  error_summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_resource_reset_status
  ON resource_reset_operation(status, created_at);
CREATE INDEX IF NOT EXISTS idx_resource_reset_correlation
  ON resource_reset_operation(correlation_id);

CREATE TABLE IF NOT EXISTS resource_reset_target (
  operation_id TEXT NOT NULL REFERENCES resource_reset_operation(id),
  target_type TEXT NOT NULL
    CHECK (
      target_type IN (
        'resource',
        'draft',
        'verification',
        'revision',
        'legacy_binding',
        'application_binding',
        'handler_resource_binding',
        'resource_runtime_state',
        'application_runtime_state',
        'activation'
      )
    ),
  target_id TEXT NOT NULL,
  target_revision INTEGER NOT NULL DEFAULT 0 CHECK (target_revision >= 0),
  target_code TEXT NOT NULL DEFAULT '',
  action TEXT NOT NULL CHECK (action IN ('DELETE', 'INVALIDATE', 'BLOCK')),
  item_digest TEXT NOT NULL CHECK (length(item_digest) = 64),
  apply_status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (apply_status IN ('PENDING', 'APPLIED', 'SKIPPED', 'FAILED')),
  error_code TEXT NOT NULL DEFAULT '',
  error_summary TEXT NOT NULL DEFAULT '',
  PRIMARY KEY(operation_id, target_type, target_id)
);

CREATE INDEX IF NOT EXISTS idx_resource_reset_target_status
  ON resource_reset_target(operation_id, apply_status, target_type);

COMMENT ON TABLE runtime_snapshot_generation IS
  'Published resource/application facts produce an immutable runtime generation';
COMMENT ON TABLE tool_resource_runtime_state IS
  'Per-generation Resource published/effective/LKG state without Secret values';
COMMENT ON TABLE business_application_runtime_state IS
  'Per-generation application READY/DEGRADED/BLOCKED projection';
COMMENT ON TABLE resource_reset_operation IS
  'Four-stage controlled DB/Redis/Loki reset operation and maintenance guard';
COMMENT ON TABLE resource_reset_target IS
  'Exact reset target inventory. Protected data categories are not valid targets';
