-- Allow a channel attachment to be imported into its active task workspace
-- before a later text message claims it for exactly one Agent Job.
-- migration: sqlite-foreign-keys-off

ALTER TABLE message_attachment
  ADD COLUMN task_workspace_id TEXT REFERENCES task_workspace(id);

ALTER TABLE message_attachment
  ADD COLUMN claimed_at TEXT;

UPDATE message_attachment
   SET task_workspace_id = (
     SELECT j.task_workspace_id
       FROM agent_job j
      WHERE j.id = message_attachment.job_id
   )
 WHERE task_workspace_id IS NULL;

-- SQLite cannot remove NOT NULL from message_attachment.job_id in place.
-- Rebuild the table while preserving every attachment and the 107 lifecycle
-- columns. Child foreign keys remain valid because migration execution has
-- foreign-key enforcement disabled for this transaction.
-- sqlite-only
CREATE TABLE message_attachment_stage_new (
  id TEXT PRIMARY KEY,
  message_id TEXT NOT NULL REFERENCES agent_message(id),
  job_id TEXT REFERENCES agent_job(id),
  ordinal INTEGER NOT NULL,
  media_type TEXT NOT NULL,
  file_name TEXT NOT NULL,
  declared_mime TEXT NOT NULL DEFAULT '',
  detected_mime TEXT NOT NULL DEFAULT '',
  declared_size INTEGER,
  size_bytes INTEGER,
  sha256 TEXT NOT NULL DEFAULT '',
  object_bucket TEXT NOT NULL DEFAULT '',
  object_key TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'PENDING',
  failure_code TEXT NOT NULL DEFAULT '',
  retry_count INTEGER NOT NULL DEFAULT 0,
  source_credential_ciphertext TEXT NOT NULL DEFAULT '',
  source_credential_type TEXT NOT NULL DEFAULT '',
  source_credential_expires_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  finished_at TEXT,
  expires_at TEXT,
  retention_days INTEGER NOT NULL DEFAULT 360 CHECK (retention_days > 0),
  managed_file_id TEXT,
  managed_file_version_id TEXT,
  content_deleted_at TEXT,
  task_workspace_id TEXT REFERENCES task_workspace(id),
  claimed_at TEXT,
  UNIQUE(message_id, ordinal)
);

-- sqlite-only
INSERT INTO message_attachment_stage_new (
  id, message_id, job_id, ordinal, media_type, file_name, declared_mime,
  detected_mime, declared_size, size_bytes, sha256, object_bucket, object_key,
  status, failure_code, retry_count, source_credential_ciphertext,
  source_credential_type, source_credential_expires_at, created_at, updated_at,
  finished_at, expires_at, retention_days, managed_file_id,
  managed_file_version_id, content_deleted_at, task_workspace_id, claimed_at
)
SELECT
  id, message_id, job_id, ordinal, media_type, file_name, declared_mime,
  detected_mime, declared_size, size_bytes, sha256, object_bucket, object_key,
  status, failure_code, retry_count, source_credential_ciphertext,
  source_credential_type, source_credential_expires_at, created_at, updated_at,
  finished_at, expires_at, retention_days, managed_file_id,
  managed_file_version_id, content_deleted_at, task_workspace_id, claimed_at
FROM message_attachment;

-- sqlite-only
DROP TABLE message_attachment;

-- sqlite-only
ALTER TABLE message_attachment_stage_new RENAME TO message_attachment;

-- postgres-only
ALTER TABLE message_attachment ALTER COLUMN job_id DROP NOT NULL;

-- sqlite-only
CREATE INDEX idx_message_attachment_job ON message_attachment(job_id);
-- sqlite-only
CREATE INDEX idx_message_attachment_status ON message_attachment(status);
-- sqlite-only
CREATE INDEX idx_message_attachment_created
  ON message_attachment(created_at, id);
-- sqlite-only
CREATE INDEX idx_message_attachment_retention_due
  ON message_attachment(status, expires_at, id);
-- sqlite-only
CREATE INDEX idx_message_attachment_managed_version
  ON message_attachment(managed_file_version_id);
CREATE INDEX idx_message_attachment_workspace_unclaimed
  ON message_attachment(task_workspace_id, created_at, id)
  WHERE job_id IS NULL;

-- A staged event is a successful terminal ingress outcome without an Agent Job.
-- sqlite-only
CREATE TABLE channel_ingress_event_stage_new (
    id text primary key,
    source_type text not null,
    connector_id text not null references integration_connector(id),
    external_event_id text not null,
    correlation_id text not null,
    payload_hash text not null,
    safe_summary_json text not null default '{}',
    normalized_event_json text not null default '{}',
    reply_credential_ciphertext text not null default '',
    status text not null default 'ACCEPTED'
        check (status in (
            'ACCEPTED', 'DISPATCH_PENDING', 'DISPATCHING',
            'JOB_CREATED', 'ATTACHMENTS_STAGED', 'REJECTED', 'DISPATCH_FAILED'
        )),
    job_id text references agent_job(id),
    error_code text not null default '',
    error_summary text not null default '',
    request_bytes integer not null default 0,
    received_at text not null,
    dispatched_at text,
    completed_at text,
    unique (connector_id, external_event_id)
);

-- sqlite-only
INSERT INTO channel_ingress_event_stage_new (
  id, source_type, connector_id, external_event_id, correlation_id,
  payload_hash, safe_summary_json, normalized_event_json,
  reply_credential_ciphertext, status, job_id, error_code, error_summary,
  request_bytes, received_at, dispatched_at, completed_at
)
SELECT
  id, source_type, connector_id, external_event_id, correlation_id,
  payload_hash, safe_summary_json, normalized_event_json,
  reply_credential_ciphertext, status, job_id, error_code, error_summary,
  request_bytes, received_at, dispatched_at, completed_at
FROM channel_ingress_event;

-- sqlite-only
DROP TABLE channel_ingress_event;

-- sqlite-only
ALTER TABLE channel_ingress_event_stage_new RENAME TO channel_ingress_event;

-- postgres-only
ALTER TABLE channel_ingress_event
  DROP CONSTRAINT channel_ingress_event_status_check;

-- postgres-only
ALTER TABLE channel_ingress_event
  ADD CONSTRAINT channel_ingress_event_status_check
  CHECK (status IN (
    'ACCEPTED', 'DISPATCH_PENDING', 'DISPATCHING',
    'JOB_CREATED', 'ATTACHMENTS_STAGED', 'REJECTED', 'DISPATCH_FAILED'
  ));

-- sqlite-only
CREATE INDEX idx_channel_ingress_event_status_received
  ON channel_ingress_event(status, received_at);

-- postgres-only
COMMENT ON COLUMN message_attachment.task_workspace_id IS
  '纯附件消息在 Agent Job 认领前归属的任务文件工作区标识';

-- postgres-only
COMMENT ON COLUMN message_attachment.claimed_at IS
  '后续文字触发的 Agent Job 原子认领附件的时间';
