-- Freeze the closed text-v1/text-v2 format policy across publications, Jobs,
-- immutable file versions, transfers, and commit intents. Existing rows remain
-- text-v1/TXT and their immutable JSON/hash payloads are not rewritten.
-- migration: sqlite-foreign-keys-off

ALTER TABLE business_application_revision
  ADD COLUMN file_format_policy_version TEXT NOT NULL DEFAULT 'text-v1'
  CHECK (file_format_policy_version IN ('text-v1', 'text-v2'));

ALTER TABLE business_application_publication
  ADD COLUMN file_format_policy_version TEXT NOT NULL DEFAULT 'text-v1'
  CHECK (file_format_policy_version IN ('text-v1', 'text-v2'));

ALTER TABLE agent_job_file_request
  ADD COLUMN file_format_policy_version TEXT NOT NULL DEFAULT 'text-v1'
  CHECK (file_format_policy_version IN ('text-v1', 'text-v2'));

ALTER TABLE managed_file
  ADD COLUMN format_code TEXT NOT NULL DEFAULT 'TXT'
  CHECK (format_code IN ('TXT', 'LOG', 'MARKDOWN'));

ALTER TABLE managed_file_version
  ADD COLUMN format_code TEXT NOT NULL DEFAULT 'TXT'
  CHECK (format_code IN ('TXT', 'LOG', 'MARKDOWN'));

ALTER TABLE agent_job_file_snapshot_item
  ADD COLUMN format_code TEXT NOT NULL DEFAULT 'TXT'
  CHECK (format_code IN ('TXT', 'LOG', 'MARKDOWN'));

ALTER TABLE file_materialization_transfer
  ADD COLUMN format_code TEXT NOT NULL DEFAULT 'TXT'
  CHECK (format_code IN ('TXT', 'LOG', 'MARKDOWN'));

ALTER TABLE file_commit_intent
  ADD COLUMN file_format_policy_version TEXT NOT NULL DEFAULT 'text-v1'
  CHECK (file_format_policy_version IN ('text-v1', 'text-v2'));

ALTER TABLE file_commit_intent
  ADD COLUMN format_code TEXT NOT NULL DEFAULT 'TXT'
  CHECK (format_code IN ('TXT', 'MARKDOWN'));

-- Runtime protocol 1.3 carries the frozen file policy and per-entry format
-- matrix. SQLite requires a bounded table rebuild to widen the CHECK.
-- sqlite-only
CREATE TABLE agent_job_protocol_v13 (
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
    CHECK (agent_runtime_protocol_version IN ('1.0', '1.1', '1.2', '1.3')),
  input_message_id TEXT REFERENCES agent_message(id),
  task_workspace_id TEXT REFERENCES task_workspace(id)
);

-- sqlite-only
INSERT INTO agent_job_protocol_v13 (
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
  agent_runtime_protocol_version, input_message_id, task_workspace_id
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
  agent_runtime_protocol_version, input_message_id, task_workspace_id
FROM agent_job;

-- sqlite-only
DROP TABLE agent_job;

-- sqlite-only
ALTER TABLE agent_job_protocol_v13 RENAME TO agent_job;

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
  WHERE status IN ('RUNNING', 'RETRY_WAIT');
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
CREATE INDEX idx_agent_job_task_workspace
  ON agent_job(task_workspace_id, created_at);

-- postgres-only
ALTER TABLE agent_job
  DROP CONSTRAINT agent_job_agent_runtime_protocol_version_check;

-- postgres-only
ALTER TABLE agent_job
  ADD CONSTRAINT agent_job_agent_runtime_protocol_version_check
  CHECK (agent_runtime_protocol_version IN ('1.0', '1.1', '1.2', '1.3'));

-- SQLite cannot replace the schema-version CHECK constraint in place.
-- sqlite-only
CREATE TABLE agent_job_file_snapshot_schema_v3 (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE REFERENCES agent_job(id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL REFERENCES task_workspace(id),
  tenant_id TEXT NOT NULL,
  principal_user_id TEXT NOT NULL,
  business_application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  retention_period TEXT NOT NULL
    CHECK (retention_period IN ('DAY', 'WEEK', 'MONTH')),
  schema_version INTEGER NOT NULL DEFAULT 3 CHECK (schema_version IN (1, 2, 3)),
  file_format_policy_version TEXT NOT NULL DEFAULT 'text-v1'
    CHECK (file_format_policy_version IN ('text-v1', 'text-v2')),
  manifest_hash TEXT NOT NULL CHECK (length(manifest_hash) = 64),
  created_at TEXT NOT NULL
);

-- sqlite-only
INSERT INTO agent_job_file_snapshot_schema_v3 (
  id, job_id, workspace_id, tenant_id, principal_user_id,
  business_application_publication_id, retention_period, schema_version,
  file_format_policy_version, manifest_hash, created_at
)
SELECT
  id, job_id, workspace_id, tenant_id, principal_user_id,
  business_application_publication_id, retention_period, schema_version,
  'text-v1', manifest_hash, created_at
FROM agent_job_file_snapshot;

-- sqlite-only
DROP TABLE agent_job_file_snapshot;

-- sqlite-only
ALTER TABLE agent_job_file_snapshot_schema_v3 RENAME TO agent_job_file_snapshot;

-- sqlite-only
CREATE INDEX idx_agent_job_file_snapshot_workspace
  ON agent_job_file_snapshot(workspace_id, created_at);

-- postgres-only
ALTER TABLE agent_job_file_snapshot
  DROP CONSTRAINT agent_job_file_snapshot_schema_version_check;

-- postgres-only
ALTER TABLE agent_job_file_snapshot
  ALTER COLUMN schema_version SET DEFAULT 3;

-- postgres-only
ALTER TABLE agent_job_file_snapshot
  ADD CONSTRAINT agent_job_file_snapshot_schema_version_check
  CHECK (schema_version IN (1, 2, 3));

-- postgres-only
ALTER TABLE agent_job_file_snapshot
  ADD COLUMN file_format_policy_version TEXT NOT NULL DEFAULT 'text-v1'
  CHECK (file_format_policy_version IN ('text-v1', 'text-v2'));

-- postgres-only
COMMENT ON COLUMN business_application_revision.file_format_policy_version IS
  '草稿修订选择的代码注册文件格式策略；发布时冻结';

-- postgres-only
COMMENT ON COLUMN business_application_publication.file_format_policy_version IS
  'Publication冻结的代码注册文件格式策略；历史记录为text-v1';

-- postgres-only
COMMENT ON COLUMN agent_job_file_request.file_format_policy_version IS
  'Job创建时冻结的Publication文件格式策略版本';

-- postgres-only
COMMENT ON COLUMN managed_file.format_code IS
  '稳定逻辑文件格式代码，禁止跨版本改名改变';

-- postgres-only
COMMENT ON COLUMN managed_file_version.format_code IS
  '不可变精确版本的规范化文件格式代码';

-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot.file_format_policy_version IS
  'Job Manifest冻结的文件格式策略版本';

-- postgres-only
COMMENT ON COLUMN agent_job_file_snapshot_item.format_code IS
  'Job Manifest条目的规范化文件格式代码';

-- postgres-only
COMMENT ON COLUMN file_materialization_transfer.format_code IS
  '流式物化传输绑定的精确文本格式代码';

-- postgres-only
COMMENT ON COLUMN file_commit_intent.file_format_policy_version IS
  'Commit Intent冻结的Job文件格式策略版本';

-- postgres-only
COMMENT ON COLUMN file_commit_intent.format_code IS
  'Commit Intent绑定的可写文本格式代码';
