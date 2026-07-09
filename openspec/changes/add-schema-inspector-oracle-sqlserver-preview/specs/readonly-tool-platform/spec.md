## MODIFIED Requirements

### Requirement: Internal API Platform 必须提供只读 schema 目录
系统 SHALL 提供只读 schema directory 工具或 endpoint，用于按 `user_id`、`environment`、`base`、`workshop` 返回当前调用者可访问的数据表和字段摘要。该能力 MUST 通过 `SchemaInspectorFactory` 为已配置的 MySQL、Oracle、SQL Server binding 选择真实 inspector，并 MUST 复用 topology 解析、访问控制、workshop 前缀隔离和响应大小限制。

#### Scenario: 查询 workshop schema 目录
- **WHEN** Agent 为 `sanjiu/guanlan/GL001` 请求数据库 schema 目录
- **THEN** Internal API Platform 只返回该用户有权访问且表名符合 `GL001` workshop 前缀的表和字段摘要

#### Scenario: 查询 Oracle schema 目录
- **WHEN** Agent 请求已配置 Oracle binding 的 schema 目录
- **THEN** Internal API Platform 使用 Oracle inspector 返回有界的真实表和字段元数据，而不是 unsupported limitation

#### Scenario: 查询 SQL Server schema 目录
- **WHEN** Agent 请求已配置 SQL Server binding 的 schema 目录
- **THEN** Internal API Platform 使用 SQL Server inspector 返回有界的真实表和字段元数据，而不是 unsupported limitation

#### Scenario: schema 目录不泄露连接密钥
- **WHEN** schema directory 返回数据库元数据
- **THEN** 响应不得包含 host、port、username、password、DSN、tenant secret 或其它连接凭据

#### Scenario: schema 目录受大小限制
- **WHEN** 可访问表或字段数量超过配置上限
- **THEN** 平台返回 bounded 摘要并标记 `truncated=true` 或等价字段
