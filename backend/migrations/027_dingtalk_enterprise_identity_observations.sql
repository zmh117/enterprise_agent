CREATE TABLE IF NOT EXISTS dingtalk_enterprise (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL CHECK (length(trim(name)) BETWEEN 1 AND 120),
  corp_id TEXT,
  status TEXT NOT NULL DEFAULT 'PENDING_VERIFICATION'
    CHECK (status IN (
      'PENDING_VERIFICATION', 'ACTIVE', 'DISABLED', 'ARCHIVED'
    )),
  verification_event_id TEXT NOT NULL DEFAULT '',
  verified_at TEXT,
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL REFERENCES app_user(id),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (corp_id IS NULL OR length(trim(corp_id)) BETWEEN 1 AND 128),
  CHECK (status <> 'ACTIVE' OR (corp_id IS NOT NULL AND verified_at IS NOT NULL))
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_dingtalk_enterprise_corp_id
  ON dingtalk_enterprise(corp_id)
  WHERE corp_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_dingtalk_enterprise_status_name
  ON dingtalk_enterprise(status, name, id);

ALTER TABLE integration_connector
  ADD COLUMN dingtalk_enterprise_id TEXT REFERENCES dingtalk_enterprise(id);

CREATE INDEX IF NOT EXISTS idx_integration_connector_dingtalk_enterprise
  ON integration_connector(dingtalk_enterprise_id, enabled, deleted);

ALTER TABLE user_external_identity
  ADD COLUMN dingtalk_enterprise_id TEXT REFERENCES dingtalk_enterprise(id);

ALTER TABLE user_external_identity
  ADD COLUMN display_name_observed_at TEXT;

ALTER TABLE user_external_identity
  ADD COLUMN display_name_event_id TEXT NOT NULL DEFAULT '';

ALTER TABLE user_external_identity
  ADD COLUMN display_name_source_connector_id TEXT NOT NULL DEFAULT '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_dingtalk_identity_enterprise_subject
  ON user_external_identity(dingtalk_enterprise_id, external_subject_id)
  WHERE provider = 'dingtalk' AND dingtalk_enterprise_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_dingtalk_identity_user_enterprise_current
  ON user_external_identity(user_id, dingtalk_enterprise_id)
  WHERE provider = 'dingtalk'
    AND dingtalk_enterprise_id IS NOT NULL
    AND status IN ('enabled', 'disabled');

CREATE TABLE IF NOT EXISTS dingtalk_identity_application_observation (
  id TEXT PRIMARY KEY,
  external_identity_id TEXT NOT NULL REFERENCES user_external_identity(id),
  connector_id TEXT NOT NULL REFERENCES integration_connector(id),
  first_observed_at TEXT NOT NULL,
  last_observed_at TEXT NOT NULL,
  last_ingress_event_id TEXT NOT NULL REFERENCES channel_ingress_event(id),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(external_identity_id, connector_id)
);

CREATE INDEX IF NOT EXISTS idx_dingtalk_identity_application_observation_recent
  ON dingtalk_identity_application_observation(
    external_identity_id, last_observed_at DESC, connector_id
  );

CREATE TABLE IF NOT EXISTS dingtalk_identity_nickname_audit (
  id TEXT PRIMARY KEY,
  external_identity_id TEXT NOT NULL REFERENCES user_external_identity(id),
  connector_id TEXT NOT NULL REFERENCES integration_connector(id),
  source_ingress_event_id TEXT NOT NULL UNIQUE REFERENCES channel_ingress_event(id),
  previous_nickname TEXT NOT NULL DEFAULT '',
  current_nickname TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_dingtalk_identity_nickname_audit_history
  ON dingtalk_identity_nickname_audit(
    external_identity_id, observed_at DESC, source_ingress_event_id DESC
  );

ALTER TABLE dingtalk_identity_candidate
  ADD COLUMN dingtalk_enterprise_id TEXT REFERENCES dingtalk_enterprise(id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_dingtalk_candidate_enterprise_subject
  ON dingtalk_identity_candidate(dingtalk_enterprise_id, external_subject_id)
  WHERE dingtalk_enterprise_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_dingtalk_candidate_enterprise_recent
  ON dingtalk_identity_candidate(
    dingtalk_enterprise_id, last_seen_at DESC, id DESC
  );

ALTER TABLE external_api_credential
  ADD COLUMN last_attempt_at TEXT;

ALTER TABLE external_api_credential
  ADD COLUMN last_success_at TEXT;

ALTER TABLE external_api_credential
  ADD COLUMN last_error_at TEXT;

COMMENT ON TABLE dingtalk_enterprise IS
  'Real DingTalk Corp ID namespace governed independently from app runtime state';
COMMENT ON TABLE dingtalk_identity_application_observation IS
  'Identity-to-app observations where identity ownership is enterprise scoped';
COMMENT ON TABLE dingtalk_identity_nickname_audit IS
  'Minimal nickname-change facts without message bodies or authentication material';
