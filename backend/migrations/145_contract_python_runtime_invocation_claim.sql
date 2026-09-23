-- 调用占用只允许 python-v1。非 Python 占用没有任何 Runtime 可以持有或续约，
-- 属于无主租约（Python Runtime 的过期清理本就不区分 kind），直接删除后收紧约束。
DELETE FROM agent_runtime_invocation_claim WHERE runtime_kind <> 'python-v1';

-- sqlite-only
CREATE TABLE agent_runtime_invocation_claim_v145 (
  invocation_id TEXT PRIMARY KEY,
  request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
  runtime_kind TEXT NOT NULL CHECK (runtime_kind = 'python-v1'),
  owner_instance_id TEXT NOT NULL,
  claimed_at TEXT NOT NULL,
  expires_at TEXT NOT NULL
);
-- sqlite-only
INSERT INTO agent_runtime_invocation_claim_v145
  (invocation_id, request_digest, runtime_kind, owner_instance_id, claimed_at, expires_at)
SELECT invocation_id, request_digest, runtime_kind, owner_instance_id, claimed_at, expires_at
  FROM agent_runtime_invocation_claim;
-- sqlite-only
DROP TABLE agent_runtime_invocation_claim;
-- sqlite-only
ALTER TABLE agent_runtime_invocation_claim_v145 RENAME TO agent_runtime_invocation_claim;
-- sqlite-only
CREATE INDEX idx_agent_runtime_invocation_claim_expires
  ON agent_runtime_invocation_claim(expires_at);

-- postgres-only
ALTER TABLE agent_runtime_invocation_claim
  DROP CONSTRAINT agent_runtime_invocation_claim_runtime_kind_check;
-- postgres-only
ALTER TABLE agent_runtime_invocation_claim
  ADD CONSTRAINT agent_runtime_invocation_claim_runtime_kind_check
  CHECK (runtime_kind = 'python-v1');
-- postgres-only
COMMENT ON TABLE agent_runtime_event IS 'Python Worker按sequence持久化的Python Runtime安全归一化事件，不保存原始SDK消息、Token或私有推理';
-- postgres-only
COMMENT ON TABLE agent_runtime_terminal_ledger IS 'Python Runtime有界终态恢复账本；只保存规范事件并按TTL清理，不保存原始SDK消息或Secret';
