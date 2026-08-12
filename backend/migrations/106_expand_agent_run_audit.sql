-- Expand Agent run audit facts without adding mutable accounting columns to
-- agent_job. Runtime 1.2 remains backward compatible with pinned 1.0/1.1 Jobs.
-- migration: sqlite-foreign-keys-off

-- SQLite cannot alter an existing CHECK constraint, so rebuild only the Job
-- lifecycle table while preserving its exact columns and rows.
-- sqlite-only
CREATE TABLE agent_job_protocol_v12 (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES agent_session(id),
  idempotency_key TEXT NOT NULL UNIQUE,
  project_code TEXT NOT NULL DEFAULT 'default',
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
  locked_by TEXT,
  source_channel TEXT NOT NULL DEFAULT 'dingding',
  source_connector_id TEXT NOT NULL DEFAULT 'connector-dingtalk-enterprise-default',
  external_event_id TEXT NOT NULL DEFAULT '',
  requester_id TEXT NOT NULL DEFAULT '',
  routing_context_json TEXT NOT NULL DEFAULT '{}',
  reply_route_json TEXT NOT NULL DEFAULT '{"type":"dingtalk_conversation"}',
  internal_user_id TEXT,
  external_identity_id TEXT,
  agent_definition_id TEXT,
  agent_publication_id TEXT,
  agent_revision INTEGER,
  agent_config_hash TEXT NOT NULL DEFAULT '',
  webhook_event_id TEXT REFERENCES webhook_event(id),
  webhook_trigger_id TEXT REFERENCES webhook_trigger_definition(id),
  webhook_trigger_publication_id TEXT REFERENCES webhook_trigger_publication(id),
  last_error_code TEXT NOT NULL DEFAULT '',
  last_error_at TEXT,
  next_retry_at TEXT,
  business_application_id TEXT,
  business_application_code TEXT NOT NULL DEFAULT '',
  business_application_publication_id TEXT,
  business_application_deployment_id TEXT,
  business_application_route_id TEXT,
  business_application_config_hash TEXT NOT NULL DEFAULT '',
  business_application_runtime_status TEXT NOT NULL DEFAULT '',
  business_application_route_decision_json TEXT NOT NULL DEFAULT '{}',
  execution_policy_json TEXT,
  execution_policy_tool_call_count INTEGER NOT NULL DEFAULT 0,
  execution_policy_exhausted INTEGER NOT NULL DEFAULT 0,
  model_runtime_provenance_json TEXT,
  agent_runtime_kind TEXT NOT NULL DEFAULT 'python-v1'
    CHECK (agent_runtime_kind IN ('python-v1', 'typescript-v1')),
  agent_runtime_protocol_version TEXT NOT NULL DEFAULT '1.2'
    CHECK (agent_runtime_protocol_version IN ('1.0', '1.1', '1.2')),
  input_message_id TEXT REFERENCES agent_message(id)
);

-- sqlite-only
INSERT INTO agent_job_protocol_v12 (
  id, session_id, idempotency_key, project_code, status, priority,
  retry_count, max_retry_count, result, error_message, created_at, started_at,
  finished_at, locked_at, locked_by, source_channel, source_connector_id,
  external_event_id, requester_id, routing_context_json, reply_route_json,
  internal_user_id, external_identity_id, agent_definition_id,
  agent_publication_id, agent_revision, agent_config_hash, webhook_event_id,
  webhook_trigger_id, webhook_trigger_publication_id, last_error_code,
  last_error_at, next_retry_at, business_application_id,
  business_application_code, business_application_publication_id,
  business_application_deployment_id, business_application_route_id,
  business_application_config_hash, business_application_runtime_status,
  business_application_route_decision_json, execution_policy_json,
  execution_policy_tool_call_count, execution_policy_exhausted,
  model_runtime_provenance_json, agent_runtime_kind,
  agent_runtime_protocol_version, input_message_id
)
SELECT
  id, session_id, idempotency_key, project_code, status, priority,
  retry_count, max_retry_count, result, error_message, created_at, started_at,
  finished_at, locked_at, locked_by, source_channel, source_connector_id,
  external_event_id, requester_id, routing_context_json, reply_route_json,
  internal_user_id, external_identity_id, agent_definition_id,
  agent_publication_id, agent_revision, agent_config_hash, webhook_event_id,
  webhook_trigger_id, webhook_trigger_publication_id, last_error_code,
  last_error_at, next_retry_at, business_application_id,
  business_application_code, business_application_publication_id,
  business_application_deployment_id, business_application_route_id,
  business_application_config_hash, business_application_runtime_status,
  business_application_route_decision_json, execution_policy_json,
  execution_policy_tool_call_count, execution_policy_exhausted,
  model_runtime_provenance_json, agent_runtime_kind,
  agent_runtime_protocol_version, input_message_id
FROM agent_job;

-- sqlite-only
DROP TABLE agent_job;
-- sqlite-only
ALTER TABLE agent_job_protocol_v12 RENAME TO agent_job;

-- sqlite-only
CREATE INDEX idx_agent_job_status ON agent_job(status);
-- sqlite-only
CREATE INDEX idx_agent_job_session ON agent_job(session_id);
-- sqlite-only
CREATE INDEX idx_agent_job_internal_user ON agent_job(internal_user_id);
-- sqlite-only
CREATE INDEX idx_agent_job_publication ON agent_job(agent_publication_id);
-- sqlite-only
CREATE INDEX idx_agent_job_webhook_event ON agent_job(webhook_event_id);
-- sqlite-only
CREATE INDEX idx_agent_job_webhook_trigger
  ON agent_job(webhook_trigger_id, webhook_trigger_publication_id);
-- sqlite-only
CREATE INDEX idx_agent_job_created_status ON agent_job(created_at, status);
-- sqlite-only
CREATE INDEX idx_agent_job_project_created ON agent_job(project_code, created_at);
-- sqlite-only
CREATE INDEX idx_agent_job_session_created ON agent_job(session_id, created_at);
-- sqlite-only
CREATE INDEX idx_agent_job_source_created ON agent_job(source_channel, created_at);
-- sqlite-only
CREATE INDEX idx_agent_job_retry_due ON agent_job(status, next_retry_at);
-- sqlite-only
CREATE INDEX idx_agent_job_legacy_retry_recovery
  ON agent_job(status, retry_count, locked_at)
  WHERE status = 'RUNNING' OR retry_count > 0;
-- sqlite-only
CREATE INDEX idx_agent_job_business_application
  ON agent_job(business_application_id, created_at);
-- sqlite-only
CREATE INDEX idx_agent_job_business_application_publication
  ON agent_job(business_application_publication_id, created_at);
-- sqlite-only
CREATE INDEX idx_agent_job_business_application_deployment
  ON agent_job(business_application_deployment_id, created_at);
-- sqlite-only
CREATE UNIQUE INDEX idx_agent_job_input_message
  ON agent_job(input_message_id)
  WHERE input_message_id IS NOT NULL;

-- sqlite-only
CREATE TABLE agent_runtime_event_v12 (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  invocation_id TEXT NOT NULL,
  request_digest TEXT NOT NULL,
  sequence INTEGER NOT NULL CHECK (sequence > 0),
  event_type TEXT NOT NULL CHECK (event_type IN (
    'execution_started', 'runtime_initialized', 'model_call', 'api_retry',
    'tool_event', 'assistant_text', 'terminal'
  )),
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(job_id, invocation_id, sequence)
);

-- sqlite-only
INSERT INTO agent_runtime_event_v12
  (id, job_id, invocation_id, request_digest, sequence, event_type,
   payload_json, created_at)
SELECT id, job_id, invocation_id, request_digest, sequence, event_type,
       payload_json, created_at
  FROM agent_runtime_event;
-- sqlite-only
DROP TABLE agent_runtime_event;
-- sqlite-only
ALTER TABLE agent_runtime_event_v12 RENAME TO agent_runtime_event;

-- postgres-only
ALTER TABLE agent_job
  DROP CONSTRAINT agent_job_agent_runtime_protocol_version_check;
-- postgres-only
ALTER TABLE agent_job
  ADD CONSTRAINT agent_job_agent_runtime_protocol_version_check
  CHECK (agent_runtime_protocol_version IN ('1.0', '1.1', '1.2'));
-- postgres-only
ALTER TABLE agent_job
  ALTER COLUMN agent_runtime_protocol_version SET DEFAULT '1.2';

-- postgres-only
ALTER TABLE agent_runtime_event
  DROP CONSTRAINT agent_runtime_event_event_type_check;
-- postgres-only
ALTER TABLE agent_runtime_event
  ADD CONSTRAINT agent_runtime_event_event_type_check CHECK (event_type IN (
    'execution_started', 'runtime_initialized', 'model_call', 'api_retry',
    'tool_event', 'assistant_text', 'terminal'
  ));

CREATE TABLE agent_job_execution_summary (
  job_id TEXT PRIMARY KEY REFERENCES agent_job(id) ON DELETE CASCADE,
  accounting_status TEXT NOT NULL
    CHECK (accounting_status IN ('COMPLETE', 'PARTIAL', 'UNAVAILABLE')),
  observed_model_turn_count BIGINT NOT NULL DEFAULT 0
    CHECK (observed_model_turn_count >= 0),
  api_retry_count BIGINT NOT NULL DEFAULT 0 CHECK (api_retry_count >= 0),
  runtime_invocation_count BIGINT NOT NULL DEFAULT 0
    CHECK (runtime_invocation_count >= 0),
  total_duration_ms BIGINT CHECK (total_duration_ms IS NULL OR total_duration_ms >= 0),
  total_api_duration_ms BIGINT
    CHECK (total_api_duration_ms IS NULL OR total_api_duration_ms >= 0),
  input_tokens BIGINT CHECK (input_tokens IS NULL OR input_tokens >= 0),
  output_tokens BIGINT CHECK (output_tokens IS NULL OR output_tokens >= 0),
  cache_creation_input_tokens BIGINT
    CHECK (cache_creation_input_tokens IS NULL OR cache_creation_input_tokens >= 0),
  cache_read_input_tokens BIGINT
    CHECK (cache_read_input_tokens IS NULL OR cache_read_input_tokens >= 0),
  model_usage_json TEXT NOT NULL DEFAULT '[]',
  estimated_cost_usd NUMERIC(20, 12)
    CHECK (estimated_cost_usd IS NULL OR estimated_cost_usd >= 0),
  execution_status TEXT NOT NULL DEFAULT 'UNKNOWN'
    CHECK (execution_status IN ('SUCCEEDED', 'FAILED', 'CANCELLED', 'UNKNOWN')),
  execution_failure_stage TEXT CHECK (
    execution_failure_stage IS NULL OR execution_failure_stage IN (
      'RUNTIME_START', 'RUNTIME_PROTOCOL', 'MCP_CONNECTION', 'MODEL_API',
      'TOOL_PERMISSION', 'TOOL_EXECUTION', 'UNKNOWN'
    )
  ),
  failure_code TEXT CHECK (failure_code IS NULL OR length(failure_code) <= 128),
  failure_summary TEXT CHECK (failure_summary IS NULL OR length(failure_summary) <= 2048),
  retry_exhausted INTEGER NOT NULL DEFAULT 0 CHECK (retry_exhausted IN (0, 1)),
  source_protocol_version TEXT NOT NULL
    CHECK (source_protocol_version IN ('1.0', '1.1', '1.2')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE agent_model_call (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id) ON DELETE CASCADE,
  invocation_id TEXT NOT NULL CHECK (length(invocation_id) BETWEEN 1 AND 128),
  request_digest TEXT NOT NULL CHECK (length(request_digest) = 64),
  runtime_sequence BIGINT NOT NULL CHECK (runtime_sequence BETWEEN 1 AND 2048),
  provider_request_id TEXT CHECK (
    provider_request_id IS NULL OR length(provider_request_id) <= 200
  ),
  provider_message_id TEXT CHECK (
    provider_message_id IS NULL OR length(provider_message_id) <= 200
  ),
  model_id TEXT NOT NULL CHECK (length(model_id) BETWEEN 1 AND 200),
  status TEXT NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED')),
  started_at TEXT,
  completed_at TEXT NOT NULL,
  duration_ms BIGINT CHECK (duration_ms IS NULL OR duration_ms >= 0),
  duration_source TEXT NOT NULL
    CHECK (duration_source IN ('SDK_OBSERVED', 'UNAVAILABLE')),
  input_tokens BIGINT CHECK (input_tokens IS NULL OR input_tokens >= 0),
  output_tokens BIGINT CHECK (output_tokens IS NULL OR output_tokens >= 0),
  cache_creation_input_tokens BIGINT
    CHECK (cache_creation_input_tokens IS NULL OR cache_creation_input_tokens >= 0),
  cache_read_input_tokens BIGINT
    CHECK (cache_read_input_tokens IS NULL OR cache_read_input_tokens >= 0),
  stop_reason TEXT CHECK (stop_reason IS NULL OR length(stop_reason) <= 128),
  error_code TEXT CHECK (error_code IS NULL OR length(error_code) <= 128),
  error_summary TEXT CHECK (error_summary IS NULL OR length(error_summary) <= 2048),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE (job_id, invocation_id, runtime_sequence),
  CHECK (
    (duration_source = 'UNAVAILABLE' AND duration_ms IS NULL AND started_at IS NULL)
    OR duration_source = 'SDK_OBSERVED'
  )
);

CREATE INDEX idx_agent_job_execution_summary_status
  ON agent_job_execution_summary(execution_status, execution_failure_stage, updated_at, job_id);
CREATE INDEX idx_agent_job_execution_summary_updated
  ON agent_job_execution_summary(updated_at, job_id);
CREATE INDEX idx_agent_model_call_job_sequence
  ON agent_model_call(job_id, runtime_sequence, id);
CREATE INDEX idx_agent_model_call_model_completed
  ON agent_model_call(model_id, completed_at, id);
CREATE INDEX idx_agent_model_call_status_completed
  ON agent_model_call(status, completed_at, id);

COMMENT ON TABLE agent_job_execution_summary IS
  'Agent Job 级可重算执行核算与安全失败诊断；不承载 Job 生命周期事实。';
COMMENT ON COLUMN agent_job_execution_summary.job_id IS '关联的 Agent Job；与 Job 同保留周期。';
COMMENT ON COLUMN agent_job_execution_summary.accounting_status IS '核算完整性：COMPLETE、PARTIAL 或 UNAVAILABLE。';
COMMENT ON COLUMN agent_job_execution_summary.observed_model_turn_count IS '已投影的 SDK 模型轮次数。';
COMMENT ON COLUMN agent_job_execution_summary.api_retry_count IS 'SDK 报告的模型 API 重试事件数。';
COMMENT ON COLUMN agent_job_execution_summary.runtime_invocation_count IS '具有唯一终态的 Runtime invocation 数。';
COMMENT ON COLUMN agent_job_execution_summary.total_duration_ms IS 'ResultMessage 报告的 query 总耗时毫秒汇总；未知为 NULL。';
COMMENT ON COLUMN agent_job_execution_summary.total_api_duration_ms IS 'ResultMessage 报告的 API 耗时毫秒汇总；未知为 NULL。';
COMMENT ON COLUMN agent_job_execution_summary.input_tokens IS '输入 Token 总量；未知为 NULL。';
COMMENT ON COLUMN agent_job_execution_summary.output_tokens IS '输出 Token 总量；未知为 NULL。';
COMMENT ON COLUMN agent_job_execution_summary.cache_creation_input_tokens IS '缓存创建输入 Token 总量；未知为 NULL。';
COMMENT ON COLUMN agent_job_execution_summary.cache_read_input_tokens IS '缓存读取输入 Token 总量；未知为 NULL。';
COMMENT ON COLUMN agent_job_execution_summary.model_usage_json IS
  '固定白名单 schema 的按模型 usage 数值汇总，不得保存 raw SDK JSON。';
COMMENT ON COLUMN agent_job_execution_summary.estimated_cost_usd IS
  'Claude Agent SDK ResultMessage 返回的 query 级估算成本，不是账单。';
COMMENT ON COLUMN agent_job_execution_summary.execution_status IS '独立于 Delivery 的 Agent 执行投影状态。';
COMMENT ON COLUMN agent_job_execution_summary.execution_failure_stage IS '由 typed 事件分类的稳定执行失败阶段。';
COMMENT ON COLUMN agent_job_execution_summary.failure_code IS '有界稳定错误码；不得从自由文本猜测。';
COMMENT ON COLUMN agent_job_execution_summary.failure_summary IS '有界安全错误摘要。';
COMMENT ON COLUMN agent_job_execution_summary.retry_exhausted IS 'Job retry 是否耗尽；不覆盖根因。';
COMMENT ON COLUMN agent_job_execution_summary.source_protocol_version IS '生成投影的固定 Runtime 协议版本。';
COMMENT ON COLUMN agent_job_execution_summary.created_at IS '投影首次创建时间。';
COMMENT ON COLUMN agent_job_execution_summary.updated_at IS '最近一次确定性重建时间。';
COMMENT ON TABLE agent_model_call IS
  'SDK 可见模型响应轮次；不保存 Prompt、完整回复、raw SDK message 或 private thinking。';
COMMENT ON COLUMN agent_model_call.id IS '由 Job、invocation 和 sequence 派生的稳定投影 ID。';
COMMENT ON COLUMN agent_model_call.job_id IS '关联的 Agent Job。';
COMMENT ON COLUMN agent_model_call.invocation_id IS '固定 Runtime invocation 身份。';
COMMENT ON COLUMN agent_model_call.request_digest IS '固定 Runtime 请求摘要。';
COMMENT ON COLUMN agent_model_call.runtime_sequence IS '模型轮次对应的 Runtime event sequence。';
COMMENT ON COLUMN agent_model_call.provider_request_id IS 'SDK 暴露的安全 Provider request 标识；未知为 NULL。';
COMMENT ON COLUMN agent_model_call.provider_message_id IS 'SDK 暴露的安全 Provider message 标识；未知为 NULL。';
COMMENT ON COLUMN agent_model_call.model_id IS 'SDK 报告的有界模型标识。';
COMMENT ON COLUMN agent_model_call.status IS '模型轮次终态。';
COMMENT ON COLUMN agent_model_call.started_at IS '本地 SDK 观测请求起点；不可用为 NULL。';
COMMENT ON COLUMN agent_model_call.completed_at IS 'SDK 模型消息观测完成时间。';
COMMENT ON COLUMN agent_model_call.duration_ms IS '本地 SDK 观测耗时；不可用为 NULL。';
COMMENT ON COLUMN agent_model_call.duration_source IS
  'SDK_OBSERVED 表示 SDK 请求边界观测值；不得解释为 Provider HTTP Span。';
COMMENT ON COLUMN agent_model_call.input_tokens IS '本轮输入 Token；未知为 NULL。';
COMMENT ON COLUMN agent_model_call.output_tokens IS '本轮输出 Token；未知为 NULL。';
COMMENT ON COLUMN agent_model_call.cache_creation_input_tokens IS '本轮缓存创建输入 Token；未知为 NULL。';
COMMENT ON COLUMN agent_model_call.cache_read_input_tokens IS '本轮缓存读取输入 Token；未知为 NULL。';
COMMENT ON COLUMN agent_model_call.stop_reason IS 'SDK 报告的有界停止原因。';
COMMENT ON COLUMN agent_model_call.error_code IS 'SDK 或 Runtime typed 有界错误码。';
COMMENT ON COLUMN agent_model_call.error_summary IS '有界安全错误摘要。';
COMMENT ON COLUMN agent_model_call.created_at IS '投影首次创建时间。';
COMMENT ON COLUMN agent_model_call.updated_at IS '投影最近确认时间。';
