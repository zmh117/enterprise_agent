ALTER TABLE agent_job ADD COLUMN worker_lease_until TEXT;
ALTER TABLE agent_job ADD COLUMN worker_claim_version INTEGER NOT NULL DEFAULT 0
  CHECK (worker_claim_version >= 0);
ALTER TABLE agent_job ADD COLUMN cancel_requested_at TEXT;
ALTER TABLE agent_job ADD COLUMN cancel_requested_by TEXT;
ALTER TABLE agent_job ADD COLUMN cancel_reason TEXT;
ALTER TABLE agent_job ADD COLUMN admission_deadline_at TEXT;

CREATE INDEX idx_agent_job_worker_lease ON agent_job(status, worker_lease_until);

CREATE TABLE agent_runtime_invocation (
  invocation_id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id) ON DELETE CASCADE,
  attempt INTEGER NOT NULL CHECK (attempt >= 0),
  request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
  protocol_version TEXT NOT NULL CHECK (protocol_version IN ('1.4', '1.5')),
  app_user_id TEXT NOT NULL,
  agent_publication_id TEXT NOT NULL,
  application_publication_id TEXT NOT NULL,
  timeout_seconds INTEGER NOT NULL CHECK (timeout_seconds > 0 AND timeout_seconds <= 3600),
  state TEXT NOT NULL CHECK (state IN ('PREPARED', 'RUNNING', 'TERMINAL')),
  node_id TEXT,
  instance_id TEXT,
  created_at TEXT NOT NULL,
  admission_deadline_at TEXT NOT NULL,
  accepted_at TEXT,
  execution_deadline_at TEXT,
  lease_until TEXT,
  cancel_requested_at TEXT,
  cancel_reason TEXT,
  terminal_code TEXT,
  terminal_at TEXT,
  execution_quiesced_at TEXT,
  UNIQUE (job_id, attempt),
  CHECK ((node_id IS NULL AND instance_id IS NULL AND accepted_at IS NULL)
    OR (node_id IS NOT NULL AND instance_id IS NOT NULL AND accepted_at IS NOT NULL)),
  CHECK (state <> 'PREPARED' OR node_id IS NULL),
  CHECK (state <> 'RUNNING' OR
    (node_id IS NOT NULL AND lease_until IS NOT NULL AND execution_deadline_at IS NOT NULL)),
  CHECK ((state = 'TERMINAL' AND terminal_at IS NOT NULL AND terminal_code IS NOT NULL)
    OR (state <> 'TERMINAL' AND terminal_at IS NULL AND terminal_code IS NULL))
);

CREATE INDEX idx_runtime_invocation_lease ON agent_runtime_invocation(state, lease_until);
CREATE INDEX idx_runtime_invocation_owner ON agent_runtime_invocation(node_id, instance_id);
CREATE INDEX idx_runtime_invocation_job_quiescence
  ON agent_runtime_invocation(job_id, execution_quiesced_at);

CREATE TABLE agent_runtime_request_snapshot (
  invocation_id TEXT PRIMARY KEY REFERENCES agent_runtime_invocation(invocation_id) ON DELETE CASCADE,
  request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
  request_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

ALTER TABLE job_dispatch_outbox ADD COLUMN wait_reason TEXT;

-- postgres-only
COMMENT ON TABLE agent_runtime_invocation IS
  'Runtime执行归属及不可再执行标记，至少随Job保留，逻辑终态与实际停止证据分离';
-- postgres-only
COMMENT ON TABLE agent_runtime_request_snapshot IS
  '受保护的不可变执行请求，仅执行及恢复路径读取，禁止认证Header或明文凭据';

-- postgres-only
COMMENT ON COLUMN agent_job.worker_lease_until IS '当前 Worker 控制租约截止，数据库 UTC 时间';

-- postgres-only
COMMENT ON COLUMN agent_job.worker_claim_version IS '每次领取递增的 Worker 写入栅栏版本';

-- postgres-only
COMMENT ON COLUMN agent_job.cancel_requested_at IS '持久化取消意图首次提交时间';

-- postgres-only
COMMENT ON COLUMN agent_job.cancel_requested_by IS '取消请求的内部操作者标识';

-- postgres-only
COMMENT ON COLUMN agent_job.cancel_reason IS '安全取消原因码，不保存自由文本';

-- postgres-only
COMMENT ON COLUMN agent_job.admission_deadline_at IS '当前业务 attempt 的准入截止，容量延期不重置';

-- postgres-only
COMMENT ON COLUMN job_dispatch_outbox.wait_reason IS '容量、会话或控制者恢复的安全等待原因码';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.invocation_id IS '不可复用的执行身份，与 Job attempt 唯一对应';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.job_id IS '所属 Job 标识';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.attempt IS '业务 attempt 序号，恢复不递增';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.request_digest IS '不可变执行请求的 SHA256 摘要';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.protocol_version IS '冻结的执行协议版本';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.app_user_id IS '冻结的执行主体，用于恢复 Grant 绑定';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.agent_publication_id IS '冻结 Agent Publication 标识';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.application_publication_id IS '冻结 Application Publication 标识';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.timeout_seconds IS '冻结执行时长上限，准入后计算绝对截止';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.state IS 'PREPARED、RUNNING 或不可再次执行的 TERMINAL';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.node_id IS '准入时固定的 Compose 节点标识，不允许迁移';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.instance_id IS '准入节点启动 UUID，不允许复用';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.created_at IS '准备事务提交的 UTC 时间';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.admission_deadline_at IS '本 attempt 的准入截止，不随恢复延长';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.accepted_at IS '执行归属提交时间，先于 SDK 启动';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.execution_deadline_at IS '准入后固定的执行截止';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.lease_until IS '执行者租约截止，过期不可续活';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.cancel_requested_at IS '取消意图首次提交时间';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.cancel_reason IS '安全取消原因码';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.terminal_code IS '唯一结果或中断原因，不含业务正文';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.terminal_at IS '逻辑终态提交时间，不代表实际停止';

-- postgres-only
COMMENT ON COLUMN agent_runtime_invocation.execution_quiesced_at IS '已确认本地 SDK 停止或固定容器被替换的证据时间';

-- postgres-only
COMMENT ON COLUMN agent_runtime_request_snapshot.invocation_id IS '关联不可复用的执行身份';

-- postgres-only
COMMENT ON COLUMN agent_runtime_request_snapshot.request_digest IS '受保护正文的摘要';

-- postgres-only
COMMENT ON COLUMN agent_runtime_request_snapshot.request_json IS '不可变 canonical request 正文，禁止认证 Header 或凭据';

-- postgres-only
COMMENT ON COLUMN agent_runtime_request_snapshot.created_at IS '请求快照创建时间';
