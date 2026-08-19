-- Per-message file admission: blocked-turn facts, quote target, and
-- session-level SYSTEM_NOTICE delivery without an Agent Job.
-- migration: sqlite-foreign-keys-off

ALTER TABLE agent_message
  ADD COLUMN quoted_external_message_id TEXT NOT NULL DEFAULT '';

CREATE INDEX idx_agent_message_quoted
  ON agent_message(session_id, quoted_external_message_id)
  WHERE quoted_external_message_id <> '';

CREATE TABLE file_readiness_blocked_turn (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES agent_session(id),
  workspace_id TEXT NOT NULL REFERENCES task_workspace(id),
  user_message_id TEXT NOT NULL REFERENCES agent_message(id),
  reason_code TEXT NOT NULL
    CHECK (reason_code IN (
      'file_readable_content_not_ready',
      'file_processing_failed',
      'file_binding_ambiguous'
    )),
  status TEXT NOT NULL
    CHECK (status IN ('OPEN', 'NOTIFIED', 'EXPIRED')),
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  notified_at TEXT
);

CREATE TABLE file_readiness_blocked_turn_version (
  turn_id TEXT NOT NULL REFERENCES file_readiness_blocked_turn(id) ON DELETE CASCADE,
  file_version_id TEXT NOT NULL,
  PRIMARY KEY (turn_id, file_version_id)
);

CREATE INDEX idx_file_readiness_blocked_turn_open
  ON file_readiness_blocked_turn(status, expires_at, id);

CREATE INDEX idx_file_readiness_blocked_turn_session
  ON file_readiness_blocked_turn(session_id, created_at, id);

CREATE INDEX idx_file_readiness_blocked_turn_version
  ON file_readiness_blocked_turn_version(file_version_id, turn_id);

-- SQLite cannot drop NOT NULL or widen an inline CHECK in place.
-- sqlite-only
CREATE TABLE delivery_outbox_system_notice (
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
  UNIQUE(job_id, result_artifact_id),
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
INSERT INTO delivery_outbox_system_notice (
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
ALTER TABLE delivery_outbox_system_notice RENAME TO delivery_outbox;

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

-- sqlite-only
CREATE TABLE delivery_attempt_system_notice (
  id TEXT PRIMARY KEY,
  job_id TEXT REFERENCES agent_job(id),
  route_type TEXT NOT NULL,
  connector_id TEXT NOT NULL DEFAULT '',
  target_summary TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL,
  error_message TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT,
  delivery_outbox_id TEXT REFERENCES delivery_outbox(id),
  replay_no INTEGER NOT NULL DEFAULT 0 CHECK (replay_no >= 0),
  attempt_no INTEGER NOT NULL DEFAULT 0 CHECK (attempt_no >= 0),
  correlation_id TEXT NOT NULL DEFAULT '',
  idempotency_key TEXT NOT NULL DEFAULT '',
  error_code TEXT NOT NULL DEFAULT '',
  file_id TEXT NOT NULL DEFAULT '',
  file_version_id TEXT NOT NULL DEFAULT ''
);

-- sqlite-only
INSERT INTO delivery_attempt_system_notice (
  id, job_id, route_type, connector_id, target_summary, status, error_message,
  created_at, finished_at, delivery_outbox_id, replay_no, attempt_no,
  correlation_id, idempotency_key, error_code, file_id, file_version_id
)
SELECT
  id, job_id, route_type, connector_id, target_summary, status, error_message,
  created_at, finished_at, delivery_outbox_id, replay_no, attempt_no,
  correlation_id, idempotency_key, error_code, file_id, file_version_id
FROM delivery_attempt;

-- sqlite-only
DROP TABLE delivery_attempt;

-- sqlite-only
ALTER TABLE delivery_attempt_system_notice RENAME TO delivery_attempt;

-- sqlite-only
CREATE INDEX idx_delivery_attempt_job ON delivery_attempt(job_id);

-- sqlite-only
CREATE INDEX idx_delivery_attempt_status ON delivery_attempt(status);

-- sqlite-only
CREATE INDEX idx_delivery_attempt_created_status
  ON delivery_attempt(created_at, status);

-- sqlite-only
CREATE UNIQUE INDEX uq_delivery_attempt_idempotency
  ON delivery_attempt(idempotency_key);

-- sqlite-only
CREATE UNIQUE INDEX uq_delivery_attempt_outbox_number
  ON delivery_attempt(delivery_outbox_id, replay_no, attempt_no)
  WHERE delivery_outbox_id IS NOT NULL;

-- sqlite-only
CREATE INDEX idx_delivery_attempt_outbox
  ON delivery_attempt(delivery_outbox_id, replay_no, attempt_no);

-- postgres-only
ALTER TABLE delivery_outbox
  ALTER COLUMN job_id DROP NOT NULL;

-- postgres-only
ALTER TABLE delivery_outbox
  ALTER COLUMN result_artifact_id DROP NOT NULL;

-- postgres-only
ALTER TABLE delivery_attempt
  ALTER COLUMN job_id DROP NOT NULL;

-- postgres-only
ALTER TABLE delivery_outbox
  DROP CONSTRAINT delivery_outbox_delivery_kind_check;

-- postgres-only
ALTER TABLE delivery_outbox
  ADD CONSTRAINT delivery_outbox_delivery_kind_check
  CHECK (delivery_kind IN ('RESULT', 'FAILURE', 'FILE_VERSION', 'SYSTEM_NOTICE'));

-- postgres-only
ALTER TABLE delivery_outbox
  ADD CONSTRAINT delivery_outbox_system_notice_shape_check
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
  );

-- postgres-only
CREATE INDEX idx_delivery_outbox_session_notice
  ON delivery_outbox(session_id, created_at)
  WHERE delivery_kind = 'SYSTEM_NOTICE';

-- postgres-only
COMMENT ON COLUMN agent_message.quoted_external_message_id IS
  '当前消息引用的外部消息ID，供本轮文件绑定反查附件';

-- postgres-only
COMMENT ON COLUMN delivery_outbox.delivery_kind IS
  '结果、失败通知、精确文件版本交付或会话级系统说明类型';


-- postgres-only
COMMENT ON TABLE file_readiness_blocked_turn IS
  '因可读内容未就绪或绑定歧义而结束的轮次，供就绪通知使用且不含正文';

-- postgres-only
COMMENT ON COLUMN file_readiness_blocked_turn.id IS '被挡轮次稳定标识';
-- postgres-only
COMMENT ON COLUMN file_readiness_blocked_turn.session_id IS '被挡轮次所属渠道会话';
-- postgres-only
COMMENT ON COLUMN file_readiness_blocked_turn.workspace_id IS '被挡轮次所属任务工作区';
-- postgres-only
COMMENT ON COLUMN file_readiness_blocked_turn.user_message_id IS '触发门禁的用户消息';
-- postgres-only
COMMENT ON COLUMN file_readiness_blocked_turn.reason_code IS '未就绪、处理失败或绑定歧义原因码';
-- postgres-only
COMMENT ON COLUMN file_readiness_blocked_turn.status IS '待通知、已通知或已过期';
-- postgres-only
COMMENT ON COLUMN file_readiness_blocked_turn.created_at IS '被挡事实创建时间';
-- postgres-only
COMMENT ON COLUMN file_readiness_blocked_turn.expires_at IS '就绪通知截止时间';
-- postgres-only
COMMENT ON COLUMN file_readiness_blocked_turn.notified_at IS '就绪通知实际发送时间';

-- postgres-only
COMMENT ON TABLE file_readiness_blocked_turn_version IS
  '被挡轮次依赖的精确文件版本，用于表示就绪后匹配通知';

-- postgres-only
COMMENT ON COLUMN file_readiness_blocked_turn_version.turn_id IS '被挡轮次标识';
-- postgres-only
COMMENT ON COLUMN file_readiness_blocked_turn_version.file_version_id IS
  '本轮依赖的精确文件版本';
