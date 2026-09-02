-- Release an ONES subject after self-unbind while retaining the historical
-- identity row, scrubbed credential, and audit references. DingTalk and every
-- other provider retain their all-status historical uniqueness.
-- migration: sqlite-foreign-keys-off

-- SQLite cannot drop an inline UNIQUE constraint. Keep child foreign keys
-- pointed at the stable table name while rebuilding the parent table.
-- sqlite-only
PRAGMA legacy_alter_table = ON;

-- sqlite-only
ALTER TABLE user_external_identity
  RENAME TO user_external_identity_before_ones_release;

-- sqlite-only
CREATE TABLE user_external_identity (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_user(id),
  provider TEXT NOT NULL,
  tenant_code TEXT NOT NULL,
  external_subject_id TEXT NOT NULL,
  connector_id TEXT NOT NULL DEFAULT '',
  union_id TEXT NOT NULL DEFAULT '',
  open_id TEXT NOT NULL DEFAULT '',
  display_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  verified_at TEXT,
  last_seen_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  dingtalk_enterprise_id TEXT REFERENCES dingtalk_enterprise(id),
  display_name_observed_at TEXT,
  display_name_event_id TEXT NOT NULL DEFAULT '',
  display_name_source_connector_id TEXT NOT NULL DEFAULT ''
);

-- sqlite-only
INSERT INTO user_external_identity
  (id, user_id, provider, tenant_code, external_subject_id, connector_id,
   union_id, open_id, display_name, status, verified_at, last_seen_at,
   metadata_json, revision, created_at, updated_at, dingtalk_enterprise_id,
   display_name_observed_at, display_name_event_id,
   display_name_source_connector_id)
SELECT id, user_id, provider, tenant_code, external_subject_id, connector_id,
       union_id, open_id, display_name, status, verified_at, last_seen_at,
       metadata_json, revision, created_at, updated_at, dingtalk_enterprise_id,
       display_name_observed_at, display_name_event_id,
       display_name_source_connector_id
  FROM user_external_identity_before_ones_release;

-- sqlite-only
DROP TABLE user_external_identity_before_ones_release;

-- sqlite-only
PRAGMA legacy_alter_table = OFF;

-- sqlite-only
CREATE INDEX idx_external_identity_user
  ON user_external_identity(user_id);

-- sqlite-only
CREATE INDEX idx_external_identity_status
  ON user_external_identity(status);

-- PostgreSQL generated this name for the v100 inline UNIQUE constraint.
-- postgres-only
ALTER TABLE user_external_identity
  DROP CONSTRAINT user_external_identity_provider_tenant_code_external_subjec_key;

CREATE UNIQUE INDEX uq_external_identity_non_ones_subject
  ON user_external_identity(provider, tenant_code, external_subject_id)
  WHERE provider <> 'ones';

CREATE UNIQUE INDEX uq_external_identity_ones_current_subject
  ON user_external_identity(provider, tenant_code, external_subject_id)
  WHERE provider = 'ones' AND status IN ('enabled', 'disabled');
