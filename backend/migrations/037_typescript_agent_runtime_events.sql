ALTER TABLE agent_job
  ADD COLUMN agent_runtime_kind TEXT NOT NULL DEFAULT 'python-v1'
    CHECK (agent_runtime_kind IN ('python-v1', 'typescript-v1'));
ALTER TABLE agent_job
  ADD COLUMN agent_runtime_protocol_version TEXT NOT NULL DEFAULT '1.0'
    CHECK (agent_runtime_protocol_version = '1.0');

CREATE TABLE IF NOT EXISTS agent_runtime_event (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  invocation_id TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  sequence INTEGER NOT NULL CHECK (sequence > 0),
  event_type TEXT NOT NULL
    CHECK (event_type IN ('execution_started', 'tool_event', 'assistant_text', 'terminal')),
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(job_id, invocation_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_event_job
  ON agent_runtime_event(job_id, invocation_id, sequence);
CREATE INDEX IF NOT EXISTS idx_agent_runtime_event_digest
  ON agent_runtime_event(request_digest);

COMMENT ON TABLE agent_runtime_event IS
  'Python Worker按sequence持久化的TypeScript Runtime安全归一化事件，不保存原始SDK消息、Token或私有推理';
COMMENT ON COLUMN agent_runtime_event.payload_json IS
  '仅保存V1契约允许的安全payload；写入前再次执行敏感字段清理';

CREATE TABLE IF NOT EXISTS agent_runtime_terminal_ledger (
  invocation_id TEXT PRIMARY KEY,
  request_digest TEXT NOT NULL,
  events_json TEXT NOT NULL,
  terminal_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_terminal_ledger_expiry
  ON agent_runtime_terminal_ledger(expires_at);

COMMENT ON TABLE agent_runtime_terminal_ledger IS
  'TypeScript Runtime重启恢复用的有界安全终态事件，不保存请求、Prompt、Token、Key或原始SDK消息';
