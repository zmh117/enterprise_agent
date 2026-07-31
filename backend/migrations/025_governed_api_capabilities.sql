CREATE TABLE IF NOT EXISTS api_connection (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  provider TEXT NOT NULL CHECK (provider = 'ones'),
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled', 'archived')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_authentication_profile (
  id TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL UNIQUE REFERENCES api_connection(id),
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled', 'archived')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_connection_draft (
  id TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL UNIQUE REFERENCES api_connection(id),
  draft_revision INTEGER NOT NULL DEFAULT 1 CHECK (draft_revision >= 1),
  origin_scheme TEXT NOT NULL CHECK (origin_scheme IN ('https', 'http')),
  origin_host TEXT NOT NULL,
  origin_port INTEGER NOT NULL CHECK (origin_port BETWEEN 1 AND 65535),
  allow_insecure_local_http INTEGER NOT NULL DEFAULT 0
    CHECK (allow_insecure_local_http IN (0, 1)),
  connect_timeout_ms INTEGER NOT NULL DEFAULT 3000
    CHECK (connect_timeout_ms BETWEEN 100 AND 30000),
  read_timeout_ms INTEGER NOT NULL DEFAULT 10000
    CHECK (read_timeout_ms BETWEEN 100 AND 60000),
  max_response_bytes INTEGER NOT NULL DEFAULT 1048576
    CHECK (max_response_bytes BETWEEN 1024 AND 5242880),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'VERIFIED')),
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (length(origin_host) > 0),
  CHECK (origin_host NOT LIKE '%/%'),
  CHECK (origin_host NOT LIKE '%@%')
);

CREATE TABLE IF NOT EXISTS api_authentication_profile_draft (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL UNIQUE REFERENCES api_authentication_profile(id),
  draft_revision INTEGER NOT NULL DEFAULT 1 CHECK (draft_revision >= 1),
  config_json TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'VERIFIED')),
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_connection_verification (
  id TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL REFERENCES api_connection(id),
  connection_draft_id TEXT REFERENCES api_connection_draft(id) ON DELETE SET NULL,
  connection_draft_revision INTEGER NOT NULL
    CHECK (connection_draft_revision >= 1),
  profile_draft_id TEXT
    REFERENCES api_authentication_profile_draft(id) ON DELETE SET NULL,
  profile_draft_revision INTEGER NOT NULL CHECK (profile_draft_revision >= 1),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL CHECK (status IN ('PASSED', 'FAILED')),
  checks_json TEXT NOT NULL DEFAULT '{}',
  safe_error_summary TEXT NOT NULL DEFAULT '',
  verified_by TEXT NOT NULL,
  verified_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_authentication_profile_revision (
  id TEXT PRIMARY KEY,
  profile_id TEXT NOT NULL REFERENCES api_authentication_profile(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  schema_version INTEGER NOT NULL DEFAULT 1 CHECK (schema_version = 1),
  config_json TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL DEFAULT 'PUBLISHED'
    CHECK (status IN ('PUBLISHED', 'DISABLED', 'ARCHIVED')),
  published_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  disabled_by TEXT NOT NULL DEFAULT '',
  disabled_at TEXT,
  archived_by TEXT NOT NULL DEFAULT '',
  archived_at TEXT,
  UNIQUE(profile_id, revision),
  UNIQUE(profile_id, id)
);

CREATE TABLE IF NOT EXISTS api_connection_revision (
  id TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL REFERENCES api_connection(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  schema_version INTEGER NOT NULL DEFAULT 1 CHECK (schema_version = 1),
  origin_scheme TEXT NOT NULL CHECK (origin_scheme IN ('https', 'http')),
  origin_host TEXT NOT NULL,
  origin_port INTEGER NOT NULL CHECK (origin_port BETWEEN 1 AND 65535),
  allow_insecure_local_http INTEGER NOT NULL DEFAULT 0
    CHECK (allow_insecure_local_http IN (0, 1)),
  connect_timeout_ms INTEGER NOT NULL CHECK (connect_timeout_ms > 0),
  read_timeout_ms INTEGER NOT NULL CHECK (read_timeout_ms > 0),
  max_response_bytes INTEGER NOT NULL CHECK (max_response_bytes >= 1024),
  authentication_profile_revision_id TEXT NOT NULL
    REFERENCES api_authentication_profile_revision(id),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  verification_id TEXT NOT NULL REFERENCES api_connection_verification(id),
  status TEXT NOT NULL DEFAULT 'PUBLISHED'
    CHECK (status IN ('PUBLISHED', 'DISABLED', 'ARCHIVED')),
  published_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  disabled_by TEXT NOT NULL DEFAULT '',
  disabled_at TEXT,
  archived_by TEXT NOT NULL DEFAULT '',
  archived_at TEXT,
  UNIQUE(connection_id, revision),
  UNIQUE(connection_id, id)
);

CREATE INDEX IF NOT EXISTS idx_api_connection_revision_status
  ON api_connection_revision(connection_id, status, revision);

CREATE TABLE IF NOT EXISTS api_capability (
  id TEXT PRIMARY KEY,
  identifier TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled', 'archived')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (length(identifier) BETWEEN 18 AND 128),
  CHECK (substr(identifier, 1, 5) = 'cap__'),
  CHECK (lower(identifier) = identifier)
);

CREATE TABLE IF NOT EXISTS api_handler (
  id TEXT PRIMARY KEY,
  capability_id TEXT NOT NULL UNIQUE REFERENCES api_capability(id),
  executor_id TEXT NOT NULL DEFAULT 'http-json-v1'
    CHECK (executor_id = 'http-json-v1'),
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled', 'archived')),
  created_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_capability_draft (
  id TEXT PRIMARY KEY,
  capability_id TEXT NOT NULL UNIQUE REFERENCES api_capability(id),
  handler_id TEXT NOT NULL UNIQUE REFERENCES api_handler(id),
  draft_revision INTEGER NOT NULL DEFAULT 1 CHECK (draft_revision >= 1),
  connection_revision_id TEXT NOT NULL REFERENCES api_connection_revision(id),
  authentication_profile_revision_id TEXT NOT NULL
    REFERENCES api_authentication_profile_revision(id),
  capability_json TEXT NOT NULL,
  handler_json TEXT NOT NULL,
  mapping_ast_json TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'VERIFIED')),
  created_by TEXT NOT NULL,
  updated_by TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_capability_verification (
  id TEXT PRIMARY KEY,
  capability_id TEXT NOT NULL REFERENCES api_capability(id),
  draft_id TEXT REFERENCES api_capability_draft(id) ON DELETE SET NULL,
  draft_revision INTEGER NOT NULL CHECK (draft_revision >= 1),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  external_identity_id TEXT NOT NULL REFERENCES user_external_identity(id),
  external_user_id TEXT NOT NULL,
  default_team_id TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('PASSED', 'FAILED')),
  result_summary_json TEXT NOT NULL DEFAULT '{}',
  result_hash TEXT NOT NULL DEFAULT '',
  verified_by TEXT NOT NULL REFERENCES app_user(id),
  verified_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_capability_revision (
  id TEXT PRIMARY KEY,
  capability_id TEXT NOT NULL REFERENCES api_capability(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  schema_version INTEGER NOT NULL DEFAULT 1 CHECK (schema_version = 1),
  identifier TEXT NOT NULL,
  name TEXT NOT NULL,
  description TEXT NOT NULL,
  operation_semantics TEXT NOT NULL CHECK (operation_semantics = 'QUERY'),
  data_classification TEXT NOT NULL
    CHECK (data_classification = 'INTERNAL'),
  input_schema_json TEXT NOT NULL,
  output_schema_json TEXT NOT NULL,
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  published_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  UNIQUE(capability_id, revision),
  UNIQUE(capability_id, id),
  UNIQUE(identifier, revision)
);

CREATE TABLE IF NOT EXISTS api_compiled_mapping_plan (
  id TEXT PRIMARY KEY,
  schema_version INTEGER NOT NULL DEFAULT 1 CHECK (schema_version = 1),
  ast_hash TEXT NOT NULL CHECK (length(ast_hash) = 64),
  plan_json TEXT NOT NULL,
  content_hash TEXT NOT NULL UNIQUE CHECK (length(content_hash) = 64),
  compiled_by TEXT NOT NULL,
  compiled_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS api_handler_revision (
  id TEXT PRIMARY KEY,
  handler_id TEXT NOT NULL REFERENCES api_handler(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  schema_version INTEGER NOT NULL DEFAULT 1 CHECK (schema_version = 1),
  executor_id TEXT NOT NULL CHECK (executor_id = 'http-json-v1'),
  connection_revision_id TEXT NOT NULL REFERENCES api_connection_revision(id),
  authentication_profile_revision_id TEXT NOT NULL
    REFERENCES api_authentication_profile_revision(id),
  method TEXT NOT NULL CHECK (method IN ('GET', 'POST')),
  relative_path TEXT NOT NULL,
  graphql_document TEXT NOT NULL DEFAULT '',
  mapping_plan_id TEXT NOT NULL REFERENCES api_compiled_mapping_plan(id),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  published_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  UNIQUE(handler_id, revision),
  UNIQUE(handler_id, id),
  CHECK (substr(relative_path, 1, 1) = '/'),
  CHECK (relative_path NOT LIKE '%://%'),
  CHECK (relative_path NOT LIKE '%@%')
);

CREATE TABLE IF NOT EXISTS api_capability_release (
  id TEXT PRIMARY KEY,
  capability_id TEXT NOT NULL REFERENCES api_capability(id),
  identifier TEXT NOT NULL,
  release_revision INTEGER NOT NULL CHECK (release_revision >= 1),
  capability_revision_id TEXT NOT NULL REFERENCES api_capability_revision(id),
  handler_revision_id TEXT NOT NULL REFERENCES api_handler_revision(id),
  connection_revision_id TEXT NOT NULL REFERENCES api_connection_revision(id),
  authentication_profile_revision_id TEXT NOT NULL
    REFERENCES api_authentication_profile_revision(id),
  mapping_plan_id TEXT NOT NULL REFERENCES api_compiled_mapping_plan(id),
  verification_id TEXT NOT NULL REFERENCES api_capability_verification(id),
  config_hash TEXT NOT NULL CHECK (length(config_hash) = 64),
  publication_idempotency_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'DEPRECATED', 'DISABLED', 'ARCHIVED')),
  release_note TEXT NOT NULL DEFAULT '',
  deprecation_reason TEXT NOT NULL DEFAULT '',
  replacement_release_id TEXT REFERENCES api_capability_release(id),
  published_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  status_updated_by TEXT NOT NULL DEFAULT '',
  status_updated_at TEXT,
  UNIQUE(capability_id, release_revision),
  UNIQUE(identifier, release_revision),
  CHECK (replacement_release_id IS NULL OR replacement_release_id != id)
);

CREATE INDEX IF NOT EXISTS idx_api_capability_release_catalog
  ON api_capability_release(status, identifier, release_revision);

ALTER TABLE business_application_revision
  ADD COLUMN api_capability_release_ids_json TEXT NOT NULL DEFAULT '[]';

CREATE TABLE IF NOT EXISTS external_api_credential (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_user(id),
  external_identity_id TEXT NOT NULL REFERENCES user_external_identity(id),
  provider TEXT NOT NULL CHECK (provider = 'ones'),
  connection_revision_id TEXT NOT NULL REFERENCES api_connection_revision(id),
  token_ciphertext TEXT NOT NULL,
  encryption_key_id TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ACTIVE'
    CHECK (status IN ('ACTIVE', 'INVALID', 'DISABLED')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  last_error_code TEXT NOT NULL DEFAULT '',
  verified_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_external_api_credential_current
  ON external_api_credential(user_id, provider)
  WHERE status IN ('ACTIVE', 'INVALID');

CREATE INDEX IF NOT EXISTS idx_external_api_credential_identity
  ON external_api_credential(external_identity_id, status);

CREATE TABLE IF NOT EXISTS external_api_verification_challenge (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_user(id),
  provider TEXT NOT NULL CHECK (provider = 'ones'),
  connection_revision_id TEXT NOT NULL REFERENCES api_connection_revision(id),
  external_user_id TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  team_ids_json TEXT NOT NULL,
  token_ciphertext TEXT NOT NULL,
  encryption_key_id TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PENDING'
    CHECK (status IN ('PENDING', 'CONSUMED', 'EXPIRED')),
  created_at TEXT NOT NULL,
  consumed_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_external_api_challenge_pending
  ON external_api_verification_challenge(user_id, provider)
  WHERE status = 'PENDING';

CREATE INDEX IF NOT EXISTS idx_external_api_challenge_expiry
  ON external_api_verification_challenge(status, expires_at);

CREATE TABLE IF NOT EXISTS agent_publication_api_capability (
  id TEXT PRIMARY KEY,
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  binding_order INTEGER NOT NULL CHECK (binding_order >= 0),
  identifier TEXT NOT NULL,
  capability_release_id TEXT NOT NULL REFERENCES api_capability_release(id),
  capability_revision_id TEXT NOT NULL REFERENCES api_capability_revision(id),
  handler_revision_id TEXT NOT NULL REFERENCES api_handler_revision(id),
  schema_hash TEXT NOT NULL CHECK (length(schema_hash) = 64),
  description TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(agent_publication_id, identifier),
  UNIQUE(agent_publication_id, capability_release_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_publication_api_release
  ON agent_publication_api_capability(capability_release_id, agent_publication_id);

CREATE TABLE IF NOT EXISTS business_application_publication_api_capability (
  id TEXT PRIMARY KEY,
  application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  binding_order INTEGER NOT NULL CHECK (binding_order >= 0),
  identifier TEXT NOT NULL,
  capability_release_id TEXT NOT NULL REFERENCES api_capability_release(id),
  created_at TEXT NOT NULL,
  UNIQUE(application_publication_id, identifier),
  UNIQUE(application_publication_id, capability_release_id)
);

CREATE INDEX IF NOT EXISTS idx_application_publication_api_release
  ON business_application_publication_api_capability(
    capability_release_id,
    application_publication_id
  );

CREATE TABLE IF NOT EXISTS agent_job_external_subject (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE REFERENCES agent_job(id),
  provider TEXT NOT NULL CHECK (provider = 'ones'),
  external_identity_id TEXT NOT NULL REFERENCES user_external_identity(id),
  external_user_id TEXT NOT NULL,
  default_team_id TEXT NOT NULL,
  binding_revision INTEGER NOT NULL CHECK (binding_revision >= 1),
  snapshot_hash TEXT NOT NULL CHECK (length(snapshot_hash) = 64),
  created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_tool_call_api_provenance (
  id TEXT PRIMARY KEY,
  tool_call_id TEXT NOT NULL UNIQUE REFERENCES agent_tool_call(id),
  user_id TEXT NOT NULL REFERENCES app_user(id),
  application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  capability_release_id TEXT NOT NULL REFERENCES api_capability_release(id),
  data_classification TEXT NOT NULL CHECK (data_classification = 'INTERNAL'),
  normalized_result_hash TEXT NOT NULL CHECK (length(normalized_result_hash) = 64),
  normalized_result_size INTEGER NOT NULL CHECK (normalized_result_size >= 0),
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tool_call_api_provenance_release
  ON agent_tool_call_api_provenance(capability_release_id, created_at);

CREATE TABLE IF NOT EXISTS agent_tool_call_http_attempt (
  id TEXT PRIMARY KEY,
  tool_call_id TEXT NOT NULL REFERENCES agent_tool_call(id),
  job_id TEXT NOT NULL REFERENCES agent_job(id),
  capability_release_id TEXT NOT NULL REFERENCES api_capability_release(id),
  correlation_id TEXT NOT NULL,
  attempt_no INTEGER NOT NULL CHECK (attempt_no BETWEEN 1 AND 3),
  status_class TEXT NOT NULL,
  http_status INTEGER,
  duration_ms INTEGER NOT NULL DEFAULT 0 CHECK (duration_ms >= 0),
  response_size INTEGER NOT NULL DEFAULT 0 CHECK (response_size >= 0),
  request_hash TEXT NOT NULL DEFAULT '',
  response_hash TEXT NOT NULL DEFAULT '',
  safe_error_code TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(tool_call_id, attempt_no),
  CHECK (http_status IS NULL OR http_status BETWEEN 100 AND 599),
  CHECK (request_hash = '' OR length(request_hash) = 64),
  CHECK (response_hash = '' OR length(response_hash) = 64)
);

CREATE INDEX IF NOT EXISTS idx_tool_call_http_attempt_job
  ON agent_tool_call_http_attempt(job_id, tool_call_id, attempt_no);

COMMENT ON TABLE api_connection IS
  '外部 API 固定 Origin 的稳定身份；敏感认证材料不属于 Connection';
COMMENT ON TABLE api_connection_revision IS
  '发布后不可变的固定 Origin、预算和精确 Authentication Profile Revision';
COMMENT ON TABLE api_capability IS
  '使用 cap__ 保留命名空间的稳定业务和模型 Tool 标识';
COMMENT ON TABLE api_capability_draft IS
  '统一工作台的可编辑聚合；Capability、Handler、Connection 与 Mapping 仍分别版本化';
COMMENT ON TABLE api_capability_release IS
  '原子冻结公开契约、声明式 Handler、Connection、Authentication Profile 与 Mapping Plan';
COMMENT ON TABLE external_api_credential IS
  '当前用户个人外部 Token 的独立密文；不属于共享平台 Secret';
COMMENT ON TABLE external_api_verification_challenge IS
  '短时、单次、当前用户绑定的 ONES 候选和临时加密 Token';
COMMENT ON TABLE agent_job_external_subject IS
  'Job 冻结的外部 User/default Team 主体快照；永不保存 Token';
COMMENT ON TABLE agent_tool_call_http_attempt IS
  '受治理 QUERY 的安全 attempt 元数据；不保存请求或响应正文';
