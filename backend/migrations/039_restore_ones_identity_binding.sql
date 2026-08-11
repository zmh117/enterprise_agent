-- Restore ONES identity self-service after migration 038 removed the legacy
-- API Capability credential challenge. This table stores identity facts only:
-- never email, password, login token, API Connection, Capability, or MCP data.

CREATE TABLE IF NOT EXISTS ones_identity_verification_challenge (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_user(id),
  external_user_id TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  teams_json TEXT NOT NULL DEFAULT '[]',
  verified_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'CONSUMED', 'EXPIRED')),
  created_at TEXT NOT NULL,
  consumed_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ones_identity_challenge_pending
  ON ones_identity_verification_challenge(user_id)
  WHERE status = 'PENDING';

CREATE INDEX IF NOT EXISTS idx_ones_identity_challenge_expiry
  ON ones_identity_verification_challenge(status, expires_at);
