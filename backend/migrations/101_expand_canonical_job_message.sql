-- Expand-only migration for canonical Session/Job/Message facts.
-- It preserves compatibility columns but makes them nullable so the cutover
-- application can stop writing them. Data reconciliation remains a separately
-- authorized backfill.
-- migration: sqlite-foreign-keys-off

-- sqlite-only
CREATE TABLE agent_session_expand_new (
  id TEXT PRIMARY KEY,
  dingding_conversation_id TEXT,
  dingding_user_id TEXT,
  source TEXT,
  project_code TEXT NOT NULL DEFAULT 'default',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  source_channel TEXT NOT NULL DEFAULT 'dingding',
  source_connector_id TEXT NOT NULL DEFAULT 'connector-dingtalk-enterprise-default',
  external_conversation_id TEXT NOT NULL DEFAULT '',
  requester_id TEXT NOT NULL DEFAULT '',
  requester_display_name TEXT NOT NULL DEFAULT '',
  routing_context_json TEXT NOT NULL DEFAULT '{}',
  reply_route_json TEXT NOT NULL DEFAULT '{"type":"dingtalk_conversation"}',
  session_key TEXT NOT NULL DEFAULT '',
  conversation_type TEXT NOT NULL DEFAULT 'direct',
  bot_identity TEXT NOT NULL DEFAULT '',
  summary_text TEXT NOT NULL DEFAULT '',
  summary_through_sequence INTEGER NOT NULL DEFAULT 0,
  summary_version INTEGER NOT NULL DEFAULT 0,
  message_sequence INTEGER NOT NULL DEFAULT 0,
  last_message_at TEXT,
  external_identity_id TEXT,
  business_application_id TEXT,
  business_application_code TEXT NOT NULL DEFAULT '',
  conversation_mode TEXT NOT NULL DEFAULT 'legacy',
  recent_message_limit INTEGER,
  session_policy_json TEXT NOT NULL DEFAULT '{}',
  application_publication_id TEXT,
  execution_scope_hash TEXT,
  isolation_key_version INTEGER NOT NULL DEFAULT 2,
  history_read_only INTEGER NOT NULL DEFAULT 0
);

-- sqlite-only
INSERT INTO agent_session_expand_new (
  id, dingding_conversation_id, dingding_user_id, source, project_code,
  created_at, updated_at, source_channel, source_connector_id,
  external_conversation_id, requester_id, requester_display_name,
  routing_context_json, reply_route_json, session_key, conversation_type,
  bot_identity, summary_text, summary_through_sequence, summary_version,
  message_sequence, last_message_at, external_identity_id,
  business_application_id, business_application_code, conversation_mode,
  recent_message_limit, session_policy_json, application_publication_id,
  execution_scope_hash, isolation_key_version, history_read_only
)
SELECT
  id, dingding_conversation_id, dingding_user_id, source, project_code,
  created_at, updated_at, source_channel, source_connector_id,
  external_conversation_id, requester_id, requester_display_name,
  routing_context_json, reply_route_json, session_key, conversation_type,
  bot_identity, summary_text, summary_through_sequence, summary_version,
  message_sequence, last_message_at, external_identity_id,
  business_application_id, business_application_code, conversation_mode,
  recent_message_limit, session_policy_json, application_publication_id,
  execution_scope_hash, isolation_key_version, history_read_only
FROM agent_session;

-- sqlite-only
DROP TABLE agent_session;

-- sqlite-only
ALTER TABLE agent_session_expand_new RENAME TO agent_session;

-- sqlite-only
CREATE UNIQUE INDEX idx_agent_session_key ON agent_session(session_key);

-- sqlite-only
CREATE INDEX idx_agent_session_updated ON agent_session(updated_at, id);

-- sqlite-only
CREATE INDEX idx_agent_session_requester_updated
  ON agent_session(requester_id, updated_at);

-- sqlite-only
CREATE INDEX idx_agent_session_business_application
  ON agent_session(business_application_id, updated_at);

-- sqlite-only
CREATE INDEX idx_agent_session_publication_scope
  ON agent_session(application_publication_id, execution_scope_hash, updated_at);

-- sqlite-only
CREATE TABLE agent_job_expand_new (
  id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES agent_session(id),
  idempotency_key TEXT NOT NULL UNIQUE,
  user_id TEXT,
  project_code TEXT NOT NULL DEFAULT 'default',
  source TEXT,
  user_message TEXT,
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
  agent_runtime_protocol_version TEXT NOT NULL DEFAULT '1.0'
    CHECK (agent_runtime_protocol_version = '1.0'),
  input_message_id TEXT REFERENCES agent_message(id)
);

-- sqlite-only
INSERT INTO agent_job_expand_new (
  id, session_id, idempotency_key, user_id, project_code, source, user_message,
  status, priority, retry_count, max_retry_count, result, error_message,
  created_at, started_at, finished_at, locked_at, locked_by, source_channel,
  source_connector_id, external_event_id, requester_id, routing_context_json,
  reply_route_json, internal_user_id, external_identity_id, agent_definition_id,
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
  id, session_id, idempotency_key, user_id, project_code, source, user_message,
  status, priority, retry_count, max_retry_count, result, error_message,
  created_at, started_at, finished_at, locked_at, locked_by, source_channel,
  source_connector_id, external_event_id, requester_id, routing_context_json,
  reply_route_json, internal_user_id, external_identity_id, agent_definition_id,
  agent_publication_id, agent_revision, agent_config_hash, webhook_event_id,
  webhook_trigger_id, webhook_trigger_publication_id, last_error_code,
  last_error_at, next_retry_at, business_application_id,
  business_application_code, business_application_publication_id,
  business_application_deployment_id, business_application_route_id,
  business_application_config_hash, business_application_runtime_status,
  business_application_route_decision_json, execution_policy_json,
  execution_policy_tool_call_count, execution_policy_exhausted,
  model_runtime_provenance_json, agent_runtime_kind,
  agent_runtime_protocol_version, NULL
FROM agent_job;

-- sqlite-only
DROP TABLE agent_job;

-- sqlite-only
ALTER TABLE agent_job_expand_new RENAME TO agent_job;

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
  WHERE result IS NULL;

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
CREATE UNIQUE INDEX idx_agent_message_job_user
  ON agent_message(job_id)
  WHERE job_id IS NOT NULL AND role = 'user';

-- postgres-only
ALTER TABLE agent_session ALTER COLUMN dingding_conversation_id DROP NOT NULL;

-- postgres-only
ALTER TABLE agent_session ALTER COLUMN dingding_user_id DROP NOT NULL;

-- postgres-only
ALTER TABLE agent_session ALTER COLUMN source DROP DEFAULT;

-- postgres-only
ALTER TABLE agent_session ALTER COLUMN source DROP NOT NULL;

-- postgres-only
ALTER TABLE agent_job ALTER COLUMN user_id DROP NOT NULL;

-- postgres-only
ALTER TABLE agent_job ALTER COLUMN source DROP DEFAULT;

-- postgres-only
ALTER TABLE agent_job ALTER COLUMN source DROP NOT NULL;

-- postgres-only
ALTER TABLE agent_job ALTER COLUMN user_message DROP NOT NULL;

-- postgres-only
ALTER TABLE agent_job ADD COLUMN input_message_id TEXT;

-- postgres-only
ALTER TABLE agent_job
  ADD CONSTRAINT fk_agent_job_input_message
  FOREIGN KEY (input_message_id) REFERENCES agent_message(id) NOT VALID;

-- postgres-only
CREATE UNIQUE INDEX idx_agent_job_input_message
  ON agent_job(input_message_id)
  WHERE input_message_id IS NOT NULL;

-- postgres-only
CREATE UNIQUE INDEX idx_agent_message_job_user
  ON agent_message(job_id)
  WHERE job_id IS NOT NULL AND role = 'user';

-- postgres-only
COMMENT ON COLUMN agent_job.input_message_id IS
  'Job 的不可变输入所引用的规范有序 role=user agent_message。仅无法修复的只读历史允许 NULL。';
