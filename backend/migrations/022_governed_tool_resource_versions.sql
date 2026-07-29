CREATE TABLE IF NOT EXISTS platform_resource (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL DEFAULT '',
  resource_kind TEXT NOT NULL
    CHECK (resource_kind IN ('database', 'redis', 'loki')),
  scope_type TEXT NOT NULL
    CHECK (scope_type IN ('environment', 'base', 'workshop')),
  environment_id TEXT NOT NULL REFERENCES platform_environment(id),
  base_id TEXT REFERENCES platform_base(id),
  workshop_id TEXT REFERENCES platform_workshop(id),
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled', 'archived')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  CHECK (
    (scope_type = 'environment' AND base_id IS NULL AND workshop_id IS NULL)
    OR
    (scope_type = 'base' AND base_id IS NOT NULL AND workshop_id IS NULL)
    OR
    (scope_type = 'workshop' AND base_id IS NOT NULL AND workshop_id IS NOT NULL)
  )
);

CREATE INDEX IF NOT EXISTS idx_platform_resource_scope
  ON platform_resource(scope_type, environment_id, base_id, workshop_id);
CREATE INDEX IF NOT EXISTS idx_platform_resource_kind_status
  ON platform_resource(resource_kind, status);

CREATE TABLE IF NOT EXISTS platform_resource_draft (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL UNIQUE REFERENCES platform_resource(id),
  draft_revision INTEGER NOT NULL DEFAULT 1 CHECK (draft_revision >= 1),
  provider_type TEXT NOT NULL
    CHECK (provider_type IN ('mysql', 'sqlserver', 'oracle', 'redis', 'loki')),
  config_json TEXT NOT NULL DEFAULT '{}',
  secret_refs_json TEXT NOT NULL DEFAULT '{}',
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL DEFAULT 'DRAFT'
    CHECK (status IN ('DRAFT', 'VERIFIED')),
  created_by TEXT NOT NULL DEFAULT '',
  updated_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_resource_draft_status
  ON platform_resource_draft(status, updated_at);

CREATE TABLE IF NOT EXISTS platform_resource_verification (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES platform_resource(id),
  draft_id TEXT REFERENCES platform_resource_draft(id) ON DELETE SET NULL,
  draft_revision INTEGER NOT NULL CHECK (draft_revision >= 1),
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  status TEXT NOT NULL
    CHECK (status IN ('PASSED', 'FAILED', 'BLOCKED')),
  provider_contract_version TEXT NOT NULL,
  checks_json TEXT NOT NULL DEFAULT '{}',
  safe_error_summary TEXT NOT NULL DEFAULT '',
  verified_by TEXT NOT NULL DEFAULT '',
  verified_at TEXT NOT NULL,
  UNIQUE(resource_id, draft_revision, content_hash)
);

CREATE INDEX IF NOT EXISTS idx_platform_resource_verification_resource
  ON platform_resource_verification(resource_id, verified_at);

CREATE TABLE IF NOT EXISTS platform_resource_revision (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES platform_resource(id),
  revision INTEGER NOT NULL CHECK (revision >= 1),
  provider_type TEXT NOT NULL
    CHECK (provider_type IN ('mysql', 'sqlserver', 'oracle', 'redis', 'loki')),
  provider_contract_version TEXT NOT NULL,
  config_json TEXT NOT NULL,
  secret_refs_json TEXT NOT NULL DEFAULT '{}',
  content_hash TEXT NOT NULL CHECK (length(content_hash) = 64),
  verification_id TEXT NOT NULL REFERENCES platform_resource_verification(id),
  status TEXT NOT NULL DEFAULT 'PUBLISHED'
    CHECK (status IN ('PUBLISHED', 'DISABLED', 'ARCHIVED')),
  published_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  disabled_by TEXT NOT NULL DEFAULT '',
  disabled_at TEXT,
  archived_by TEXT NOT NULL DEFAULT '',
  archived_at TEXT,
  UNIQUE(resource_id, revision),
  UNIQUE(resource_id, id)
);

CREATE INDEX IF NOT EXISTS idx_platform_resource_revision_status
  ON platform_resource_revision(resource_id, status, revision);

CREATE TABLE IF NOT EXISTS business_application_resource_binding (
  id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  slot_code TEXT NOT NULL,
  resource_revision_id TEXT NOT NULL
    REFERENCES platform_resource_revision(id),
  binding_constraints_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(publication_id, slot_code)
);

CREATE INDEX IF NOT EXISTS idx_business_application_resource_revision
  ON business_application_resource_binding(resource_revision_id);

CREATE TABLE IF NOT EXISTS platform_resource_activation (
  id TEXT PRIMARY KEY,
  resource_id TEXT NOT NULL REFERENCES platform_resource(id),
  runtime_environment TEXT NOT NULL,
  published_revision_id TEXT NOT NULL,
  effective_revision_id TEXT,
  last_known_good_revision_id TEXT,
  published_generation INTEGER NOT NULL CHECK (published_generation >= 1),
  effective_generation INTEGER NOT NULL DEFAULT 0
    CHECK (effective_generation >= 0),
  attempt_no INTEGER NOT NULL DEFAULT 1 CHECK (attempt_no >= 1),
  status TEXT NOT NULL
    CHECK (
      status IN (
        'PENDING',
        'ACTIVE',
        'DEGRADED',
        'BLOCKED',
        'DISABLED',
        'ARCHIVED'
      )
    ),
  safe_error_summary TEXT NOT NULL DEFAULT '',
  observed_at TEXT NOT NULL,
  activated_at TEXT,
  UNIQUE(resource_id, published_revision_id, runtime_environment, attempt_no),
  FOREIGN KEY(resource_id, published_revision_id)
    REFERENCES platform_resource_revision(resource_id, id),
  FOREIGN KEY(resource_id, effective_revision_id)
    REFERENCES platform_resource_revision(resource_id, id),
  FOREIGN KEY(resource_id, last_known_good_revision_id)
    REFERENCES platform_resource_revision(resource_id, id),
  CHECK (status != 'ACTIVE' OR effective_revision_id IS NOT NULL),
  CHECK (
    last_known_good_revision_id IS NULL
    OR effective_revision_id = last_known_good_revision_id
    OR status = 'PENDING'
  )
);

CREATE INDEX IF NOT EXISTS idx_platform_resource_activation_observed
  ON platform_resource_activation(
    runtime_environment,
    resource_id,
    published_generation,
    observed_at
  );

CREATE TABLE IF NOT EXISTS handler_installation (
  handler_id TEXT NOT NULL,
  handler_version TEXT NOT NULL,
  implementation_digest TEXT NOT NULL
    CHECK (length(implementation_digest) = 64),
  display_name TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  input_schema_json TEXT NOT NULL,
  output_schema_json TEXT NOT NULL,
  risk_level TEXT NOT NULL
    CHECK (risk_level IN ('LOW', 'MEDIUM', 'HIGH')),
  required_permissions_json TEXT NOT NULL DEFAULT '[]',
  resource_slots_json TEXT NOT NULL DEFAULT '[]',
  visibility TEXT NOT NULL DEFAULT 'application'
    CHECK (visibility IN ('application', 'internal_diagnostic')),
  installation_status TEXT NOT NULL DEFAULT 'INSTALLED'
    CHECK (installation_status IN ('INSTALLED', 'MISSING', 'DRIFTED')),
  first_seen_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  PRIMARY KEY(handler_id, handler_version)
);

CREATE INDEX IF NOT EXISTS idx_handler_installation_status
  ON handler_installation(installation_status, handler_id);

CREATE TABLE IF NOT EXISTS handler_publication (
  id TEXT PRIMARY KEY,
  handler_id TEXT NOT NULL,
  handler_version TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'PUBLISHED'
    CHECK (status IN ('PUBLISHED', 'DISABLED', 'ARCHIVED')),
  revision INTEGER NOT NULL DEFAULT 1 CHECK (revision >= 1),
  published_by TEXT NOT NULL,
  published_at TEXT NOT NULL,
  disabled_by TEXT NOT NULL DEFAULT '',
  disabled_at TEXT,
  archived_by TEXT NOT NULL DEFAULT '',
  archived_at TEXT,
  UNIQUE(handler_id, handler_version),
  FOREIGN KEY(handler_id, handler_version)
    REFERENCES handler_installation(handler_id, handler_version)
);

CREATE INDEX IF NOT EXISTS idx_handler_publication_status
  ON handler_publication(status, handler_id);

CREATE TABLE IF NOT EXISTS business_application_publication_handler (
  id TEXT PRIMARY KEY,
  application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  handler_publication_id TEXT NOT NULL
    REFERENCES handler_publication(id),
  capability_code TEXT NOT NULL,
  constraints_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(application_publication_id, capability_code),
  UNIQUE(application_publication_id, handler_publication_id)
);

CREATE INDEX IF NOT EXISTS idx_application_handler_publication
  ON business_application_publication_handler(handler_publication_id);

CREATE TABLE IF NOT EXISTS business_application_publication_resource (
  id TEXT PRIMARY KEY,
  application_handler_id TEXT NOT NULL
    REFERENCES business_application_publication_handler(id),
  resource_slot TEXT NOT NULL,
  resource_revision_id TEXT NOT NULL
    REFERENCES platform_resource_revision(id),
  constraints_json TEXT NOT NULL DEFAULT '{}',
  binding_hash TEXT NOT NULL CHECK (length(binding_hash) = 64),
  created_at TEXT NOT NULL,
  UNIQUE(application_handler_id, resource_slot)
);

CREATE INDEX IF NOT EXISTS idx_application_handler_resource_revision
  ON business_application_publication_resource(resource_revision_id);

ALTER TABLE agent_definition
  ADD COLUMN classification TEXT NOT NULL DEFAULT 'business'
    CHECK (classification IN ('business', 'internal_diagnostic'));

UPDATE agent_definition
   SET classification = 'internal_diagnostic'
 WHERE code = 'default-diagnostic-agent';

ALTER TABLE agent_job ADD COLUMN execution_scope_id TEXT;
ALTER TABLE agent_job ADD COLUMN execution_scope_hash TEXT;

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_job_execution_scope_id
  ON agent_job(execution_scope_id)
  WHERE execution_scope_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS agent_job_execution_scope (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL UNIQUE REFERENCES agent_job(id),
  business_application_id TEXT NOT NULL REFERENCES business_application(id),
  application_publication_id TEXT NOT NULL
    REFERENCES business_application_publication(id),
  agent_publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  environment_id TEXT NOT NULL REFERENCES platform_environment(id),
  base_id TEXT REFERENCES platform_base(id),
  workshop_id TEXT REFERENCES platform_workshop(id),
  scope_hash TEXT NOT NULL UNIQUE CHECK (length(scope_hash) = 64),
  schema_version INTEGER NOT NULL CHECK (schema_version = 2),
  snapshot_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_job_execution_scope_publication
  ON agent_job_execution_scope(application_publication_id, created_at);
CREATE INDEX IF NOT EXISTS idx_job_execution_scope_nodes
  ON agent_job_execution_scope(environment_id, base_id, workshop_id);

CREATE TABLE IF NOT EXISTS agent_job_execution_binding (
  id TEXT PRIMARY KEY,
  execution_scope_id TEXT NOT NULL REFERENCES agent_job_execution_scope(id),
  capability_code TEXT NOT NULL,
  handler_id TEXT NOT NULL,
  handler_version TEXT NOT NULL,
  resource_slot TEXT NOT NULL,
  resource_revision_id TEXT NOT NULL,
  constraints_json TEXT NOT NULL DEFAULT '{}',
  binding_hash TEXT NOT NULL CHECK (length(binding_hash) = 64),
  created_at TEXT NOT NULL,
  UNIQUE(
    execution_scope_id,
    handler_id,
    handler_version,
    resource_slot
  )
);

CREATE INDEX IF NOT EXISTS idx_execution_binding_resource
  ON agent_job_execution_binding(resource_revision_id, execution_scope_id);

COMMENT ON TABLE platform_resource IS
  'DB、Redis、Loki 的稳定 Resource Identity；连接内容只存在于 Draft/Revision';
COMMENT ON TABLE platform_resource_draft IS
  '每个 Resource Identity 最多一个可编辑 Draft；内容变化必须重置为 DRAFT';
COMMENT ON TABLE platform_resource_verification IS
  '字段、Secret、连接和只读权限的技术验证记录，只保存安全摘要';
COMMENT ON TABLE platform_resource_revision IS
  '发布后不可变的 Resource Revision；普通路径只能更新治理状态';
COMMENT ON TABLE business_application_resource_binding IS
  '业务应用发布的逻辑资源槽到具体 Resource Revision 的不可变绑定';
COMMENT ON TABLE platform_resource_activation IS
  'Published Revision 的运行时装载尝试、Effective Revision 与 Last Known Good';
COMMENT ON TABLE handler_installation IS
  '代码 Handler manifest 发现事实；不保存实现源码、脚本、SQL 模板或 URL';
COMMENT ON TABLE handler_publication IS
  '已安装且 digest 未漂移的精确 Handler 版本治理状态';
COMMENT ON TABLE business_application_publication_handler IS
  '业务应用发布固定到精确 Handler publication；不保存实现内容';
COMMENT ON TABLE business_application_publication_resource IS
  '应用 Handler 逻辑资源槽固定到精确 Published Resource Revision';
COMMENT ON COLUMN agent_definition.classification IS
  'Agent 分类；internal_diagnostic 才允许绑定内部诊断 Handler';
COMMENT ON TABLE agent_job_execution_scope IS
  'Job 创建事务内固化的应用发布、Agent 发布和授权数据范围';
COMMENT ON TABLE agent_job_execution_binding IS
  'Job Execution Scope 固化的精确 Handler 与 Resource Revision 历史事实，不以外键阻止受控资源清理';
