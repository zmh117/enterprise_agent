-- Add the durable, provider-neutral confirmation boundary used by business
-- MCP mutations. No existing Job, Publication, or audit history is rewritten.
-- migration: sqlite-foreign-keys-off

-- Expand the closed publication domain before a DingTalk MCP Tool can be
-- selected. Existing immutable publication rows remain byte-for-byte equal.

-- sqlite-only
ALTER TABLE agent_publication_mcp_tool
  RENAME TO agent_publication_mcp_tool_before_dingtalk_mcp;

-- sqlite-only
CREATE TABLE agent_publication_mcp_tool (
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL
    CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service', 'dingtalk-mcp')),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  model_description TEXT NOT NULL DEFAULT '',
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(agent_publication_id, tool_identifier),
  UNIQUE(agent_publication_id, selection_order),
  UNIQUE(agent_publication_id, server_code, tool_identifier)
);

-- sqlite-only
INSERT INTO agent_publication_mcp_tool
  (agent_publication_id, server_code, tool_identifier, schema_hash,
   model_description, selection_order, created_at)
SELECT agent_publication_id, server_code, tool_identifier, schema_hash,
       model_description, selection_order, created_at
  FROM agent_publication_mcp_tool_before_dingtalk_mcp;

-- sqlite-only
ALTER TABLE business_application_revision_mcp_tool
  RENAME TO business_application_revision_mcp_tool_before_dingtalk_mcp;

-- sqlite-only
CREATE TABLE business_application_revision_mcp_tool (
  application_revision_id TEXT NOT NULL REFERENCES business_application_revision(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL
    CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service', 'dingtalk-mcp')),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(application_revision_id, tool_identifier),
  UNIQUE(application_revision_id, selection_order),
  FOREIGN KEY(agent_publication_id, server_code, tool_identifier)
    REFERENCES agent_publication_mcp_tool(
      agent_publication_id, server_code, tool_identifier
    )
);

-- sqlite-only
INSERT INTO business_application_revision_mcp_tool
  (application_revision_id, agent_publication_id, server_code,
   tool_identifier, schema_hash, selection_order, created_at)
SELECT application_revision_id, agent_publication_id, server_code,
       tool_identifier, schema_hash, selection_order, created_at
  FROM business_application_revision_mcp_tool_before_dingtalk_mcp;

-- sqlite-only
ALTER TABLE business_application_publication_mcp_tool
  RENAME TO business_application_publication_mcp_tool_before_dingtalk_mcp;

-- sqlite-only
CREATE TABLE business_application_publication_mcp_tool (
  application_publication_id TEXT NOT NULL REFERENCES business_application_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  server_code TEXT NOT NULL
    CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service', 'dingtalk-mcp')),
  tool_identifier TEXT NOT NULL,
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  selection_order INTEGER NOT NULL DEFAULT 0 CHECK (selection_order >= 0),
  created_at TEXT NOT NULL,
  PRIMARY KEY(application_publication_id, tool_identifier),
  UNIQUE(application_publication_id, selection_order),
  FOREIGN KEY(agent_publication_id, server_code, tool_identifier)
    REFERENCES agent_publication_mcp_tool(
      agent_publication_id, server_code, tool_identifier
    )
);

-- sqlite-only
INSERT INTO business_application_publication_mcp_tool
  (application_publication_id, agent_publication_id, server_code,
   tool_identifier, schema_hash, selection_order, created_at)
SELECT application_publication_id, agent_publication_id, server_code,
       tool_identifier, schema_hash, selection_order, created_at
  FROM business_application_publication_mcp_tool_before_dingtalk_mcp;

-- sqlite-only
DROP TABLE business_application_revision_mcp_tool_before_dingtalk_mcp;

-- sqlite-only
DROP TABLE business_application_publication_mcp_tool_before_dingtalk_mcp;

-- sqlite-only
DROP TABLE agent_publication_mcp_tool_before_dingtalk_mcp;

-- postgres-only
ALTER TABLE agent_publication_mcp_tool
  DROP CONSTRAINT agent_publication_mcp_tool_server_code_check;

-- postgres-only
ALTER TABLE agent_publication_mcp_tool
  ADD CONSTRAINT agent_publication_mcp_tool_server_code_check
  CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service', 'dingtalk-mcp'));

-- postgres-only
ALTER TABLE business_application_revision_mcp_tool
  DROP CONSTRAINT business_application_revision_mcp_tool_server_code_check;

-- postgres-only
ALTER TABLE business_application_revision_mcp_tool
  ADD CONSTRAINT business_application_revision_mcp_tool_server_code_check
  CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service', 'dingtalk-mcp'));

-- postgres-only
ALTER TABLE business_application_publication_mcp_tool
  DROP CONSTRAINT business_application_publication_mcp_tool_server_code_check;

-- postgres-only
ALTER TABLE business_application_publication_mcp_tool
  ADD CONSTRAINT business_application_publication_mcp_tool_server_code_check
  CHECK (server_code IN ('tool-mcp', 'ones-mcp', 'file-service', 'dingtalk-mcp'));

CREATE TABLE external_action_intent (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  session_id TEXT NOT NULL REFERENCES agent_session(id),
  actor_user_id TEXT NOT NULL REFERENCES app_user(id),
  business_application_id TEXT NOT NULL REFERENCES business_application(id),
  agent_publication_id TEXT NOT NULL,
  application_publication_id TEXT NOT NULL,
  source_connector_id TEXT NOT NULL REFERENCES integration_connector(id),
  dingtalk_enterprise_id TEXT NOT NULL REFERENCES dingtalk_enterprise(id),
  target_external_subject_id TEXT NOT NULL CHECK (length(target_external_subject_id) > 0),
  target_union_id TEXT NOT NULL CHECK (length(target_union_id) > 0),
  server_code TEXT NOT NULL CHECK (length(server_code) BETWEEN 1 AND 64),
  tool_identifier TEXT NOT NULL CHECK (length(tool_identifier) BETWEEN 1 AND 128),
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  confirmation_policy TEXT NOT NULL CHECK (length(confirmation_policy) BETWEEN 1 AND 64),
  operation_code TEXT NOT NULL CHECK (length(operation_code) BETWEEN 1 AND 128),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision > 0),
  status TEXT NOT NULL CHECK (status IN (
    'PENDING_CONFIRMATION', 'APPROVED', 'EXECUTING', 'SUCCEEDED',
    'FAILED', 'FAILED_UNCERTAIN', 'REJECTED', 'EXPIRED'
  )),
  arguments_json TEXT NOT NULL CHECK (length(arguments_json) <= 16384),
  arguments_hash TEXT NOT NULL CHECK (length(arguments_hash) = 64),
  safe_summary_json TEXT NOT NULL CHECK (length(safe_summary_json) <= 4096),
  mcp_call_id TEXT NOT NULL CHECK (length(mcp_call_id) BETWEEN 1 AND 128),
  expires_at TEXT NOT NULL,
  approved_at TEXT,
  rejected_at TEXT,
  execution_claimed_by TEXT NOT NULL DEFAULT '' CHECK (length(execution_claimed_by) <= 128),
  execution_claim_expires_at TEXT,
  execution_attempts INTEGER NOT NULL DEFAULT 0 CHECK (execution_attempts >= 0),
  provider_request_id TEXT NOT NULL DEFAULT '' CHECK (length(provider_request_id) <= 256),
  result_json TEXT NOT NULL DEFAULT '{}' CHECK (length(result_json) <= 16384),
  last_error_code TEXT NOT NULL DEFAULT '' CHECK (length(last_error_code) <= 128),
  last_error_summary TEXT NOT NULL DEFAULT '' CHECK (length(last_error_summary) <= 500),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  completed_at TEXT,
  UNIQUE(job_id, tool_identifier, arguments_hash)
);

CREATE INDEX idx_external_action_intent_status_claim
  ON external_action_intent(status, execution_claim_expires_at, created_at);

CREATE INDEX idx_external_action_intent_actor_created
  ON external_action_intent(actor_user_id, created_at);

CREATE TABLE external_action_card_outbox (
  id TEXT PRIMARY KEY,
  action_intent_id TEXT NOT NULL REFERENCES external_action_intent(id),
  event_kind TEXT NOT NULL CHECK (event_kind IN ('CREATE', 'RESULT_UPDATE')),
  status TEXT NOT NULL CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'RETRY_WAIT', 'DEAD')),
  idempotency_key TEXT NOT NULL UNIQUE,
  payload_json TEXT NOT NULL CHECK (length(payload_json) <= 8192),
  attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
  next_attempt_at TEXT,
  claimed_by TEXT NOT NULL DEFAULT '' CHECK (length(claimed_by) <= 128),
  claim_expires_at TEXT,
  last_error_code TEXT NOT NULL DEFAULT '' CHECK (length(last_error_code) <= 128),
  last_error_summary TEXT NOT NULL DEFAULT '' CHECK (length(last_error_summary) <= 500),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX idx_external_action_card_outbox_claim
  ON external_action_card_outbox(status, next_attempt_at, claim_expires_at, created_at);

COMMENT ON TABLE external_action_intent IS
  '业务MCP mutation逐次确认与Provider执行的持久事实';
COMMENT ON COLUMN external_action_intent.id IS '外部操作意图ID';
COMMENT ON COLUMN external_action_intent.job_id IS '来源Job ID';
COMMENT ON COLUMN external_action_intent.session_id IS '来源会话ID';
COMMENT ON COLUMN external_action_intent.actor_user_id IS '发起操作的内部用户ID';
COMMENT ON COLUMN external_action_intent.business_application_id IS '来源业务应用ID';
COMMENT ON COLUMN external_action_intent.agent_publication_id IS '冻结的Agent发布ID';
COMMENT ON COLUMN external_action_intent.application_publication_id IS '冻结的业务应用发布ID';
COMMENT ON COLUMN external_action_intent.source_connector_id IS '来源钉钉Connector ID';
COMMENT ON COLUMN external_action_intent.dingtalk_enterprise_id IS '受治理钉钉企业ID';
COMMENT ON COLUMN external_action_intent.target_external_subject_id IS '卡片目标钉钉人员ID';
COMMENT ON COLUMN external_action_intent.target_union_id IS 'Provider待办目标Union ID';
COMMENT ON COLUMN external_action_intent.server_code IS '冻结的MCP Server代码';
COMMENT ON COLUMN external_action_intent.tool_identifier IS '冻结的MCP Tool标识';
COMMENT ON COLUMN external_action_intent.schema_hash IS '冻结的Tool输入Schema摘要';
COMMENT ON COLUMN external_action_intent.confirmation_policy IS '冻结的逐次确认策略';
COMMENT ON COLUMN external_action_intent.operation_code IS '代码注册的Provider操作代码';
COMMENT ON COLUMN external_action_intent.revision IS '确认意图修订号';
COMMENT ON COLUMN external_action_intent.status IS '确认与Provider执行状态';
COMMENT ON COLUMN external_action_intent.arguments_json IS
  '代码规范化且有界的业务参数，不得包含Provider凭据';
COMMENT ON COLUMN external_action_intent.arguments_hash IS '规范化业务参数摘要';
COMMENT ON COLUMN external_action_intent.safe_summary_json IS '卡片可展示的有界摘要';
COMMENT ON COLUMN external_action_intent.mcp_call_id IS '首次准备意图的MCP调用ID';
COMMENT ON COLUMN external_action_intent.expires_at IS '用户确认截止时间';
COMMENT ON COLUMN external_action_intent.approved_at IS '用户同意时间';
COMMENT ON COLUMN external_action_intent.rejected_at IS '用户拒绝时间';
COMMENT ON COLUMN external_action_intent.execution_claimed_by IS 'Provider执行Worker租约持有者';
COMMENT ON COLUMN external_action_intent.execution_claim_expires_at IS 'Provider执行租约截止时间';
COMMENT ON COLUMN external_action_intent.execution_attempts IS 'Provider执行领取次数';
COMMENT ON COLUMN external_action_intent.provider_request_id IS 'Provider返回的有界请求或资源ID';
COMMENT ON COLUMN external_action_intent.result_json IS 'Provider执行的有界安全结果';
COMMENT ON COLUMN external_action_intent.last_error_code IS '最近安全错误代码';
COMMENT ON COLUMN external_action_intent.last_error_summary IS '最近安全错误摘要';
COMMENT ON COLUMN external_action_intent.created_at IS '意图创建时间';
COMMENT ON COLUMN external_action_intent.updated_at IS '意图更新时间';
COMMENT ON COLUMN external_action_intent.completed_at IS '意图终态时间';
COMMENT ON TABLE external_action_card_outbox IS
  '互动确认卡创建与结果更新的持久Outbox';
COMMENT ON COLUMN external_action_card_outbox.id IS '卡片Outbox事件ID';
COMMENT ON COLUMN external_action_card_outbox.action_intent_id IS '关联外部操作意图ID';
COMMENT ON COLUMN external_action_card_outbox.event_kind IS '卡片创建或结果更新类型';
COMMENT ON COLUMN external_action_card_outbox.status IS '卡片Outbox投递状态';
COMMENT ON COLUMN external_action_card_outbox.idempotency_key IS '卡片投递幂等键';
COMMENT ON COLUMN external_action_card_outbox.payload_json IS '卡片投递有界安全载荷';
COMMENT ON COLUMN external_action_card_outbox.attempt_count IS '卡片投递尝试次数';
COMMENT ON COLUMN external_action_card_outbox.next_attempt_at IS '卡片下次重试时间';
COMMENT ON COLUMN external_action_card_outbox.claimed_by IS '卡片Worker租约持有者';
COMMENT ON COLUMN external_action_card_outbox.claim_expires_at IS '卡片Worker租约截止时间';
COMMENT ON COLUMN external_action_card_outbox.last_error_code IS '卡片最近安全错误代码';
COMMENT ON COLUMN external_action_card_outbox.last_error_summary IS '卡片最近安全错误摘要';
COMMENT ON COLUMN external_action_card_outbox.created_at IS 'Outbox创建时间';
COMMENT ON COLUMN external_action_card_outbox.updated_at IS 'Outbox更新时间';
