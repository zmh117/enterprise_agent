# readonly-tool-platform Specification

## ADDED Requirements

### Requirement: Internal API Platform loads topology from PostgreSQL configuration
系统 SHALL 让 Internal API Platform 优先从 PostgreSQL platform configuration 构造 topology、资源绑定和访问范围。

#### Scenario: Database topology exists
- **WHEN** PostgreSQL 中存在启用的环境、基地、车间和资源绑定
- **THEN** Internal API Platform 使用 DB-backed snapshot 处理 DB、Redis、Loki、ER 和业务图工具请求

#### Scenario: Database topology is empty in local mode
- **WHEN** PostgreSQL 中没有任何启用 topology 且当前运行模式允许本地 fallback
- **THEN** Internal API Platform 可以读取 YAML topology 作为本地 bootstrap 来源，并在状态接口标记来源为 yaml

#### Scenario: Database topology is invalid
- **WHEN** PostgreSQL 中存在启用 topology 但资源绑定缺少必要 endpoint 或 secret ref
- **THEN** Internal API Platform MUST 暴露配置错误，不得静默回退到 YAML

### Requirement: Tool platform resolves secrets only in infrastructure layer
系统 SHALL 在 Internal API Platform infrastructure 层解析 secret references，并 MUST 防止 domain、API 响应、审计摘要和 Agent prompt 泄露真实密钥。

#### Scenario: Database tool uses env secret ref
- **WHEN** database resource binding 使用 `env:ORDER_DB_PASSWORD`
- **THEN** 只有 infrastructure 连接网关解析该环境变量，工具调用审计只记录 secret ref

#### Scenario: Secret value appears in tool result
- **WHEN** 工具响应或错误信息包含疑似密钥值
- **THEN** Internal API Platform 在保存审计或返回 Agent 前 MUST 脱敏该值

### Requirement: DB-backed resource bindings preserve read-only guardrails
系统 SHALL 确保从 PostgreSQL 配置加载的 DB、Redis、Loki 和 context 工具仍执行只读安全策略。

#### Scenario: DB config enables query_database
- **WHEN** 平台配置启用 database resource binding
- **THEN** `query_database` 仍只允许 policy-approved read query，并拒绝 insert、update、delete、DDL 和 privileged operation

#### Scenario: Redis config enables scan
- **WHEN** 平台配置启用 Redis resource binding
- **THEN** `query_redis_scan` 仍必须受 key pattern、limit 和只读策略约束

### Requirement: Tool platform exposes configuration source in health and debug output
系统 SHALL 在 health 或 debug 输出中暴露当前工具平台配置来源和配置版本摘要，便于本地和生产排障。

#### Scenario: Debug local tools configuration
- **WHEN** 开发者查询 Internal API Platform 调试接口
- **THEN** 系统返回当前 topology 来源、配置 revision 或 hash、启用资源数量和配置错误摘要
