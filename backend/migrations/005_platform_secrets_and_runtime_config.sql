CREATE TABLE IF NOT EXISTS platform_secret (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL DEFAULT 'encrypted_db',
  ref TEXT NOT NULL UNIQUE,
  purpose TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  active_version INTEGER NOT NULL DEFAULT 0,
  masked_summary TEXT NOT NULL DEFAULT '',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_secret_status ON platform_secret(status);
CREATE INDEX IF NOT EXISTS idx_platform_secret_ref ON platform_secret(ref);

COMMENT ON TABLE platform_secret IS 'Web 管理密钥元数据表，只保存引用、状态、当前版本和脱敏摘要';
COMMENT ON COLUMN platform_secret.ref IS '稳定密钥引用，格式 secret://platform/<code>';
COMMENT ON COLUMN platform_secret.masked_summary IS '密钥脱敏摘要，不可用于还原明文';

CREATE TABLE IF NOT EXISTS platform_secret_version (
  id TEXT PRIMARY KEY,
  secret_id TEXT NOT NULL REFERENCES platform_secret(id),
  version INTEGER NOT NULL,
  ciphertext TEXT NOT NULL,
  nonce TEXT NOT NULL,
  key_id TEXT NOT NULL DEFAULT '',
  algorithm TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(secret_id, version)
);

CREATE INDEX IF NOT EXISTS idx_platform_secret_version_secret ON platform_secret_version(secret_id);
CREATE INDEX IF NOT EXISTS idx_platform_secret_version_status ON platform_secret_version(status);

COMMENT ON TABLE platform_secret_version IS 'Web 管理密钥密文版本表，保存 AES-GCM 密文和 nonce';
COMMENT ON COLUMN platform_secret_version.ciphertext IS '加密后的密钥值，API、审计和 prompt 不得输出';
COMMENT ON COLUMN platform_secret_version.nonce IS 'AES-GCM nonce';

CREATE TABLE IF NOT EXISTS platform_runtime_config_definition (
  id TEXT PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,
  value_type TEXT NOT NULL,
  default_json TEXT NOT NULL DEFAULT 'null',
  sensitive INTEGER NOT NULL DEFAULT 0,
  bootstrap_only INTEGER NOT NULL DEFAULT 0,
  service_names_json TEXT NOT NULL DEFAULT '[]',
  description TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_runtime_config_definition_status
  ON platform_runtime_config_definition(status);
CREATE INDEX IF NOT EXISTS idx_platform_runtime_config_definition_bootstrap
  ON platform_runtime_config_definition(bootstrap_only);

COMMENT ON TABLE platform_runtime_config_definition IS '运行时配置定义表，声明 key、类型、默认值、敏感性和适用服务';
COMMENT ON COLUMN platform_runtime_config_definition.bootstrap_only IS '1 表示只能由部署环境提供，不允许 DB 普通配置覆盖';

CREATE TABLE IF NOT EXISTS platform_runtime_config_value (
  id TEXT PRIMARY KEY,
  definition_id TEXT NOT NULL REFERENCES platform_runtime_config_definition(id),
  key TEXT NOT NULL,
  scope_type TEXT NOT NULL DEFAULT 'global',
  scope_code TEXT NOT NULL DEFAULT '*',
  service_name TEXT NOT NULL DEFAULT '',
  value_json TEXT NOT NULL DEFAULT 'null',
  secret_ref TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(key, scope_type, scope_code, service_name)
);

CREATE INDEX IF NOT EXISTS idx_platform_runtime_config_value_key
  ON platform_runtime_config_value(key);
CREATE INDEX IF NOT EXISTS idx_platform_runtime_config_value_scope
  ON platform_runtime_config_value(scope_type, scope_code, service_name);
CREATE INDEX IF NOT EXISTS idx_platform_runtime_config_value_status
  ON platform_runtime_config_value(status);

COMMENT ON TABLE platform_runtime_config_value IS '运行时配置值表，保存 typed key 在不同作用域下的非敏感值或 secret_ref';
COMMENT ON COLUMN platform_runtime_config_value.secret_ref IS '敏感配置引用，只允许 secret://platform、env、vault、kms 等引用，不保存明文';
