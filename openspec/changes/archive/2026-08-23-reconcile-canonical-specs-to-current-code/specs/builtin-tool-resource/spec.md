## MODIFIED Requirements

### Requirement: Platform validates caller identity from request context
`tool-mcp` MUST 使用 `X-Job-Id` 解析持久化 Job，并要求该 Job 当前为 `RUNNING`、runtime kind 受支持且协议版本匹配。请求 MUST 同时携带 invocation、内部用户、project、Agent Publication、Business Application Publication 和 correlation 的 Job-context Header；这些 Header 必须与持久化 Job 事实精确一致，只能用于一致性复核，不能授予权限。`tool-mcp` 当前 Job-context transport MUST NOT 要求或接受旧 Internal API Bearer Token、Handler 或 Capability 作为额外认证层。

#### Scenario: 缺少Job上下文
- **WHEN** `tool-mcp` 请求没有 `X-Job-Id` 或缺少任一必需 Job-context Header
- **THEN** 服务在列出或执行 Tool 前拒绝请求

#### Scenario: Unknown or non-running Job rejected
- **WHEN** supplied Job 不存在、不处于 `RUNNING`、Runtime 不受支持或协议版本不匹配
- **THEN** 平台拒绝请求并记录安全拒绝事实

#### Scenario: Header identity conflicts with Job
- **WHEN** invocation、用户、project 或 Publication Header 与持久化 Job 事实冲突
- **THEN** 平台拒绝请求且 MUST NOT 信任 Header 值

#### Scenario: 请求携带旧Internal API身份
- **WHEN** 调用方只提供 Internal API Bearer Token、Handler 或 Capability 字段而没有完整 Job context
- **THEN** `tool-mcp` 拒绝请求且不启动旧兼容认证路径

### Requirement: Database gateway supports MySQL, SQL Server, and Oracle
The system SHALL execute read-only queries against MySQL, SQL Server, and Oracle engines through a common resource-revision contract. PostgreSQL business data sources MUST NOT be published until a code-owned PostgreSQL provider implementation and dialect policy are present.

#### Scenario: Query routes to base engine
- **WHEN** a Job-bound database revision for base `guanlan` declares `mysql`
- **THEN** the gateway executes through the MySQL driver and dialect policy

#### Scenario: Unsupported engine is rejected
- **WHEN** a Draft declares an engine outside `mysql`/`sqlserver`/`oracle`
- **THEN** validation and publication are rejected with a non-retryable error

#### Scenario: PostgreSQL is advertised without runtime implementation
- **WHEN** provider metadata lists PostgreSQL but no code-owned provider implementation exists
- **THEN** the provider is unavailable and the Resource Draft cannot be published

## RENAMED Requirements

- FROM: `Python Runtime只使用固定标准MCP Tool Server`
- TO: `Python Runtime只使用部署固定的MCP Server集合`
