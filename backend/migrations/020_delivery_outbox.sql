CREATE TABLE IF NOT EXISTS delivery_outbox (
  id TEXT PRIMARY KEY,
  event_key TEXT NOT NULL UNIQUE,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  result_artifact_id TEXT NOT NULL REFERENCES agent_artifact(id),
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
  UNIQUE(job_id, result_artifact_id)
);

CREATE INDEX IF NOT EXISTS idx_delivery_outbox_claim
  ON delivery_outbox(status, next_attempt_at, created_at);
CREATE INDEX IF NOT EXISTS idx_delivery_outbox_job
  ON delivery_outbox(job_id, created_at);
CREATE INDEX IF NOT EXISTS idx_delivery_outbox_correlation
  ON delivery_outbox(correlation_id, created_at);
CREATE INDEX IF NOT EXISTS idx_delivery_outbox_stale_claim
  ON delivery_outbox(status, claim_expires_at);

ALTER TABLE delivery_attempt
  ADD COLUMN delivery_outbox_id TEXT REFERENCES delivery_outbox(id);
ALTER TABLE delivery_attempt
  ADD COLUMN replay_no INTEGER NOT NULL DEFAULT 0 CHECK (replay_no >= 0);
ALTER TABLE delivery_attempt
  ADD COLUMN attempt_no INTEGER NOT NULL DEFAULT 0 CHECK (attempt_no >= 0);
ALTER TABLE delivery_attempt
  ADD COLUMN correlation_id TEXT NOT NULL DEFAULT '';
ALTER TABLE delivery_attempt
  ADD COLUMN idempotency_key TEXT NOT NULL DEFAULT '';
ALTER TABLE delivery_attempt
  ADD COLUMN error_code TEXT NOT NULL DEFAULT '';

UPDATE delivery_attempt
   SET idempotency_key = 'legacy-delivery-attempt:' || id
 WHERE idempotency_key = '';

CREATE UNIQUE INDEX IF NOT EXISTS uq_delivery_attempt_idempotency
  ON delivery_attempt(idempotency_key);
CREATE UNIQUE INDEX IF NOT EXISTS uq_delivery_attempt_outbox_number
  ON delivery_attempt(delivery_outbox_id, replay_no, attempt_no)
  WHERE delivery_outbox_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_delivery_attempt_outbox
  ON delivery_attempt(delivery_outbox_id, replay_no, attempt_no);

ALTER TABLE delivery_chunk
  ADD COLUMN delivery_outbox_id TEXT REFERENCES delivery_outbox(id);
ALTER TABLE delivery_chunk
  ADD COLUMN replay_no INTEGER NOT NULL DEFAULT 0 CHECK (replay_no >= 0);
ALTER TABLE delivery_chunk
  ADD COLUMN attempt_no INTEGER NOT NULL DEFAULT 0 CHECK (attempt_no >= 0);
ALTER TABLE delivery_chunk
  ADD COLUMN idempotency_key TEXT NOT NULL DEFAULT '';
ALTER TABLE delivery_chunk
  ADD COLUMN payload_hash TEXT NOT NULL DEFAULT '';
ALTER TABLE delivery_chunk
  ADD COLUMN sent_at TEXT;

UPDATE delivery_chunk
   SET idempotency_key = 'legacy-delivery-chunk:' || id
 WHERE idempotency_key = '';

CREATE UNIQUE INDEX IF NOT EXISTS uq_delivery_chunk_attempt_index
  ON delivery_chunk(delivery_outbox_id, replay_no, attempt_no, chunk_index)
  WHERE delivery_outbox_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_delivery_chunk_logical_success
  ON delivery_chunk(delivery_outbox_id, chunk_index)
  WHERE delivery_outbox_id IS NOT NULL AND status = 'SUCCEEDED';
CREATE INDEX IF NOT EXISTS idx_delivery_chunk_logical
  ON delivery_chunk(delivery_outbox_id, chunk_index, status);

COMMENT ON TABLE delivery_outbox IS
  '持久化 Agent 结果或安全失败通知的独立投递意图；状态不回写 Agent Job 成败';
COMMENT ON COLUMN delivery_outbox.event_key IS
  '结果 artifact 级稳定幂等键';
COMMENT ON COLUMN delivery_outbox.delivery_binding_json IS
  'Job 创建时固化的 delivery route 与 connector binding，不含 Secret 明文';
COMMENT ON COLUMN delivery_outbox.target_summary IS
  '不可逆脱敏的投递目标摘要';
COMMENT ON COLUMN delivery_outbox.claim_token IS
  '多副本 Dispatcher 单次 claim 的随机 ownership token';
COMMENT ON COLUMN delivery_attempt.delivery_outbox_id IS
  '新投递路径所属 Delivery Outbox；旧历史 attempt 可为空';
COMMENT ON COLUMN delivery_attempt.idempotency_key IS
  'Delivery event、replay number 与 attempt number 组成的稳定幂等键';
COMMENT ON COLUMN delivery_chunk.idempotency_key IS
  '跨 attempt 稳定的逻辑 chunk 幂等键';
COMMENT ON COLUMN delivery_chunk.payload_hash IS
  '发送正文的 SHA-256，用于验证重试未改写 payload';
