ALTER TABLE rbac_role ADD COLUMN origin TEXT NOT NULL DEFAULT 'custom'
  CHECK (origin IN ('system', 'custom'));
ALTER TABLE rbac_role ADD COLUMN protected INTEGER NOT NULL DEFAULT 0
  CHECK (protected IN (0, 1));
ALTER TABLE rbac_role ADD COLUMN purpose_tags_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE rbac_role ADD COLUMN metadata_revision INTEGER NOT NULL DEFAULT 1;
ALTER TABLE rbac_role ADD COLUMN admin_revision INTEGER NOT NULL DEFAULT 1;
ALTER TABLE rbac_role ADD COLUMN business_revision INTEGER NOT NULL DEFAULT 1;
ALTER TABLE rbac_role ADD COLUMN membership_revision INTEGER NOT NULL DEFAULT 1;

ALTER TABLE rbac_user_role ADD COLUMN expires_at TEXT;
ALTER TABLE rbac_user_role ADD COLUMN assigned_by TEXT NOT NULL DEFAULT '';
ALTER TABLE rbac_user_role ADD COLUMN assignment_source TEXT NOT NULL DEFAULT 'manual';

CREATE INDEX IF NOT EXISTS idx_rbac_user_role_expiry
  ON rbac_user_role(status, expires_at);

CREATE TABLE IF NOT EXISTS rbac_role_admin_capability (
  id TEXT PRIMARY KEY,
  role_id TEXT NOT NULL REFERENCES rbac_role(id),
  capability_code TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_code TEXT NOT NULL DEFAULT '*',
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled')),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(role_id, capability_code, resource_type, resource_code)
);

CREATE INDEX IF NOT EXISTS idx_role_admin_capability_role
  ON rbac_role_admin_capability(role_id, status);
CREATE INDEX IF NOT EXISTS idx_role_admin_capability_resource
  ON rbac_role_admin_capability(capability_code, resource_type, resource_code, status);

CREATE TABLE IF NOT EXISTS rbac_role_application_access (
  id TEXT PRIMARY KEY,
  role_id TEXT NOT NULL REFERENCES rbac_role(id),
  application_id TEXT NOT NULL REFERENCES business_application(id),
  status TEXT NOT NULL DEFAULT 'enabled'
    CHECK (status IN ('enabled', 'disabled')),
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(role_id, application_id)
);

CREATE INDEX IF NOT EXISTS idx_role_application_access_role
  ON rbac_role_application_access(role_id, status);
CREATE INDEX IF NOT EXISTS idx_role_application_access_application
  ON rbac_role_application_access(application_id, status);

CREATE TABLE IF NOT EXISTS rbac_role_application_capability (
  id TEXT PRIMARY KEY,
  application_access_id TEXT NOT NULL REFERENCES rbac_role_application_access(id),
  capability_code TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(application_access_id, capability_code)
);

CREATE INDEX IF NOT EXISTS idx_role_application_capability_access
  ON rbac_role_application_capability(application_access_id);

CREATE TABLE IF NOT EXISTS rbac_role_application_scope (
  id TEXT PRIMARY KEY,
  application_access_id TEXT NOT NULL REFERENCES rbac_role_application_access(id),
  environment_id TEXT NOT NULL REFERENCES platform_environment(id),
  base_id TEXT REFERENCES platform_base(id),
  workshop_id TEXT REFERENCES platform_workshop(id),
  scope_key TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(application_access_id, scope_key)
);

CREATE INDEX IF NOT EXISTS idx_role_application_scope_access
  ON rbac_role_application_scope(application_access_id);
CREATE INDEX IF NOT EXISTS idx_role_application_scope_nodes
  ON rbac_role_application_scope(environment_id, base_id, workshop_id);

UPDATE rbac_role
SET origin = 'system',
    protected = 1,
    description = '管理用户、角色、平台配置和 Agent 发布，仅包含后台管理能力',
    purpose_tags_json = '["平台管理"]',
    metadata_revision = CASE WHEN metadata_revision < 1 THEN 1 ELSE metadata_revision END,
    admin_revision = CASE WHEN admin_revision < 1 THEN 1 ELSE admin_revision END,
    business_revision = CASE WHEN business_revision < 1 THEN 1 ELSE business_revision END,
    membership_revision = CASE WHEN membership_revision < 1 THEN 1 ELSE membership_revision END
WHERE code = 'platform-admin';

COMMENT ON TABLE rbac_role_admin_capability IS '角色管理后台能力绑定，能力定义来自后端只读目录';
COMMENT ON TABLE rbac_role_application_access IS '角色对具体业务应用的使用授权聚合';
COMMENT ON TABLE rbac_role_application_capability IS '业务应用授权下的明确只读能力';
COMMENT ON TABLE rbac_role_application_scope IS '业务应用授权下的明确环境、基地、车间范围，不支持未来资源通配';
