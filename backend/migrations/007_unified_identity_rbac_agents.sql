CREATE TABLE IF NOT EXISTS app_user (
  id TEXT PRIMARY KEY,
  username TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_app_user_status ON app_user(status);

CREATE TABLE IF NOT EXISTS user_password_credential (
  user_id TEXT PRIMARY KEY REFERENCES app_user(id),
  password_hash TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  password_changed_at TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS user_external_identity (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_user(id),
  provider TEXT NOT NULL,
  tenant_code TEXT NOT NULL,
  external_subject_id TEXT NOT NULL,
  connector_id TEXT NOT NULL DEFAULT '',
  union_id TEXT NOT NULL DEFAULT '',
  open_id TEXT NOT NULL DEFAULT '',
  display_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  verified_at TEXT,
  last_seen_at TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(provider, tenant_code, external_subject_id)
);

CREATE INDEX IF NOT EXISTS idx_external_identity_user
  ON user_external_identity(user_id);
CREATE INDEX IF NOT EXISTS idx_external_identity_status
  ON user_external_identity(status);

CREATE TABLE IF NOT EXISTS user_session (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_user(id),
  token_hash TEXT NOT NULL UNIQUE,
  csrf_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  idle_expires_at TEXT NOT NULL,
  absolute_expires_at TEXT NOT NULL,
  revoked_at TEXT,
  user_agent_summary TEXT NOT NULL DEFAULT '',
  remote_address_summary TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_user_session_user ON user_session(user_id);
CREATE INDEX IF NOT EXISTS idx_user_session_status ON user_session(status);
CREATE INDEX IF NOT EXISTS idx_user_session_expiry
  ON user_session(idle_expires_at, absolute_expires_at);

CREATE TABLE IF NOT EXISTS rbac_role (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rbac_role_status ON rbac_role(status);

CREATE TABLE IF NOT EXISTS rbac_user_role (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES app_user(id),
  role_id TEXT NOT NULL REFERENCES rbac_role(id),
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_rbac_user_role_user ON rbac_user_role(user_id);
CREATE INDEX IF NOT EXISTS idx_rbac_user_role_role ON rbac_user_role(role_id);

ALTER TABLE permission_policy ADD COLUMN action TEXT NOT NULL DEFAULT 'use';
ALTER TABLE permission_policy ADD COLUMN status TEXT NOT NULL DEFAULT 'enabled';
ALTER TABLE permission_policy ADD COLUMN priority INTEGER NOT NULL DEFAULT 100;
ALTER TABLE permission_policy ADD COLUMN revision INTEGER NOT NULL DEFAULT 1;

CREATE INDEX IF NOT EXISTS idx_permission_policy_subject
  ON permission_policy(subject_type, subject_code);
CREATE INDEX IF NOT EXISTS idx_permission_policy_resource
  ON permission_policy(resource_type, resource_code, action);

CREATE TABLE IF NOT EXISTS identity_migration_audit (
  id TEXT PRIMARY KEY,
  legacy_subject_type TEXT NOT NULL,
  legacy_subject_code TEXT NOT NULL,
  tenant_code TEXT NOT NULL DEFAULT '',
  internal_user_id TEXT REFERENCES app_user(id),
  status TEXT NOT NULL,
  reason TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_identity_migration_status
  ON identity_migration_audit(status);

CREATE TABLE IF NOT EXISTS agent_definition (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  project_code TEXT NOT NULL DEFAULT 'default',
  status TEXT NOT NULL DEFAULT 'enabled',
  current_publication_id TEXT,
  revision INTEGER NOT NULL DEFAULT 1,
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_definition_status
  ON agent_definition(status);
CREATE INDEX IF NOT EXISTS idx_agent_definition_project
  ON agent_definition(project_code);

CREATE TABLE IF NOT EXISTS agent_revision (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agent_definition(id),
  revision INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'draft',
  config_json TEXT NOT NULL DEFAULT '{}',
  config_hash TEXT NOT NULL DEFAULT '',
  validation_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(agent_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_agent_revision_agent
  ON agent_revision(agent_id, revision);
CREATE INDEX IF NOT EXISTS idx_agent_revision_status
  ON agent_revision(status);

CREATE TABLE IF NOT EXISTS agent_publication (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL REFERENCES agent_definition(id),
  revision_id TEXT NOT NULL REFERENCES agent_revision(id),
  revision INTEGER NOT NULL,
  schema_version INTEGER NOT NULL DEFAULT 1,
  snapshot_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  published_by TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL,
  UNIQUE(agent_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_agent_publication_agent
  ON agent_publication(agent_id, revision);
CREATE INDEX IF NOT EXISTS idx_agent_publication_status
  ON agent_publication(status);

CREATE TABLE IF NOT EXISTS agent_tool_binding (
  id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  tool_name TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(publication_id, tool_name)
);

CREATE TABLE IF NOT EXISTS agent_skill_binding (
  id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  skill_code TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(publication_id, skill_code)
);

CREATE TABLE IF NOT EXISTS agent_channel_binding (
  id TEXT PRIMARY KEY,
  publication_id TEXT NOT NULL REFERENCES agent_publication(id),
  direction TEXT NOT NULL,
  connector_id TEXT NOT NULL,
  config_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  UNIQUE(publication_id, direction, connector_id)
);

ALTER TABLE agent_session ADD COLUMN external_identity_id TEXT;
ALTER TABLE agent_job ADD COLUMN internal_user_id TEXT;
ALTER TABLE agent_job ADD COLUMN external_identity_id TEXT;
ALTER TABLE agent_job ADD COLUMN agent_definition_id TEXT;
ALTER TABLE agent_job ADD COLUMN agent_publication_id TEXT;
ALTER TABLE agent_job ADD COLUMN agent_revision INTEGER;
ALTER TABLE agent_job ADD COLUMN agent_config_hash TEXT NOT NULL DEFAULT '';

CREATE INDEX IF NOT EXISTS idx_agent_job_internal_user
  ON agent_job(internal_user_id);
CREATE INDEX IF NOT EXISTS idx_agent_job_publication
  ON agent_job(agent_publication_id);

COMMENT ON TABLE app_user IS '统一内部用户，Web和Channel身份均解析到该主体';
COMMENT ON TABLE user_external_identity IS '外部身份绑定，钉钉按provider+tenant+subject唯一';
COMMENT ON TABLE user_session IS 'Web服务端session，仅保存token和CSRF哈希';
COMMENT ON TABLE rbac_role IS '统一RBAC角色';
COMMENT ON TABLE agent_definition IS '支持多Agent的稳定定义';
COMMENT ON TABLE agent_revision IS 'Agent可编辑草稿revision';
COMMENT ON TABLE agent_publication IS 'Agent不可变发布快照';
