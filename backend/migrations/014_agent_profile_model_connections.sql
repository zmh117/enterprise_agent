CREATE TABLE IF NOT EXISTS model_connection (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  protocol TEXT NOT NULL
    CHECK (protocol IN ('anthropic_compatible')),
  current_revision_id TEXT,
  status TEXT NOT NULL DEFAULT 'rotation_required'
    CHECK (status IN ('ready', 'rotation_required', 'disabled')),
  revision INTEGER NOT NULL DEFAULT 0,
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_model_connection_status
  ON model_connection(status);

CREATE TABLE IF NOT EXISTS model_connection_revision (
  id TEXT PRIMARY KEY,
  connection_id TEXT NOT NULL REFERENCES model_connection(id),
  revision INTEGER NOT NULL,
  status TEXT NOT NULL DEFAULT 'ready'
    CHECK (status IN ('ready', 'rotation_required', 'disabled')),
  config_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  api_key_secret_id TEXT REFERENCES platform_secret(id),
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  UNIQUE(connection_id, revision)
);

CREATE INDEX IF NOT EXISTS idx_model_connection_revision_connection
  ON model_connection_revision(connection_id, revision);
CREATE INDEX IF NOT EXISTS idx_model_connection_revision_status
  ON model_connection_revision(status);
CREATE INDEX IF NOT EXISTS idx_model_connection_revision_hash
  ON model_connection_revision(config_hash);

ALTER TABLE agent_job ADD COLUMN model_runtime_provenance_json TEXT;

COMMENT ON TABLE model_connection IS
  'Agent模型连接稳定身份；MVP仅支持Anthropic兼容协议';
COMMENT ON TABLE model_connection_revision IS
  '模型连接追加式版本；非敏感配置可发布，凭据仅引用加密Secret';
COMMENT ON COLUMN model_connection_revision.api_key_secret_id IS
  '内部凭据绑定，管理API、审计、prompt和运行记录不得输出';
COMMENT ON COLUMN agent_job.model_runtime_provenance_json IS
  'Job创建时固定的非敏感模型运行来源，不包含Secret ID、引用或明文';
