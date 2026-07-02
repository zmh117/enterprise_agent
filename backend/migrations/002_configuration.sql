CREATE TABLE IF NOT EXISTS tool_definition (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL UNIQUE,
  risk_level TEXT NOT NULL DEFAULT 'low',
  read_only INTEGER NOT NULL DEFAULT 1,
  enabled INTEGER NOT NULL DEFAULT 1,
  description TEXT NOT NULL DEFAULT '',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

COMMENT ON TABLE tool_definition IS '工具定义表，记录 Agent 可调用内部工具的名称、风险级别、只读属性和启用状态';
COMMENT ON COLUMN tool_definition.id IS '工具定义 ID';
COMMENT ON COLUMN tool_definition.name IS '工具唯一名称，例如 database.query、loki.query、schema.directory';
COMMENT ON COLUMN tool_definition.risk_level IS '工具风险级别，例如 low、medium、high';
COMMENT ON COLUMN tool_definition.read_only IS '是否为只读工具，1 表示只读，0 表示非只读';
COMMENT ON COLUMN tool_definition.enabled IS '工具是否启用，1 表示启用，0 表示停用';
COMMENT ON COLUMN tool_definition.description IS '工具用途说明';
COMMENT ON COLUMN tool_definition.created_at IS '工具定义创建时间';
COMMENT ON COLUMN tool_definition.updated_at IS '工具定义最近更新时间';

CREATE TABLE IF NOT EXISTS integration_connector (
  id TEXT PRIMARY KEY,
  connector_type TEXT NOT NULL,
  name TEXT NOT NULL UNIQUE,
  base_url TEXT NOT NULL DEFAULT '',
  enabled INTEGER NOT NULL DEFAULT 1,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

COMMENT ON TABLE integration_connector IS '集成连接器配置表，记录内部工具平台、Channel 入口和 Delivery 出口的连接配置';
COMMENT ON COLUMN integration_connector.id IS '连接器 ID';
COMMENT ON COLUMN integration_connector.connector_type IS '连接器类型，例如 internal_api_platform、dingtalk_webhook_robot、email、webhook';
COMMENT ON COLUMN integration_connector.name IS '连接器唯一名称';
COMMENT ON COLUMN integration_connector.base_url IS '连接器基础地址或服务地址，不应包含敏感 token';
COMMENT ON COLUMN integration_connector.enabled IS '连接器是否启用，1 表示启用，0 表示停用';
COMMENT ON COLUMN integration_connector.metadata IS '连接器扩展配置 JSON，不应保存敏感明文';
COMMENT ON COLUMN integration_connector.created_at IS '连接器创建时间';
COMMENT ON COLUMN integration_connector.updated_at IS '连接器最近更新时间';

CREATE TABLE IF NOT EXISTS datasource_registry (
  id TEXT PRIMARY KEY,
  source_type TEXT NOT NULL,
  source_code TEXT NOT NULL UNIQUE,
  connector_id TEXT REFERENCES integration_connector(id),
  enabled INTEGER NOT NULL DEFAULT 1,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

COMMENT ON TABLE datasource_registry IS '数据源注册表，记录项目可用的数据库、日志、Redis 或上下文数据源及其连接器归属';
COMMENT ON COLUMN datasource_registry.id IS '数据源注册 ID';
COMMENT ON COLUMN datasource_registry.source_type IS '数据源类型，例如 database、loki、redis、context';
COMMENT ON COLUMN datasource_registry.source_code IS '数据源唯一编码，用于工具请求寻址';
COMMENT ON COLUMN datasource_registry.connector_id IS '关联的集成连接器 ID';
COMMENT ON COLUMN datasource_registry.enabled IS '数据源是否启用，1 表示启用，0 表示停用';
COMMENT ON COLUMN datasource_registry.metadata IS '数据源扩展配置 JSON，例如 schema、tenant、标签映射等非敏感信息';
COMMENT ON COLUMN datasource_registry.created_at IS '数据源注册创建时间';
COMMENT ON COLUMN datasource_registry.updated_at IS '数据源注册最近更新时间';

CREATE TABLE IF NOT EXISTS permission_policy (
  id TEXT PRIMARY KEY,
  subject_type TEXT NOT NULL,
  subject_code TEXT NOT NULL,
  resource_type TEXT NOT NULL,
  resource_code TEXT NOT NULL,
  effect TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

COMMENT ON TABLE permission_policy IS '权限策略表，记录主体对工具、数据源、项目或环境资源的允许和拒绝规则';
COMMENT ON COLUMN permission_policy.id IS '权限策略 ID';
COMMENT ON COLUMN permission_policy.subject_type IS '主体类型，例如 user、role、service、channel';
COMMENT ON COLUMN permission_policy.subject_code IS '主体编码，例如用户 ID、角色编码或服务账号编码';
COMMENT ON COLUMN permission_policy.resource_type IS '资源类型，例如 tool、datasource、project、environment';
COMMENT ON COLUMN permission_policy.resource_code IS '资源编码，例如工具名称、数据源编码或项目编码';
COMMENT ON COLUMN permission_policy.effect IS '策略效果，例如 allow 或 deny';
COMMENT ON COLUMN permission_policy.created_at IS '权限策略创建时间';
COMMENT ON COLUMN permission_policy.updated_at IS '权限策略最近更新时间';
