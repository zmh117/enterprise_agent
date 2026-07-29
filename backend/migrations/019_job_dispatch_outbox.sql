CREATE TABLE IF NOT EXISTS job_dispatch_outbox (
  id TEXT PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE,
  idempotency_key TEXT NOT NULL UNIQUE,
  job_id TEXT NOT NULL UNIQUE REFERENCES agent_job(id),
  correlation_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'RUNNING', 'RETRY_WAIT', 'PUBLISHED', 'DEAD')),
  attempt_count INTEGER NOT NULL DEFAULT 0
    CHECK (attempt_count >= 0),
  max_attempts INTEGER NOT NULL DEFAULT 8
    CHECK (max_attempts > 0),
  replay_count INTEGER NOT NULL DEFAULT 0
    CHECK (replay_count >= 0),
  max_replay_count INTEGER NOT NULL DEFAULT 3
    CHECK (max_replay_count >= 0),
  next_attempt_at TEXT NOT NULL,
  claimed_by TEXT NOT NULL DEFAULT '',
  claimed_at TEXT,
  published_at TEXT,
  dead_at TEXT,
  last_replayed_at TEXT,
  last_replayed_by TEXT NOT NULL DEFAULT '',
  last_error_code TEXT NOT NULL DEFAULT '',
  last_error_summary TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (attempt_count <= max_attempts),
  CHECK (replay_count <= max_replay_count)
);

CREATE INDEX IF NOT EXISTS idx_job_dispatch_outbox_due
  ON job_dispatch_outbox(status, next_attempt_at, created_at);

CREATE INDEX IF NOT EXISTS idx_job_dispatch_outbox_claim
  ON job_dispatch_outbox(status, claimed_at)
  WHERE status = 'RUNNING';

CREATE INDEX IF NOT EXISTS idx_job_dispatch_outbox_job_status
  ON job_dispatch_outbox(job_id, status);

CREATE INDEX IF NOT EXISTS idx_job_dispatch_outbox_audit
  ON job_dispatch_outbox(correlation_id, created_at);

COMMENT ON TABLE job_dispatch_outbox IS
  'Agent Job提交后到RabbitMQ发布之间的事务Outbox，不保存可变执行payload';
COMMENT ON COLUMN job_dispatch_outbox.event_key IS
  '稳定且唯一的dispatch事件键，用于发布和消费幂等';
COMMENT ON COLUMN job_dispatch_outbox.idempotency_key IS
  '由Job创建事实派生的稳定幂等键，不接受调用方任意payload';
COMMENT ON COLUMN job_dispatch_outbox.last_error_summary IS
  '有界脱敏发布错误摘要，不包含payload、Token、Secret或连接信息';

CREATE TABLE IF NOT EXISTS job_dispatch_cutover_quarantine (
  id TEXT PRIMARY KEY,
  source_queue TEXT NOT NULL,
  message_digest TEXT NOT NULL,
  job_id TEXT,
  reason_code TEXT NOT NULL,
  observed_at TEXT NOT NULL,
  observed_by TEXT NOT NULL,
  UNIQUE (source_queue, message_digest)
);

CREATE INDEX IF NOT EXISTS idx_job_dispatch_cutover_quarantine_job
  ON job_dispatch_cutover_quarantine(job_id, observed_at);

COMMENT ON TABLE job_dispatch_cutover_quarantine IS
  '旧Agent消息切换时无法安全转换的摘要清单，不保存原始RabbitMQ payload';
