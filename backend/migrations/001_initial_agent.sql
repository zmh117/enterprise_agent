CREATE TABLE IF NOT EXISTS agent_session (
  id TEXT PRIMARY KEY,
  dingding_conversation_id TEXT NOT NULL,
  dingding_user_id TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'dingding',
  project_code TEXT NOT NULL DEFAULT 'default',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

COMMENT ON TABLE agent_session IS 'Agent 会话表，记录外部会话、请求来源和项目归属';
COMMENT ON COLUMN agent_session.id IS 'Agent 会话 ID';
COMMENT ON COLUMN agent_session.dingding_conversation_id IS '钉钉会话 ID，用于兼容早期钉钉入口会话归属';
COMMENT ON COLUMN agent_session.dingding_user_id IS '钉钉用户 ID，用于兼容早期钉钉入口请求人标识';
COMMENT ON COLUMN agent_session.source IS '早期请求来源标识，例如 dingding 或 debug_api';
COMMENT ON COLUMN agent_session.project_code IS '项目编码，用于选择权限、数据源和诊断上下文';
COMMENT ON COLUMN agent_session.created_at IS '会话创建时间';
COMMENT ON COLUMN agent_session.updated_at IS '会话最近更新时间';

CREATE TABLE IF NOT EXISTS agent_job (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES agent_session(id),
  idempotency_key TEXT NOT NULL UNIQUE,
  user_id TEXT NOT NULL,
  project_code TEXT NOT NULL DEFAULT 'default',
  source TEXT NOT NULL DEFAULT 'dingding',
  user_message TEXT NOT NULL,
  status TEXT NOT NULL,
  priority INTEGER NOT NULL DEFAULT 5,
  retry_count INTEGER NOT NULL DEFAULT 0,
  max_retry_count INTEGER NOT NULL DEFAULT 3,
  result TEXT,
  error_message TEXT,
  created_at TEXT NOT NULL,
  started_at TEXT,
  finished_at TEXT,
  locked_at TEXT,
  locked_by TEXT
);

COMMENT ON TABLE agent_job IS 'Agent 任务表，记录一次异步只读诊断执行请求及其状态和结果';
COMMENT ON COLUMN agent_job.id IS 'Agent job ID';
COMMENT ON COLUMN agent_job.session_id IS '归属的 Agent 会话 ID';
COMMENT ON COLUMN agent_job.idempotency_key IS '幂等键，用于防止同一外部请求重复创建任务';
COMMENT ON COLUMN agent_job.user_id IS '发起任务的用户或服务主体 ID';
COMMENT ON COLUMN agent_job.project_code IS '项目编码，用于权限校验、数据源选择和诊断上下文限定';
COMMENT ON COLUMN agent_job.source IS '早期任务来源标识，例如 dingding 或 debug_api';
COMMENT ON COLUMN agent_job.user_message IS '用户原始问题或外部告警转换后的诊断请求文本';
COMMENT ON COLUMN agent_job.status IS '任务状态，例如 PENDING、RUNNING、SUCCEEDED、FAILED';
COMMENT ON COLUMN agent_job.priority IS '任务优先级，数值越小表示优先级越高';
COMMENT ON COLUMN agent_job.retry_count IS '任务已重试次数';
COMMENT ON COLUMN agent_job.max_retry_count IS '任务最大允许重试次数';
COMMENT ON COLUMN agent_job.result IS 'Agent 最终诊断结果文本，未完成或失败时可为空';
COMMENT ON COLUMN agent_job.error_message IS '任务失败时的安全错误摘要';
COMMENT ON COLUMN agent_job.created_at IS '任务创建时间';
COMMENT ON COLUMN agent_job.started_at IS '任务开始执行时间，未开始时为空';
COMMENT ON COLUMN agent_job.finished_at IS '任务完成时间，未完成时为空';
COMMENT ON COLUMN agent_job.locked_at IS '任务被 worker 锁定的时间，用于并发调度控制';
COMMENT ON COLUMN agent_job.locked_by IS '锁定该任务的 worker 标识';

CREATE INDEX IF NOT EXISTS idx_agent_job_status ON agent_job(status);
CREATE INDEX IF NOT EXISTS idx_agent_job_session ON agent_job(session_id);

CREATE TABLE IF NOT EXISTS agent_message (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES agent_session(id),
  job_id TEXT REFERENCES agent_job(id),
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

COMMENT ON TABLE agent_message IS 'Agent 消息表，记录会话内用户、系统和 Agent 的消息历史';
COMMENT ON COLUMN agent_message.id IS '消息 ID';
COMMENT ON COLUMN agent_message.session_id IS '归属的 Agent 会话 ID';
COMMENT ON COLUMN agent_message.job_id IS '关联的 Agent job ID，可为空表示会话级消息';
COMMENT ON COLUMN agent_message.role IS '消息角色，例如 user、assistant、system';
COMMENT ON COLUMN agent_message.content IS '消息正文内容';
COMMENT ON COLUMN agent_message.created_at IS '消息创建时间';

CREATE TABLE IF NOT EXISTS agent_step (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  step_type TEXT NOT NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TEXT NOT NULL
);

COMMENT ON TABLE agent_step IS 'Agent 执行步骤表，记录诊断过程中的阶段性说明和推理摘要';
COMMENT ON COLUMN agent_step.id IS '执行步骤 ID';
COMMENT ON COLUMN agent_step.job_id IS '关联的 Agent job ID';
COMMENT ON COLUMN agent_step.step_type IS '步骤类型，例如 plan、tool、analysis、final';
COMMENT ON COLUMN agent_step.title IS '步骤标题';
COMMENT ON COLUMN agent_step.content IS '步骤内容或摘要';
COMMENT ON COLUMN agent_step.created_at IS '步骤创建时间';

CREATE TABLE IF NOT EXISTS audit_event (
  id TEXT PRIMARY KEY,
  job_id TEXT REFERENCES agent_job(id),
  event_type TEXT NOT NULL,
  actor_id TEXT,
  status TEXT NOT NULL,
  summary TEXT NOT NULL,
  payload_summary TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL
);

COMMENT ON TABLE audit_event IS '审计事件表，记录 Agent、工具平台和投递链路中的关键可审计动作';
COMMENT ON COLUMN audit_event.id IS '审计事件 ID';
COMMENT ON COLUMN audit_event.job_id IS '关联的 Agent job ID，可为空表示系统级审计事件';
COMMENT ON COLUMN audit_event.event_type IS '审计事件类型，例如 permission_check、tool_call、delivery';
COMMENT ON COLUMN audit_event.actor_id IS '触发事件的用户、服务或 worker 标识';
COMMENT ON COLUMN audit_event.status IS '审计事件状态，例如 ALLOWED、DENIED、SUCCEEDED、FAILED';
COMMENT ON COLUMN audit_event.summary IS '面向审计阅读的事件摘要';
COMMENT ON COLUMN audit_event.payload_summary IS '安全载荷摘要 JSON，不保存敏感明文';
COMMENT ON COLUMN audit_event.created_at IS '审计事件创建时间';

CREATE TABLE IF NOT EXISTS agent_tool_call (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  tool_name TEXT NOT NULL,
  request_payload TEXT NOT NULL,
  response_summary TEXT NOT NULL,
  status TEXT NOT NULL,
  duration_ms INTEGER NOT NULL DEFAULT 0,
  risk_level TEXT NOT NULL DEFAULT 'low',
  audit_id TEXT REFERENCES audit_event(id),
  created_at TEXT NOT NULL
);

COMMENT ON TABLE agent_tool_call IS 'Agent 工具调用表，记录只读内部工具调用请求、响应摘要、风险级别和审计关联';
COMMENT ON COLUMN agent_tool_call.id IS '工具调用 ID';
COMMENT ON COLUMN agent_tool_call.job_id IS '关联的 Agent job ID';
COMMENT ON COLUMN agent_tool_call.tool_name IS '工具名称，例如 database.query、loki.query、schema.directory';
COMMENT ON COLUMN agent_tool_call.request_payload IS '工具请求载荷 JSON，应避免保存敏感明文';
COMMENT ON COLUMN agent_tool_call.response_summary IS '工具响应安全摘要';
COMMENT ON COLUMN agent_tool_call.status IS '工具调用状态，例如 SUCCEEDED、FAILED、DENIED';
COMMENT ON COLUMN agent_tool_call.duration_ms IS '工具调用耗时，单位毫秒';
COMMENT ON COLUMN agent_tool_call.risk_level IS '工具风险级别，例如 low、medium、high';
COMMENT ON COLUMN agent_tool_call.audit_id IS '关联的审计事件 ID';
COMMENT ON COLUMN agent_tool_call.created_at IS '工具调用记录创建时间';

CREATE TABLE IF NOT EXISTS agent_artifact (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  artifact_type TEXT NOT NULL,
  name TEXT NOT NULL,
  content TEXT NOT NULL,
  file_path TEXT,
  created_at TEXT NOT NULL
);

COMMENT ON TABLE agent_artifact IS 'Agent 产物表，记录诊断过程中生成的报告、证据摘要或文件引用';
COMMENT ON COLUMN agent_artifact.id IS '产物 ID';
COMMENT ON COLUMN agent_artifact.job_id IS '关联的 Agent job ID';
COMMENT ON COLUMN agent_artifact.artifact_type IS '产物类型，例如 report、evidence、attachment';
COMMENT ON COLUMN agent_artifact.name IS '产物名称';
COMMENT ON COLUMN agent_artifact.content IS '产物内容或安全摘要';
COMMENT ON COLUMN agent_artifact.file_path IS '产物文件路径或外部引用，可为空';
COMMENT ON COLUMN agent_artifact.created_at IS '产物创建时间';
