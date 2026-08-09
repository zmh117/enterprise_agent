CREATE TABLE IF NOT EXISTS provider_instance (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL CHECK (provider = 'ones'),
  display_name TEXT NOT NULL,
  base_url TEXT NOT NULL,
  allowed_hosts_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'DISABLED')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_provider_instance_status
  ON provider_instance(provider, status, code);

ALTER TABLE user_external_identity
  ADD COLUMN provider_instance_id TEXT REFERENCES provider_instance(id);

ALTER TABLE user_external_identity
  ADD COLUMN binding_revision INTEGER NOT NULL DEFAULT 1;

CREATE UNIQUE INDEX IF NOT EXISTS idx_ones_identity_instance_subject
  ON user_external_identity(provider_instance_id, external_subject_id)
  WHERE provider = 'ones' AND provider_instance_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_ones_identity_user_instance_current
  ON user_external_identity(user_id, provider_instance_id)
  WHERE provider = 'ones'
    AND provider_instance_id IS NOT NULL
    AND status IN ('enabled', 'disabled', 'REVERIFICATION_REQUIRED');

UPDATE user_external_identity
   SET status = 'REVERIFICATION_REQUIRED',
       revision = revision + 1,
       updated_at = CURRENT_TIMESTAMP
 WHERE provider = 'ones' AND status = 'enabled';

CREATE TABLE IF NOT EXISTS provider_credential (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_user(id),
  external_identity_id TEXT NOT NULL REFERENCES user_external_identity(id),
  provider_instance_id TEXT NOT NULL REFERENCES provider_instance(id),
  token_ciphertext TEXT NOT NULL,
  encryption_key_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'INVALID', 'DISABLED')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  last_error_code TEXT NOT NULL DEFAULT '',
  last_attempt_at TEXT,
  last_success_at TEXT,
  last_error_at TEXT,
  verified_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_credential_user_current
  ON provider_credential(user_id, provider_instance_id)
  WHERE status IN ('ACTIVE', 'INVALID');

CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_credential_identity_current
  ON provider_credential(external_identity_id, provider_instance_id)
  WHERE status IN ('ACTIVE', 'INVALID');

CREATE INDEX IF NOT EXISTS idx_provider_credential_instance_status
  ON provider_credential(provider_instance_id, status, user_id);

CREATE TABLE IF NOT EXISTS provider_verification_challenge (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_user(id),
  provider_instance_id TEXT NOT NULL REFERENCES provider_instance(id),
  external_user_id TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  teams_json TEXT NOT NULL,
  token_ciphertext TEXT NOT NULL,
  encryption_key_id TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'CONSUMED', 'EXPIRED')),
  created_at TEXT NOT NULL,
  consumed_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_provider_challenge_pending
  ON provider_verification_challenge(user_id, provider_instance_id)
  WHERE status = 'PENDING';

CREATE INDEX IF NOT EXISTS idx_provider_challenge_expiry
  ON provider_verification_challenge(status, expires_at);

CREATE TABLE IF NOT EXISTS dingtalk_identity_binding_challenge (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_user(id),
  code_hash TEXT NOT NULL UNIQUE CHECK (length(code_hash) = 64),
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'CONSUMED', 'EXPIRED', 'CANCELLED')),
  consumed_external_identity_id TEXT REFERENCES user_external_identity(id),
  trusted_connector_id TEXT NOT NULL DEFAULT '',
  trusted_event_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  consumed_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_dingtalk_binding_challenge_pending
  ON dingtalk_identity_binding_challenge(user_id)
  WHERE status = 'PENDING';

CREATE UNIQUE INDEX IF NOT EXISTS idx_dingtalk_binding_trusted_event
  ON dingtalk_identity_binding_challenge(trusted_connector_id, trusted_event_id)
  WHERE status = 'CONSUMED';

CREATE INDEX IF NOT EXISTS idx_dingtalk_binding_challenge_expiry
  ON dingtalk_identity_binding_challenge(status, expires_at);

COMMENT ON TABLE provider_instance IS
  'Deployment-trusted ONES endpoint definition without authentication material';
COMMENT ON TABLE provider_credential IS
  'Encrypted personal ONES token tied to one internal user, exact identity, and provider instance';
COMMENT ON TABLE provider_verification_challenge IS
  'Short-lived encrypted ONES login result where the password is never persisted';
COMMENT ON TABLE dingtalk_identity_binding_challenge IS
  'Single-use self-binding code consumed only by a trusted DingTalk event';
