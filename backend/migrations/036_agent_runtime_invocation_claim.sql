CREATE TABLE IF NOT EXISTS agent_runtime_invocation_claim (
  invocation_id TEXT PRIMARY KEY,
  request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
  runtime_kind TEXT NOT NULL
    CHECK (runtime_kind IN ('python-v1', 'typescript-v1')),
  owner_instance_id TEXT NOT NULL,
  claimed_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_invocation_claim_expires
  ON agent_runtime_invocation_claim(expires_at);

CREATE TABLE IF NOT EXISTS agent_runtime_invocation_event (
  invocation_id TEXT NOT NULL,
  request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
  sequence INTEGER NOT NULL CHECK (sequence > 0),
  event_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  PRIMARY KEY (invocation_id, sequence)
);

CREATE INDEX IF NOT EXISTS idx_agent_runtime_invocation_event_expires
  ON agent_runtime_invocation_event(expires_at);

COMMENT ON TABLE agent_runtime_invocation_claim IS
  'Agent Runtime模型调用前的有界执行占用；Runtime重启后遗留占用失败关闭，禁止自动重放模型';
COMMENT ON COLUMN agent_runtime_invocation_claim.owner_instance_id IS
  'Runtime进程启动实例标识，仅用于区分本进程执行与重启遗留执行，不是凭据';
COMMENT ON TABLE agent_runtime_invocation_event IS
  'Agent Runtime追加式脱敏事件前缀；重启后只用于续接orphan终态，不恢复或重放模型SDK流';
