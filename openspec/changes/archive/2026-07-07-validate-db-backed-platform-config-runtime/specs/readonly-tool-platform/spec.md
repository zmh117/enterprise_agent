## ADDED Requirements

### Requirement: Internal API Platform uses DB-backed runtime snapshot when available
系统 SHALL 在启动 Internal API Platform 时优先从 PostgreSQL platform configuration 构造运行时 topology、resource binding 和 access policy。

#### Scenario: Database snapshot is active
- **WHEN** PostgreSQL 中存在启用的 environment、base、resource binding 和 access grant
- **THEN** Internal API Platform 使用 DB-backed snapshot 初始化 registry 和 access policy，并在 health/debug 输出中标记 `config.source=database`

#### Scenario: YAML file is configured but database snapshot exists
- **WHEN** PostgreSQL 中存在有效启用 topology 且同时配置了 `INTERNAL_PLATFORM_TOPOLOGY_FILE`
- **THEN** Internal API Platform MUST 使用 database snapshot，不得用 YAML 覆盖数据库配置

### Requirement: Invalid DB-backed configuration fails closed
系统 SHALL 在数据库配置存在但无效时暴露 degraded 状态，并 MUST NOT 静默回退到 YAML topology。

#### Scenario: Database configuration is invalid
- **WHEN** PostgreSQL 中存在启用 topology 但资源绑定缺少必要 endpoint、engine 或 secret reference
- **THEN** Internal API Platform 标记 `config.source=database-invalid`，返回配置错误摘要，并拒绝依赖该无效绑定的工具解析

#### Scenario: YAML fallback exists during invalid database configuration
- **WHEN** 数据库配置无效且同时配置了 YAML fallback 文件
- **THEN** Internal API Platform MUST 保持 `database-invalid` 状态，不得切换到 `yaml`

### Requirement: DB-backed runtime preserves read-only tool behavior
系统 SHALL 确保从 PostgreSQL 配置加载的工具平台运行时仍然执行只读、安全、限流、脱敏和审计策略。

#### Scenario: DB-backed database binding is queried
- **WHEN** Agent 通过 DB-backed resource binding 调用 `query_database`
- **THEN** Internal API Platform 仍执行只读 SQL 校验、车间表前缀校验、行数限制和响应摘要

#### Scenario: DB-backed Redis binding is queried
- **WHEN** Agent 通过 DB-backed resource binding 调用 `query_redis_get` 或 `query_redis_scan`
- **THEN** Internal API Platform 仍执行只读命令白名单、key namespace 限制和结果脱敏

#### Scenario: DB-backed Loki binding is queried
- **WHEN** Agent 通过 DB-backed resource binding 调用 `query_loki`
- **THEN** Internal API Platform 仍执行 selector、时间范围、行数和响应大小限制

### Requirement: Runtime configuration status is observable and secret-safe
系统 SHALL 在运行时健康检查或调试输出中暴露配置来源、revision/hash、资源数量、有效性和错误摘要，并 MUST NOT 泄漏真实密钥。

#### Scenario: Health reports DB-backed source
- **WHEN** Internal API Platform 使用数据库配置启动
- **THEN** `/health` 返回 `config.source=database`、revision 或 hash、resource count 和 valid 状态

#### Scenario: Health masks secret values
- **WHEN** resource binding 使用 `env:`、`vault:`、`kms:` 或其他 secret reference
- **THEN** `/health`、工具响应 metadata 和错误摘要不得包含解析后的 password、token 或 API key
