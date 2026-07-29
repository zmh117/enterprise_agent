CREATE TABLE IF NOT EXISTS legacy_authorization_cleanup_operation (
  id TEXT PRIMARY KEY,
  status TEXT NOT NULL
    CHECK (status IN ('PREPARED', 'APPLYING', 'APPLIED', 'VERIFIED')),
  inventory_digest TEXT NOT NULL CHECK (length(inventory_digest) = 64),
  backup_reference TEXT NOT NULL,
  manifest_json TEXT NOT NULL,
  prepared_by TEXT NOT NULL,
  prepared_at TEXT NOT NULL,
  confirmed_by TEXT NOT NULL DEFAULT '',
  confirmed_at TEXT,
  applied_by TEXT NOT NULL DEFAULT '',
  applied_at TEXT,
  verified_by TEXT NOT NULL DEFAULT '',
  verified_at TEXT,
  correlation_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_legacy_authorization_cleanup_status
  ON legacy_authorization_cleanup_operation(status, created_at);

COMMENT ON TABLE legacy_authorization_cleanup_operation IS
  'Exact digest and confirmation ledger for one-time legacy authorization cleanup';

DELETE FROM platform_runtime_config_value
 WHERE key IN (
   'PERMISSION_SHADOW_MODE',
   'FEATURE_PERMISSION_SHADOW_MODE'
 )
    OR definition_id IN (
      SELECT id
        FROM platform_runtime_config_definition
       WHERE key IN (
         'PERMISSION_SHADOW_MODE',
         'FEATURE_PERMISSION_SHADOW_MODE'
       )
    );

DELETE FROM platform_runtime_config_definition
 WHERE key IN (
   'PERMISSION_SHADOW_MODE',
   'FEATURE_PERMISSION_SHADOW_MODE'
 );
