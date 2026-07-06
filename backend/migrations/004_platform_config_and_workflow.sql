CREATE TABLE IF NOT EXISTS platform_environment (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  display_name TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  aliases_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_environment_status ON platform_environment(status);

COMMENT ON TABLE platform_environment IS '平台环境配置表，保存企业环境或组织维度的 topology 根节点';
COMMENT ON COLUMN platform_environment.code IS '环境唯一编码，例如 sanjiu、mmk';
COMMENT ON COLUMN platform_environment.status IS '环境状态，enabled 表示启用，disabled 表示停用';
COMMENT ON COLUMN platform_environment.aliases_json IS '环境别名 JSON 数组，用于自然语言寻址';
COMMENT ON COLUMN platform_environment.metadata_json IS '环境扩展元数据 JSON，不保存敏感明文';
COMMENT ON COLUMN platform_environment.revision IS '配置修订号，每次更新递增';

CREATE TABLE IF NOT EXISTS platform_base (
  id TEXT PRIMARY KEY,
  environment_id TEXT NOT NULL REFERENCES platform_environment(id),
  code TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  engine TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'enabled',
  aliases_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(environment_id, code)
);

CREATE INDEX IF NOT EXISTS idx_platform_base_environment ON platform_base(environment_id);
CREATE INDEX IF NOT EXISTS idx_platform_base_status ON platform_base(status);

COMMENT ON TABLE platform_base IS '平台基地配置表，保存环境下的业务基地和默认数据库引擎';
COMMENT ON COLUMN platform_base.environment_id IS '所属环境 ID';
COMMENT ON COLUMN platform_base.engine IS '基地默认数据库引擎，例如 mysql、sqlserver、oracle';

CREATE TABLE IF NOT EXISTS platform_workshop (
  id TEXT PRIMARY KEY,
  base_id TEXT NOT NULL REFERENCES platform_base(id),
  code TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT '',
  table_prefix TEXT NOT NULL DEFAULT '',
  redis_key_prefix TEXT NOT NULL DEFAULT '',
  loki_labels_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'enabled',
  aliases_json TEXT NOT NULL DEFAULT '[]',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(base_id, code)
);

CREATE INDEX IF NOT EXISTS idx_platform_workshop_base ON platform_workshop(base_id);
CREATE INDEX IF NOT EXISTS idx_platform_workshop_status ON platform_workshop(status);

COMMENT ON TABLE platform_workshop IS '平台车间配置表，保存基地内业务分区、表前缀、Redis key 前缀和 Loki label';
COMMENT ON COLUMN platform_workshop.table_prefix IS '车间表名前缀，用于只读 SQL 安全约束';
COMMENT ON COLUMN platform_workshop.redis_key_prefix IS '车间 Redis key 前缀，用于只读 Redis 安全约束';
COMMENT ON COLUMN platform_workshop.loki_labels_json IS '车间 Loki label 约束 JSON';

CREATE TABLE IF NOT EXISTS platform_secret_reference (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  provider TEXT NOT NULL,
  ref TEXT NOT NULL,
  purpose TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'enabled',
  metadata_json TEXT NOT NULL DEFAULT '{}',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_secret_reference_status ON platform_secret_reference(status);

COMMENT ON TABLE platform_secret_reference IS '平台密钥引用表，只保存 env/vault/kms 等引用，不保存真实密钥值';
COMMENT ON COLUMN platform_secret_reference.provider IS '密钥提供方，例如 env、vault、kms';
COMMENT ON COLUMN platform_secret_reference.ref IS '密钥引用字符串，例如 env:ORDER_DB_PASSWORD';

CREATE TABLE IF NOT EXISTS platform_resource_binding (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  scope_type TEXT NOT NULL,
  environment_id TEXT REFERENCES platform_environment(id),
  base_id TEXT REFERENCES platform_base(id),
  workshop_id TEXT REFERENCES platform_workshop(id),
  resource_kind TEXT NOT NULL,
  connector_id TEXT REFERENCES integration_connector(id),
  engine TEXT,
  config_json TEXT NOT NULL DEFAULT '{}',
  secret_refs_json TEXT NOT NULL DEFAULT '{}',
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_resource_binding_scope ON platform_resource_binding(scope_type, environment_id, base_id, workshop_id);
CREATE INDEX IF NOT EXISTS idx_platform_resource_binding_kind ON platform_resource_binding(resource_kind);
CREATE INDEX IF NOT EXISTS idx_platform_resource_binding_status ON platform_resource_binding(status);

COMMENT ON TABLE platform_resource_binding IS '平台资源绑定表，保存 DB、Redis、Loki、ER context、业务图 context 等资源配置';
COMMENT ON COLUMN platform_resource_binding.scope_type IS '资源作用域类型，environment、base 或 workshop';
COMMENT ON COLUMN platform_resource_binding.config_json IS '资源非敏感连接和策略配置 JSON';
COMMENT ON COLUMN platform_resource_binding.secret_refs_json IS '资源密钥引用 JSON，只能保存 secret reference';

CREATE TABLE IF NOT EXISTS platform_access_grant (
  id TEXT PRIMARY KEY,
  subject_type TEXT NOT NULL,
  subject_code TEXT NOT NULL,
  effect TEXT NOT NULL,
  environment_id TEXT REFERENCES platform_environment(id),
  base_id TEXT REFERENCES platform_base(id),
  workshop_id TEXT REFERENCES platform_workshop(id),
  tool_scope_json TEXT NOT NULL DEFAULT '[]',
  resource_scope_json TEXT NOT NULL DEFAULT '{}',
  condition_json TEXT NOT NULL DEFAULT '{}',
  priority INTEGER NOT NULL DEFAULT 100,
  status TEXT NOT NULL DEFAULT 'enabled',
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_access_grant_subject ON platform_access_grant(subject_type, subject_code);
CREATE INDEX IF NOT EXISTS idx_platform_access_grant_scope ON platform_access_grant(environment_id, base_id, workshop_id);
CREATE INDEX IF NOT EXISTS idx_platform_access_grant_status ON platform_access_grant(status);

COMMENT ON TABLE platform_access_grant IS '平台访问授权表，保存用户、组、角色、服务账号对 topology 和工具范围的授权';
COMMENT ON COLUMN platform_access_grant.effect IS '授权效果，allow 或 deny';
COMMENT ON COLUMN platform_access_grant.priority IS '授权优先级，数值越小优先级越高';

CREATE TABLE IF NOT EXISTS platform_config_audit (
  id TEXT PRIMARY KEY,
  entity_type TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  action TEXT NOT NULL,
  actor_id TEXT NOT NULL DEFAULT '',
  before_json TEXT NOT NULL DEFAULT '{}',
  after_json TEXT NOT NULL DEFAULT '{}',
  correlation_id TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_platform_config_audit_entity ON platform_config_audit(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_platform_config_audit_created ON platform_config_audit(created_at);

COMMENT ON TABLE platform_config_audit IS '平台配置审计表，记录配置新增、修改、启停、导入和发布动作';

CREATE TABLE IF NOT EXISTS agent_workflow_template (
  id TEXT PRIMARY KEY,
  code TEXT NOT NULL UNIQUE,
  name TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  project_code TEXT NOT NULL DEFAULT 'default',
  status TEXT NOT NULL DEFAULT 'draft',
  version INTEGER NOT NULL DEFAULT 1,
  entry_node_key TEXT NOT NULL DEFAULT '',
  graph_schema_version INTEGER NOT NULL DEFAULT 1,
  graph_json TEXT NOT NULL DEFAULT '{}',
  settings_json TEXT NOT NULL DEFAULT '{}',
  created_by TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_agent_workflow_template_project ON agent_workflow_template(project_code);
CREATE INDEX IF NOT EXISTS idx_agent_workflow_template_status ON agent_workflow_template(status);

COMMENT ON TABLE agent_workflow_template IS 'Agent 诊断流程模板表，保存 Web 拖拽编排草稿配置';

CREATE TABLE IF NOT EXISTS agent_workflow_node (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL REFERENCES agent_workflow_template(id),
  node_key TEXT NOT NULL,
  node_type TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '',
  position_json TEXT NOT NULL DEFAULT '{}',
  config_json TEXT NOT NULL DEFAULT '{}',
  ui_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(template_id, node_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_workflow_node_template ON agent_workflow_node(template_id);
CREATE INDEX IF NOT EXISTS idx_agent_workflow_node_type ON agent_workflow_node(node_type);

COMMENT ON TABLE agent_workflow_node IS 'Agent 流程节点表，保存拖拽节点、位置和节点配置';

CREATE TABLE IF NOT EXISTS agent_workflow_edge (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL REFERENCES agent_workflow_template(id),
  edge_key TEXT NOT NULL,
  source_node_key TEXT NOT NULL,
  target_node_key TEXT NOT NULL,
  source_port TEXT NOT NULL DEFAULT '',
  target_port TEXT NOT NULL DEFAULT '',
  condition_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(template_id, edge_key)
);

CREATE INDEX IF NOT EXISTS idx_agent_workflow_edge_template ON agent_workflow_edge(template_id);
CREATE INDEX IF NOT EXISTS idx_agent_workflow_edge_source ON agent_workflow_edge(template_id, source_node_key);
CREATE INDEX IF NOT EXISTS idx_agent_workflow_edge_target ON agent_workflow_edge(template_id, target_node_key);

COMMENT ON TABLE agent_workflow_edge IS 'Agent 流程边表，保存节点连线、端口和条件';

CREATE TABLE IF NOT EXISTS agent_workflow_publication (
  id TEXT PRIMARY KEY,
  template_id TEXT NOT NULL REFERENCES agent_workflow_template(id),
  version INTEGER NOT NULL,
  graph_snapshot_json TEXT NOT NULL,
  config_hash TEXT NOT NULL,
  published_by TEXT NOT NULL DEFAULT '',
  published_at TEXT NOT NULL,
  UNIQUE(template_id, version)
);

CREATE INDEX IF NOT EXISTS idx_agent_workflow_publication_template ON agent_workflow_publication(template_id);

COMMENT ON TABLE agent_workflow_publication IS 'Agent 流程发布快照表，保存不可变的已发布 graph snapshot';
