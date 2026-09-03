-- migration: sqlite-foreign-keys-off
-- Add proposal-chain and single Provider-attempt facts. SQLite rebuilds the
-- table so the status CHECK can accept the additive SUPERSEDED terminal state.

-- sqlite-only
PRAGMA legacy_alter_table = ON;

-- sqlite-only
ALTER TABLE external_action_intent RENAME TO external_action_intent_v128;

-- sqlite-only
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
    'FAILED', 'FAILED_UNCERTAIN', 'REJECTED', 'EXPIRED', 'SUPERSEDED'
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
  confirmation_channel_code TEXT NOT NULL DEFAULT 'dingtalk'
    CHECK (confirmation_channel_code = 'dingtalk'),
  execution_provider_code TEXT NOT NULL DEFAULT 'dingtalk'
    CHECK (execution_provider_code IN ('dingtalk', 'ones')),
  execution_external_identity_id TEXT REFERENCES user_external_identity(id),
  execution_scope_id TEXT NOT NULL DEFAULT '' CHECK (length(execution_scope_id) <= 128),
  target_resource_type TEXT NOT NULL DEFAULT '' CHECK (target_resource_type IN ('', 'task')),
  target_resource_id TEXT NOT NULL DEFAULT '' CHECK (length(target_resource_id) <= 128),
  precondition_json TEXT NOT NULL DEFAULT '{}' CHECK (length(precondition_json) <= 16384),
  precondition_hash TEXT NOT NULL DEFAULT '' CHECK (length(precondition_hash) IN (0, 64)),
  field_catalog_version TEXT NOT NULL DEFAULT '' CHECK (length(field_catalog_version) <= 80),
  field_catalog_hash TEXT NOT NULL DEFAULT '' CHECK (length(field_catalog_hash) IN (0, 64)),
  intent_fingerprint TEXT NOT NULL DEFAULT '' CHECK (length(intent_fingerprint) IN (0, 64)),
  confirmation_summary_json TEXT NOT NULL DEFAULT '{}' CHECK (length(confirmation_summary_json) <= 16384),
  proposal_chain_id TEXT NOT NULL CHECK (length(proposal_chain_id) BETWEEN 1 AND 128),
  supersedes_intent_id TEXT REFERENCES external_action_intent(id),
  superseded_by_intent_id TEXT REFERENCES external_action_intent(id),
  superseded_at TEXT,
  provider_attempt_status TEXT NOT NULL DEFAULT ''
    CHECK (provider_attempt_status IN ('', 'STARTED')),
  provider_attempt_started_at TEXT,
  provider_request_hash TEXT NOT NULL DEFAULT '' CHECK (length(provider_request_hash) IN (0, 64)),
  provider_catalog_hash TEXT NOT NULL DEFAULT '' CHECK (length(provider_catalog_hash) IN (0, 64)),
  UNIQUE(job_id, tool_identifier, arguments_hash)
);

-- sqlite-only
INSERT INTO external_action_intent (
  id, job_id, session_id, actor_user_id, business_application_id,
  agent_publication_id, application_publication_id, source_connector_id,
  dingtalk_enterprise_id, target_external_subject_id, target_union_id,
  server_code, tool_identifier, schema_hash, confirmation_policy, operation_code,
  revision, status, arguments_json, arguments_hash, safe_summary_json,
  mcp_call_id, expires_at, approved_at, rejected_at, execution_claimed_by,
  execution_claim_expires_at, execution_attempts, provider_request_id,
  result_json, last_error_code, last_error_summary, created_at, updated_at,
  completed_at, confirmation_channel_code, execution_provider_code,
  execution_external_identity_id, execution_scope_id, target_resource_type,
  target_resource_id, precondition_json, precondition_hash,
  field_catalog_version, field_catalog_hash, intent_fingerprint,
  confirmation_summary_json, proposal_chain_id
)
SELECT
  id, job_id, session_id, actor_user_id, business_application_id,
  agent_publication_id, application_publication_id, source_connector_id,
  dingtalk_enterprise_id, target_external_subject_id, target_union_id,
  server_code, tool_identifier, schema_hash, confirmation_policy, operation_code,
  revision, status, arguments_json, arguments_hash, safe_summary_json,
  mcp_call_id, expires_at, approved_at, rejected_at, execution_claimed_by,
  execution_claim_expires_at, execution_attempts, provider_request_id,
  result_json, last_error_code, last_error_summary, created_at, updated_at,
  completed_at, confirmation_channel_code, execution_provider_code,
  execution_external_identity_id, execution_scope_id, target_resource_type,
  target_resource_id, precondition_json, precondition_hash,
  field_catalog_version, field_catalog_hash, intent_fingerprint,
  confirmation_summary_json, id
FROM external_action_intent_v128;

-- sqlite-only
DROP TABLE external_action_intent_v128;

-- sqlite-only
PRAGMA legacy_alter_table = OFF;

-- postgres-only
ALTER TABLE external_action_intent
  DROP CONSTRAINT external_action_intent_status_check;

-- postgres-only
ALTER TABLE external_action_intent
  ADD CONSTRAINT external_action_intent_status_check CHECK (status IN (
    'PENDING_CONFIRMATION', 'APPROVED', 'EXECUTING', 'SUCCEEDED',
    'FAILED', 'FAILED_UNCERTAIN', 'REJECTED', 'EXPIRED', 'SUPERSEDED'
  ));

-- postgres-only
ALTER TABLE external_action_intent
  ADD COLUMN proposal_chain_id TEXT NOT NULL DEFAULT '' CHECK (length(proposal_chain_id) <= 128);

-- postgres-only
UPDATE external_action_intent SET proposal_chain_id = id WHERE proposal_chain_id = '';

-- postgres-only
ALTER TABLE external_action_intent
  ADD CONSTRAINT external_action_intent_proposal_chain_nonempty CHECK (length(proposal_chain_id) > 0);

-- postgres-only
ALTER TABLE external_action_intent
  ADD COLUMN supersedes_intent_id TEXT REFERENCES external_action_intent(id);

-- postgres-only
ALTER TABLE external_action_intent
  ADD COLUMN superseded_by_intent_id TEXT REFERENCES external_action_intent(id);

-- postgres-only
ALTER TABLE external_action_intent ADD COLUMN superseded_at TEXT;

-- postgres-only
ALTER TABLE external_action_intent
  ADD COLUMN provider_attempt_status TEXT NOT NULL DEFAULT ''
    CHECK (provider_attempt_status IN ('', 'STARTED'));

-- postgres-only
ALTER TABLE external_action_intent ADD COLUMN provider_attempt_started_at TEXT;

-- postgres-only
ALTER TABLE external_action_intent
  ADD COLUMN provider_request_hash TEXT NOT NULL DEFAULT ''
    CHECK (length(provider_request_hash) IN (0, 64));

-- postgres-only
ALTER TABLE external_action_intent
  ADD COLUMN provider_catalog_hash TEXT NOT NULL DEFAULT ''
    CHECK (length(provider_catalog_hash) IN (0, 64));

-- sqlite-only
CREATE INDEX idx_external_action_intent_status_claim
  ON external_action_intent(status, execution_claim_expires_at, created_at);

-- sqlite-only
CREATE INDEX idx_external_action_intent_actor_created
  ON external_action_intent(actor_user_id, created_at);

-- sqlite-only
CREATE UNIQUE INDEX uq_external_action_intent_fingerprint
  ON external_action_intent(intent_fingerprint) WHERE intent_fingerprint <> '';

-- sqlite-only
CREATE INDEX idx_external_action_intent_provider_claim
  ON external_action_intent(execution_provider_code, status,
                            execution_claim_expires_at, created_at);

CREATE UNIQUE INDEX uq_external_action_intent_mcp_call
  ON external_action_intent(job_id, tool_identifier, mcp_call_id)
  WHERE operation_code = 'ones.task.create';

CREATE INDEX idx_external_action_intent_proposal_chain
  ON external_action_intent(proposal_chain_id, created_at);

CREATE UNIQUE INDEX uq_external_action_intent_supersedes
  ON external_action_intent(supersedes_intent_id)
  WHERE supersedes_intent_id IS NOT NULL;

COMMENT ON COLUMN external_action_intent.proposal_chain_id IS
  '显式缺陷创建提案链ID，既有记录以自身Intent ID回填';
COMMENT ON COLUMN external_action_intent.supersedes_intent_id IS
  '本Intent显式替代的待确认创建Intent';
COMMENT ON COLUMN external_action_intent.superseded_by_intent_id IS
  '替代本Intent的新创建Intent';
COMMENT ON COLUMN external_action_intent.superseded_at IS
  '待确认Intent被原子替代的时间';
COMMENT ON COLUMN external_action_intent.provider_attempt_status IS
  '唯一Provider写入尝试状态，STARTED后禁止自动重放';
COMMENT ON COLUMN external_action_intent.provider_attempt_started_at IS
  'Provider写入尝试在外部调用前的持久开始时间';
COMMENT ON COLUMN external_action_intent.provider_request_hash IS
  '冻结Provider请求摘要';
COMMENT ON COLUMN external_action_intent.provider_catalog_hash IS
  'Provider尝试使用的字段目录摘要';
