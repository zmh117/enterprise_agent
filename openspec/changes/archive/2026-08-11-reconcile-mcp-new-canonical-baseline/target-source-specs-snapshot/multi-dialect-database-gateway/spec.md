## Purpose

Define the read-only multi-dialect database gateway used by internal tools to query enterprise databases through a bounded and auditable platform layer.
## Requirements
### Requirement: Database gateway supports MySQL, SQL Server, and Oracle
The system SHALL execute read-only queries against MySQL, SQL Server, and Oracle engines through a common resource-revision contract. PostgreSQL business data sources MUST NOT be published until a PostgreSQL runtime Handler is implemented.

#### Scenario: Query routes to base engine
- **WHEN** a Job-bound database revision for base `guanlan` declares `mysql`
- **THEN** the gateway executes through the MySQL driver and dialect policy

#### Scenario: Unsupported engine is rejected
- **WHEN** a Draft declares an engine outside `mysql`/`sqlserver`/`oracle`
- **THEN** validation and publication are rejected with a non-retryable error

#### Scenario: PostgreSQL is advertised without runtime implementation
- **WHEN** provider metadata lists PostgreSQL but no installed runtime Handler exists
- **THEN** the provider is unavailable and the Resource Draft cannot be published

### Requirement: Only read-only statements are allowed across dialects
The system MUST parse SQL into an AST and allow only one `SELECT` or read-only `WITH` statement. It MUST reject DML, DDL, administrative statements, PL/SQL blocks, stored procedure calls and multiple statements for every dialect before execution.

#### Scenario: Mutating statement rejected
- **WHEN** a request contains `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `MERGE`, `CALL`, `EXEC` or equivalent AST nodes
- **THEN** the gateway rejects it before opening an execution cursor

#### Scenario: Multiple statements rejected
- **WHEN** parsing produces more than one statement
- **THEN** the gateway rejects the request as a policy violation

#### Scenario: Comment-obfuscated statement rejected
- **WHEN** comments, quoting or unusual whitespace attempt to conceal a forbidden operation
- **THEN** the AST policy still rejects the forbidden node

#### Scenario: Oracle PL/SQL block rejected
- **WHEN** an Oracle request contains `BEGIN...END`, `DECLARE` or a procedure invocation
- **THEN** the gateway rejects it as non-read-only

### Requirement: Queries are restricted to the target workshop table prefix
The system SHALL enforce that every table referenced by a workshop-scoped query uses that workshop's table prefix (e.g. `GL001_EBR_`). The system SHALL reject queries that reference tables without the required prefix or belonging to another workshop.

#### Scenario: Correct prefix accepted
- **WHEN** a query for workshop `GL001` references only tables like `GL001_EBR_order`
- **THEN** the gateway executes the query

#### Scenario: Missing prefix rejected
- **WHEN** a query for workshop `GL001` references `order_header` without the workshop prefix
- **THEN** the gateway rejects the query as a policy violation

#### Scenario: Cross-workshop access rejected
- **WHEN** a query for workshop `GL001` references `GL002_EBR_order`
- **THEN** the gateway rejects the query because it targets a different workshop

### Requirement: Result size is bounded per dialect
The system SHALL enforce statement/session timeout, maximum rows and maximum serialized bytes with a dialect-compatible mechanism. Oracle 11.2 MUST use a `ROWNUM`-compatible bound and MUST NOT depend on 12c `FETCH FIRST`.

#### Scenario: Limit applied for each dialect
- **WHEN** a query lacks an explicit safe bound
- **THEN** the gateway applies the configured MySQL, SQL Server or Oracle 11g-compatible maximum row limit

#### Scenario: Oversized response is truncated
- **WHEN** a result exceeds the configured maximum bytes
- **THEN** the gateway returns a bounded summary with `truncated=true`

### Requirement: Database errors are classified and desensitized
The system SHALL classify database connection timeouts and transient failures as retryable, classify policy and syntax rejections as non-retryable, and desensitize credentials or connection details in all error messages.

#### Scenario: Connection timeout is retryable
- **WHEN** a base database connection times out or fails transiently
- **THEN** the gateway returns a retryable error and no credentials appear in the error message

#### Scenario: Policy rejection is non-retryable
- **WHEN** a query is rejected for read-only or prefix policy violations
- **THEN** the gateway returns a non-retryable policy error

### Requirement: Oracle gateway supports thick client and legacy row limits
The system SHALL execute Oracle read-only queries using either thin or thick (Instant Client) connectivity as configured for the base, and SHALL apply a legacy-compatible row-limit mechanism when the base is marked for older Oracle compatibility.

#### Scenario: Thick mode uses Instant Client
- **WHEN** a base with engine `oracle` is configured for thick client mode and Instant Client is available in the process
- **THEN** the gateway connects using oracledb thick mode and executes the read-only query

#### Scenario: Legacy Oracle uses ROWNUM row limit
- **WHEN** a workshop-scoped Oracle query targets a base configured with legacy Oracle compatibility and no explicit row bound in SQL
- **THEN** the gateway enforces the maximum row limit using a `ROWNUM`-based rewrite rather than requiring `FETCH FIRST`

#### Scenario: Modern Oracle keeps FETCH FIRST
- **WHEN** a workshop-scoped Oracle query targets a base without legacy compatibility (default)
- **THEN** the gateway continues to enforce the row limit using `FETCH FIRST` (or equivalent modern syntax)

#### Scenario: Thick requested but client unavailable
- **WHEN** a base requires thick mode but Instant Client was not initialized successfully
- **THEN** the gateway returns a clear non-retryable configuration/upstream error and does not silently fall back to thin

### Requirement: 数据库资源必须使用可验证的专用只读账户
每个数据库 Resource Draft MUST 在 VERIFIED 前连接目标数据库并证明账号不具备写入或管理权限；连接失败、发现禁止权限或无法判断时必须阻止发布。

#### Scenario: 账号具有写表权限
- **WHEN** 验证发现账号可 INSERT、UPDATE、DELETE、DDL 或执行管理操作
- **THEN** Draft 必须验证失败并返回脱敏原因

#### Scenario: 账号只读且查询边界生效
- **WHEN** 权限检查、只读 session 能力和受限探针全部通过
- **THEN** Draft 可以进入 VERIFIED

### Requirement: Oracle 11g 必须使用结构化单实例 Thick 连接
Oracle 目标 MUST 为 11.2.0.4 单实例，使用 `host`、`port` 以及 `service_name`/`sid` 二选一；运行时 MUST 使用与容器架构一致的 64-bit Instant Client 19c 和 python-oracledb Thick，禁止 Thin 自动回退。

#### Scenario: Service Name 连接配置
- **WHEN** Oracle Draft 提供 host、port、service_name 且不提供 sid
- **THEN** 验证器构造受控连接参数，不接受任意 TNS descriptor

#### Scenario: SID 连接配置
- **WHEN** Oracle Draft 提供 host、port、sid 且不提供 service_name
- **THEN** 验证器使用 SID 模式连接

#### Scenario: Thick Client 未正确加载
- **WHEN** Instant Client 缺失、架构不匹配或只能使用 Thin
- **THEN** Oracle 验证和运行时必须失败，不得自动降级

#### Scenario: 本地没有真实 Oracle
- **WHEN** 仅单元测试或测试替身通过
- **THEN** Oracle Draft 不得进入 PUBLISHED，状态必须明确为等待真实连接验证
