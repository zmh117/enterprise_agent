-- migration: sqlite-foreign-keys-off
-- Resource reset inventory follows exact Built-in Tool Application mappings.
-- Historical target values remain accepted for old reset ledgers.

-- sqlite-only
PRAGMA legacy_alter_table = ON;

-- sqlite-only
ALTER TABLE resource_reset_target
  RENAME TO resource_reset_target_pre_exact_builtin_tools;

-- sqlite-only
CREATE TABLE resource_reset_target (
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
        'builtin_tool_resource_mapping',
        'builtin_tool_draft_resource_mapping',
        'builtin_tool_resolution',
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

-- sqlite-only
INSERT INTO resource_reset_target
  (operation_id, target_type, target_id, target_revision, target_code,
   action, item_digest, apply_status, error_code, error_summary)
SELECT operation_id, target_type, target_id, target_revision, target_code,
       action, item_digest, apply_status, error_code, error_summary
  FROM resource_reset_target_pre_exact_builtin_tools;

-- sqlite-only
DROP TABLE resource_reset_target_pre_exact_builtin_tools;

-- sqlite-only
CREATE INDEX idx_resource_reset_target_status
  ON resource_reset_target(operation_id, apply_status, target_type);

-- sqlite-only
PRAGMA legacy_alter_table = OFF;

-- postgres-only
ALTER TABLE resource_reset_target
  DROP CONSTRAINT resource_reset_target_target_type_check;

-- postgres-only
ALTER TABLE resource_reset_target
  ADD CONSTRAINT resource_reset_target_target_type_check
  CHECK (
    target_type IN (
      'resource',
      'draft',
      'verification',
      'revision',
      'legacy_binding',
      'application_binding',
      'handler_resource_binding',
      'builtin_tool_resource_mapping',
      'builtin_tool_draft_resource_mapping',
      'builtin_tool_resolution',
      'resource_runtime_state',
      'application_runtime_state',
      'activation'
    )
  );
