-- Per-recipient result delivery, preserving existing events and references.
-- migration: sqlite-foreign-keys-off

-- sqlite-only
CREATE TABLE delivery_outbox_recipients (
  id TEXT PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE,
  job_id TEXT REFERENCES agent_job(id),
  result_artifact_id TEXT REFERENCES agent_artifact(id),
  application_publication_id TEXT NOT NULL DEFAULT '',
  delivery_binding_json TEXT NOT NULL,
  target_summary TEXT NOT NULL DEFAULT '{}',
  correlation_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (
    status IN (
      'PENDING',
      'RUNNING',
      'RETRY_WAIT',
      'SUCCEEDED',
      'FAILED',
      'DEAD',
      'SKIPPED'
    )
  ),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  max_attempts INTEGER NOT NULL CHECK (max_attempts > 0),
  replay_count INTEGER NOT NULL DEFAULT 0 CHECK (replay_count >= 0),
  max_replay_count INTEGER NOT NULL DEFAULT 0 CHECK (max_replay_count >= 0),
  next_attempt_at TEXT NOT NULL,
  claimed_by TEXT NOT NULL DEFAULT '',
  claim_token TEXT NOT NULL DEFAULT '',
  claimed_at TEXT,
  claim_expires_at TEXT,
  last_error_code TEXT NOT NULL DEFAULT '',
  last_error_summary TEXT NOT NULL DEFAULT '',
  started_at TEXT,
  finished_at TEXT,
  dead_at TEXT,
  last_replayed_at TEXT,
  last_replayed_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  delivery_kind TEXT NOT NULL DEFAULT 'RESULT'
    CHECK (delivery_kind IN ('RESULT', 'FAILURE', 'FILE_VERSION', 'SYSTEM_NOTICE')),
  file_id TEXT NOT NULL DEFAULT '',
  file_version_id TEXT NOT NULL DEFAULT '',
  file_content_sha256 TEXT NOT NULL DEFAULT '',
  principal_user_id TEXT NOT NULL DEFAULT '',
  session_id TEXT NOT NULL DEFAULT '',
  agent_publication_id TEXT NOT NULL DEFAULT '',
  recipient_key TEXT NOT NULL DEFAULT '',
  UNIQUE(job_id, result_artifact_id, recipient_key),
  CHECK (
    (
      delivery_kind = 'SYSTEM_NOTICE'
      AND job_id IS NULL
      AND result_artifact_id IS NULL
      AND session_id <> ''
    )
    OR
    (
      delivery_kind <> 'SYSTEM_NOTICE'
      AND job_id IS NOT NULL
      AND result_artifact_id IS NOT NULL
    )
  )
);

-- sqlite-only
INSERT INTO delivery_outbox_recipients (
  id, event_key, job_id, result_artifact_id, application_publication_id,
  delivery_binding_json, target_summary, correlation_id, status, attempt_count,
  max_attempts, replay_count, max_replay_count, next_attempt_at, claimed_by,
  claim_token, claimed_at, claim_expires_at, last_error_code, last_error_summary,
  started_at, finished_at, dead_at, last_replayed_at, last_replayed_by,
  created_at, updated_at, delivery_kind, file_id, file_version_id,
  file_content_sha256, principal_user_id, session_id, agent_publication_id
)
SELECT
  id, event_key, job_id, result_artifact_id, application_publication_id,
  delivery_binding_json, target_summary, correlation_id, status, attempt_count,
  max_attempts, replay_count, max_replay_count, next_attempt_at, claimed_by,
  claim_token, claimed_at, claim_expires_at, last_error_code, last_error_summary,
  started_at, finished_at, dead_at, last_replayed_at, last_replayed_by,
  created_at, updated_at, delivery_kind, file_id, file_version_id,
  file_content_sha256, principal_user_id, session_id, agent_publication_id
FROM delivery_outbox;

-- sqlite-only
DROP TABLE delivery_outbox;

-- sqlite-only
ALTER TABLE delivery_outbox_recipients RENAME TO delivery_outbox;

-- sqlite-only
CREATE INDEX idx_delivery_outbox_claim
  ON delivery_outbox(status, next_attempt_at, created_at);

-- sqlite-only
CREATE INDEX idx_delivery_outbox_job
  ON delivery_outbox(job_id, created_at);

-- sqlite-only
CREATE INDEX idx_delivery_outbox_correlation
  ON delivery_outbox(correlation_id, created_at);

-- sqlite-only
CREATE INDEX idx_delivery_outbox_stale_claim
  ON delivery_outbox(status, claim_expires_at);

-- sqlite-only
CREATE UNIQUE INDEX uq_delivery_outbox_file_version
  ON delivery_outbox(job_id, file_version_id)
  WHERE file_version_id <> '';

-- sqlite-only
CREATE INDEX idx_delivery_outbox_session_notice
  ON delivery_outbox(session_id, created_at)
  WHERE delivery_kind = 'SYSTEM_NOTICE';

-- postgres-only
ALTER TABLE delivery_outbox ADD COLUMN recipient_key TEXT NOT NULL DEFAULT '';

-- postgres-only
ALTER TABLE delivery_outbox DROP CONSTRAINT delivery_outbox_job_id_result_artifact_id_key;

-- postgres-only
ALTER TABLE delivery_outbox ADD CONSTRAINT delivery_outbox_result_recipient_key
  UNIQUE(job_id, result_artifact_id, recipient_key);

-- postgres-only
COMMENT ON COLUMN delivery_outbox.recipient_key IS '冻结结果接收人的稳定标识；单目标为空';
