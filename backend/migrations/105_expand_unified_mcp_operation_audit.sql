-- Expand the Runtime Tool fact and the MCP execution evidence model without
-- guessing historical links. Existing ONES audit rows remain readable and
-- receive deterministic legacy MCP call ids only.
-- migration: sqlite-foreign-keys-off

-- New publications use Runtime protocol 1.1 while existing Job rows retain
-- their pinned 1.0 value during the dual-read compatibility window.
-- sqlite-only
CREATE TABLE agent_job_protocol_expand (
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
  agent_runtime_protocol_version TEXT NOT NULL DEFAULT '1.1'
    CHECK (agent_runtime_protocol_version IN ('1.0', '1.1')),
  input_message_id TEXT REFERENCES agent_message(id)
);

-- sqlite-only
INSERT INTO agent_job_protocol_expand (
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
ALTER TABLE agent_job_protocol_expand RENAME TO agent_job;

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

-- postgres-only
ALTER TABLE agent_job
  DROP CONSTRAINT agent_job_agent_runtime_protocol_version_check;
-- postgres-only
ALTER TABLE agent_job
  ADD CONSTRAINT agent_job_agent_runtime_protocol_version_check
  CHECK (agent_runtime_protocol_version IN ('1.0', '1.1'));
-- postgres-only
ALTER TABLE agent_job
  ALTER COLUMN agent_runtime_protocol_version SET DEFAULT '1.1';

ALTER TABLE agent_tool_call ADD COLUMN invocation_id TEXT;
ALTER TABLE agent_tool_call ADD COLUMN runtime_tool_call_id TEXT;
ALTER TABLE agent_tool_call ADD COLUMN tool_origin TEXT NOT NULL DEFAULT 'unknown'
  CHECK (tool_origin IN ('mcp', 'sdk_builtin', 'sdk_custom', 'unknown'));
ALTER TABLE agent_tool_call ADD COLUMN server_code TEXT;
ALTER TABLE agent_tool_call ADD COLUMN mcp_call_id TEXT;
ALTER TABLE agent_tool_call ADD COLUMN persisted_by TEXT NOT NULL DEFAULT 'worker'
  CHECK (persisted_by IN ('mcp_server', 'worker'));

CREATE UNIQUE INDEX uq_agent_tool_call_runtime_identity
  ON agent_tool_call(job_id, invocation_id, runtime_tool_call_id)
  WHERE invocation_id IS NOT NULL AND runtime_tool_call_id IS NOT NULL;

CREATE UNIQUE INDEX uq_agent_tool_call_mcp_call
  ON agent_tool_call(mcp_call_id)
  WHERE mcp_call_id IS NOT NULL;

CREATE INDEX idx_agent_tool_call_origin_server
  ON agent_tool_call(tool_origin, server_code, tool_name, created_at, id);

-- sqlite-only
ALTER TABLE mcp_operation_audit RENAME TO mcp_operation_audit_before_unification;

-- sqlite-only
CREATE TABLE mcp_operation_audit (
  id TEXT PRIMARY KEY,
  mcp_call_id TEXT NOT NULL,
  parent_audit_id TEXT REFERENCES mcp_operation_audit(id) ON DELETE CASCADE,
  correlation_id TEXT NOT NULL,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  session_id TEXT NOT NULL REFERENCES agent_session(id),
  invocation_id TEXT,
  agent_publication_id TEXT,
  application_publication_id TEXT,
  principal_jti TEXT,
  actor_user_id TEXT NOT NULL REFERENCES app_user(id),
  actor_type TEXT NOT NULL DEFAULT 'user'
    CHECK (actor_type IN ('user', 'agent', 'system')),
  external_identity_id TEXT REFERENCES user_external_identity(id),
  credential_id TEXT REFERENCES external_identity_credential(id),
  credential_revision INTEGER CHECK (
    credential_revision IS NULL OR credential_revision >= 1
  ),
  provider TEXT,
  team_id TEXT,
  provider_email TEXT,
  provider_user_id TEXT,
  server_code TEXT NOT NULL,
  tool_identifier TEXT NOT NULL,
  tool_schema_hash TEXT NOT NULL DEFAULT '',
  operation TEXT NOT NULL,
  event_kind TEXT NOT NULL CHECK (
    event_kind IN ('TOOL', 'AUTHORIZATION', 'RESOURCE', 'PROVIDER', 'CREDENTIAL')
  ),
  attempt INTEGER NOT NULL DEFAULT 0 CHECK (attempt >= 0),
  status TEXT NOT NULL CHECK (
    status IN ('STARTED', 'SUCCEEDED', 'FAILED', 'DENIED')
  ),
  error_code TEXT NOT NULL DEFAULT '',
  duration_ms INTEGER NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
  authorization_decision TEXT NOT NULL DEFAULT '',
  authorization_reason TEXT NOT NULL DEFAULT '',
  resource_code TEXT,
  resource_deployment_id TEXT,
  resource_revision_id TEXT,
  resource_placement TEXT,
  target_type TEXT NOT NULL DEFAULT '',
  target_id TEXT NOT NULL DEFAULT '',
  target_name TEXT NOT NULL DEFAULT '',
  payload_schema_version INTEGER NOT NULL DEFAULT 2
    CHECK (payload_schema_version IN (1, 2)),
  tool_request_json TEXT NOT NULL DEFAULT '{}',
  provider_request_json TEXT NOT NULL DEFAULT '{}',
  provider_response_json TEXT NOT NULL DEFAULT '{}',
  tool_response_json TEXT NOT NULL DEFAULT '{}',
  business_request_json TEXT NOT NULL DEFAULT '{}',
  business_response_json TEXT NOT NULL DEFAULT '{}',
  request_truncated INTEGER NOT NULL DEFAULT 0 CHECK (request_truncated IN (0, 1)),
  response_truncated INTEGER NOT NULL DEFAULT 0 CHECK (response_truncated IN (0, 1)),
  payload_digest TEXT NOT NULL DEFAULT ''
    CHECK (payload_digest = '' OR length(payload_digest) = 64),
  legacy_link_status TEXT NOT NULL DEFAULT 'LINKED'
    CHECK (legacy_link_status IN ('LINKED', 'LEGACY_UNLINKED')),
  audit_event_id TEXT REFERENCES audit_event(id) ON DELETE SET NULL,
  agent_tool_call_id TEXT REFERENCES agent_tool_call(id) ON DELETE SET NULL,
  created_at TEXT NOT NULL,
  completed_at TEXT
);

-- sqlite-only
INSERT INTO mcp_operation_audit (
  id, mcp_call_id, parent_audit_id, correlation_id, job_id, session_id,
  invocation_id, agent_publication_id, application_publication_id,
  principal_jti, actor_user_id, actor_type,
  external_identity_id, credential_id, credential_revision, provider,
  team_id, provider_email, provider_user_id, server_code, tool_identifier,
  tool_schema_hash, operation, event_kind, attempt, status, error_code, duration_ms,
  authorization_decision, authorization_reason, resource_code,
  resource_deployment_id, resource_revision_id, resource_placement,
  target_type, target_id,
  target_name, payload_schema_version, tool_request_json,
  provider_request_json, provider_response_json, tool_response_json,
  business_request_json, business_response_json, request_truncated,
  response_truncated, payload_digest, legacy_link_status, audit_event_id,
  agent_tool_call_id, created_at, completed_at
)
SELECT
  id, 'legacy:' || id, NULL, correlation_id, job_id, session_id,
  NULL, NULL, NULL, principal_jti, actor_user_id, actor_type,
  external_identity_id, credential_id, credential_revision, provider,
  team_id, provider_email, provider_user_id, server_code, tool_identifier,
  '', operation, event_kind, attempt, status, error_code, duration_ms,
  '', '', NULL, NULL, NULL, NULL, '', '', '', 1, tool_request_json,
  provider_request_json, provider_response_json, tool_response_json,
  tool_request_json, tool_response_json, 0, 0, '',
  CASE WHEN agent_tool_call_id IS NULL THEN 'LEGACY_UNLINKED' ELSE 'LINKED' END,
  audit_event_id, agent_tool_call_id, created_at,
  CASE WHEN status = 'STARTED' THEN NULL ELSE created_at END
FROM mcp_operation_audit_before_unification;

-- sqlite-only
DROP TABLE mcp_operation_audit_before_unification;

-- sqlite-only
CREATE INDEX idx_mcp_operation_audit_created
  ON mcp_operation_audit(created_at, id);
-- sqlite-only
CREATE INDEX idx_mcp_operation_audit_correlation
  ON mcp_operation_audit(correlation_id, created_at, id);
-- sqlite-only
CREATE INDEX idx_mcp_operation_audit_job
  ON mcp_operation_audit(job_id, created_at, id);
-- sqlite-only
CREATE INDEX idx_mcp_operation_audit_actor
  ON mcp_operation_audit(actor_user_id, created_at, id);
-- sqlite-only
CREATE INDEX idx_mcp_operation_audit_identity
  ON mcp_operation_audit(external_identity_id, created_at, id);
-- sqlite-only
CREATE INDEX idx_mcp_operation_audit_principal
  ON mcp_operation_audit(principal_jti, created_at, id);
-- sqlite-only
CREATE INDEX idx_mcp_operation_audit_status
  ON mcp_operation_audit(status, error_code, created_at, id);

-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN mcp_call_id TEXT;
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN parent_audit_id TEXT;
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN invocation_id TEXT;
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN agent_publication_id TEXT;
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN application_publication_id TEXT;
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN authorization_decision TEXT NOT NULL DEFAULT '';
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN authorization_reason TEXT NOT NULL DEFAULT '';
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN tool_schema_hash TEXT NOT NULL DEFAULT '';
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN resource_code TEXT;
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN resource_deployment_id TEXT;
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN resource_revision_id TEXT;
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN resource_placement TEXT;
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN target_type TEXT NOT NULL DEFAULT '';
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN target_id TEXT NOT NULL DEFAULT '';
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN target_name TEXT NOT NULL DEFAULT '';
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN business_request_json TEXT NOT NULL DEFAULT '{}';
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN business_response_json TEXT NOT NULL DEFAULT '{}';
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN request_truncated INTEGER NOT NULL DEFAULT 0;
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN response_truncated INTEGER NOT NULL DEFAULT 0;
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN payload_digest TEXT NOT NULL DEFAULT '';
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN legacy_link_status TEXT NOT NULL DEFAULT 'LINKED';
-- postgres-only
ALTER TABLE mcp_operation_audit ADD COLUMN completed_at TEXT;

-- postgres-only
UPDATE mcp_operation_audit
   SET mcp_call_id = 'legacy:' || id,
       business_request_json = tool_request_json,
       business_response_json = tool_response_json,
       legacy_link_status = CASE
         WHEN agent_tool_call_id IS NULL THEN 'LEGACY_UNLINKED'
         ELSE 'LINKED'
       END,
       completed_at = CASE WHEN status = 'STARTED' THEN NULL ELSE created_at END;

-- postgres-only
ALTER TABLE mcp_operation_audit ALTER COLUMN mcp_call_id SET NOT NULL;
-- postgres-only
ALTER TABLE mcp_operation_audit ALTER COLUMN principal_jti DROP NOT NULL;
-- postgres-only
ALTER TABLE mcp_operation_audit ALTER COLUMN provider DROP NOT NULL;
-- postgres-only
ALTER TABLE mcp_operation_audit ALTER COLUMN team_id DROP NOT NULL;
-- postgres-only
ALTER TABLE mcp_operation_audit ALTER COLUMN provider_email DROP NOT NULL;
-- postgres-only
ALTER TABLE mcp_operation_audit ALTER COLUMN provider_user_id DROP NOT NULL;
-- postgres-only
ALTER TABLE mcp_operation_audit ALTER COLUMN payload_schema_version SET DEFAULT 2;
-- postgres-only
ALTER TABLE mcp_operation_audit DROP CONSTRAINT mcp_operation_audit_event_kind_check;
-- postgres-only
ALTER TABLE mcp_operation_audit ADD CONSTRAINT mcp_operation_audit_event_kind_check
  CHECK (event_kind IN ('TOOL', 'AUTHORIZATION', 'RESOURCE', 'PROVIDER', 'CREDENTIAL'));
-- postgres-only
ALTER TABLE mcp_operation_audit DROP CONSTRAINT mcp_operation_audit_payload_schema_version_check;
-- postgres-only
ALTER TABLE mcp_operation_audit ADD CONSTRAINT mcp_operation_audit_payload_schema_version_check
  CHECK (payload_schema_version IN (1, 2));
-- postgres-only
ALTER TABLE mcp_operation_audit ADD CONSTRAINT mcp_operation_audit_request_truncated_check
  CHECK (request_truncated IN (0, 1));
-- postgres-only
ALTER TABLE mcp_operation_audit ADD CONSTRAINT mcp_operation_audit_response_truncated_check
  CHECK (response_truncated IN (0, 1));
-- postgres-only
ALTER TABLE mcp_operation_audit ADD CONSTRAINT mcp_operation_audit_payload_digest_check
  CHECK (payload_digest = '' OR length(payload_digest) = 64);
-- postgres-only
ALTER TABLE mcp_operation_audit ADD CONSTRAINT mcp_operation_audit_legacy_link_status_check
  CHECK (legacy_link_status IN ('LINKED', 'LEGACY_UNLINKED'));
-- postgres-only
ALTER TABLE mcp_operation_audit ADD CONSTRAINT fk_mcp_operation_audit_parent
  FOREIGN KEY (parent_audit_id) REFERENCES mcp_operation_audit(id) ON DELETE CASCADE;

CREATE UNIQUE INDEX uq_mcp_operation_audit_tool_root
  ON mcp_operation_audit(mcp_call_id)
  WHERE event_kind = 'TOOL';

CREATE UNIQUE INDEX uq_mcp_operation_audit_child_attempt
  ON mcp_operation_audit(mcp_call_id, event_kind, attempt)
  WHERE event_kind <> 'TOOL';

CREATE INDEX idx_mcp_operation_audit_mcp_call
  ON mcp_operation_audit(mcp_call_id, event_kind, attempt, created_at, id);

CREATE INDEX idx_mcp_operation_audit_parent
  ON mcp_operation_audit(parent_audit_id, created_at, id);

CREATE INDEX idx_mcp_operation_audit_server_tool
  ON mcp_operation_audit(server_code, tool_identifier, event_kind, status, created_at, id);

CREATE INDEX idx_mcp_operation_audit_job_invocation
  ON mcp_operation_audit(job_id, invocation_id, created_at, id);

COMMENT ON COLUMN agent_tool_call.invocation_id IS
  '固定 Runtime invocation identity；legacy 记录为空。';
COMMENT ON COLUMN agent_tool_call.runtime_tool_call_id IS
  'Claude Agent SDK 真实 Tool Use ID；不得按工具名推断。';
COMMENT ON COLUMN agent_tool_call.tool_origin IS
  'mcp、sdk_builtin、sdk_custom 或 unknown 的代码目录分类。';
COMMENT ON COLUMN agent_tool_call.server_code IS
  '仅 MCP 来源设置的通用 MCP Server code。';
COMMENT ON COLUMN agent_tool_call.mcp_call_id IS
  'MCP Server 首写的一次调用稳定 ID。';
COMMENT ON COLUMN agent_tool_call.persisted_by IS
  '逻辑 Tool Call 首写方：mcp_server 或 worker。';
COMMENT ON COLUMN mcp_operation_audit.mcp_call_id IS
  '同一次 MCP Tool Call 的服务端稳定分组 ID。';
COMMENT ON COLUMN mcp_operation_audit.parent_audit_id IS
  'AUTHORIZATION、RESOURCE、PROVIDER、CREDENTIAL 子证据的 TOOL 根事件。';
COMMENT ON COLUMN mcp_operation_audit.invocation_id IS
  '固定 Runtime invocation identity；legacy 记录为空。';
COMMENT ON COLUMN mcp_operation_audit.agent_publication_id IS
  '本次调用冻结的 Agent Publication ID；legacy 记录为空。';
COMMENT ON COLUMN mcp_operation_audit.application_publication_id IS
  '本次调用冻结的业务应用 Publication ID；legacy 记录为空。';
COMMENT ON COLUMN mcp_operation_audit.tool_schema_hash IS
  '本次调用冻结的 Tool 公共 Schema SHA-256。';
COMMENT ON COLUMN mcp_operation_audit.authorization_decision IS
  'ALLOW 或 DENY 等通用授权决策；非授权事件为空。';
COMMENT ON COLUMN mcp_operation_audit.authorization_reason IS
  '授权决策的有界稳定原因码或摘要。';
COMMENT ON COLUMN mcp_operation_audit.resource_code IS
  '受治理 Resource 的稳定代码。';
COMMENT ON COLUMN mcp_operation_audit.resource_deployment_id IS
  '本次调用固定的 Resource Deployment ID。';
COMMENT ON COLUMN mcp_operation_audit.resource_revision_id IS
  '本次调用固定的 Resource Revision ID。';
COMMENT ON COLUMN mcp_operation_audit.resource_placement IS
  '本次调用实际选择的 cloud 或 edge placement。';
COMMENT ON COLUMN mcp_operation_audit.target_type IS
  '通用业务目标类型。';
COMMENT ON COLUMN mcp_operation_audit.target_id IS
  '通用业务目标稳定 ID。';
COMMENT ON COLUMN mcp_operation_audit.target_name IS
  '通用业务目标有界展示名称。';
COMMENT ON COLUMN mcp_operation_audit.business_request_json IS
  '有界业务请求 JSON；认证材料由共享序列化器结构性拒绝。';
COMMENT ON COLUMN mcp_operation_audit.business_response_json IS
  '有界业务响应 JSON；认证材料由共享序列化器结构性拒绝。';
COMMENT ON COLUMN mcp_operation_audit.request_truncated IS
  '业务请求是否因大小边界被截断。';
COMMENT ON COLUMN mcp_operation_audit.response_truncated IS
  '业务响应是否因大小边界被截断。';
COMMENT ON COLUMN mcp_operation_audit.payload_digest IS
  '截断前规范业务载荷的 SHA-256；无载荷时为空。';
COMMENT ON COLUMN mcp_operation_audit.legacy_link_status IS
  '历史精确关联状态；LEGACY_UNLINKED 表示明确未猜测补链。';
COMMENT ON COLUMN mcp_operation_audit.completed_at IS
  '终态事件完成时间；STARTED 事件为空。';
