## ADDED Requirements

### Requirement: Internal API Platform resolves Web-managed secrets
系统 SHALL 允许 Internal API Platform 通过统一 SecretResolver 解析 Web-managed `secret://platform/<code>`，并只在 infrastructure 连接外部资源时获取明文。

#### Scenario: Database binding uses Web-managed password
- **WHEN** database resource binding 的 password 使用 `secret://platform/order_db_password`
- **THEN** Internal API Platform 在创建数据库连接时解析该 secret，API 响应、health、审计和工具摘要均不包含明文密码

#### Scenario: Secret is disabled
- **WHEN** resource binding 引用的 secret 被禁用
- **THEN** 对应工具调用失败为安全配置错误，不回退到旧 secret 或空密码

### Requirement: Tool platform consumes DB-backed runtime config
系统 SHALL 允许 Internal API Platform 的超时、行数、Loki 限制、schema directory 限制等运行参数从 DB-backed runtime config 读取，并保留 env fallback。

#### Scenario: DB config sets Loki line limit
- **WHEN** runtime config 中为 internal-api-platform 配置 `LOKI_MAX_LINES=200`
- **THEN** Loki 查询限制使用该值

#### Scenario: DB config is unavailable
- **WHEN** DB-backed runtime config 不可用
- **THEN** Internal API Platform 使用 env/default fallback，并在 health 输出中标记配置来源
