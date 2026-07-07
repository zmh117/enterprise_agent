# readonly-tool-platform Specification

## Purpose
TBD - created by archiving change add-readonly-diagnostic-agent-mvp. Update Purpose after archive.
## Requirements
### Requirement: Tool calls go through internal API platform
The system SHALL route Claude tool calls through internal API platform client contracts instead of direct database, Redis, Loki, ER, or business-flow clients inside the Agent runtime. When real internal tools are enabled, the runtime SHALL perform these calls through the configured HTTP Internal API Platform; when disabled, tests and local development MAY use the fake client with the same application contract.

#### Scenario: Agent queries database evidence
- **WHEN** the Claude runtime calls `query_database`
- **THEN** the tool adapter sends the request to the internal API platform database query endpoint and does not open a direct database connection from Agent runtime code

#### Scenario: Agent queries Redis evidence
- **WHEN** the Claude runtime calls `query_redis_get` or `query_redis_scan`
- **THEN** the tool adapter sends the request to the internal API platform Redis endpoint and does not open a direct Redis connection from Agent runtime code

#### Scenario: Real HTTP client is selected
- **WHEN** `FEATURE_REAL_INTERNAL_TOOLS=true`
- **THEN** the API and worker runtime use `HttpInternalApiClient` for read-only tools instead of `FakeInternalApiClient`

#### Scenario: Fake client remains available
- **WHEN** `FEATURE_REAL_INTERNAL_TOOLS=false` or test runtime builds a container
- **THEN** the runtime uses `FakeInternalApiClient` and preserves deterministic local test behavior

### Requirement: Tool definitions are persisted
The system SHALL persist tool definitions, connector configuration metadata, data source registry entries, and enablement status needed for later web-based configuration.

#### Scenario: Tool registry is loaded
- **WHEN** the Agent runtime prepares available tools for a job
- **THEN** it loads enabled tool definitions and connector metadata from PostgreSQL-backed configuration

### Requirement: Context search returns compact relevant graph context
The system SHALL provide tools to retrieve relevant ER and business-flow context for a user question without loading all available tables, fields, or flow nodes into the Agent prompt.

#### Scenario: Agent searches order context
- **WHEN** the user asks why an order is stuck in a business status
- **THEN** the context tools return only relevant ER tables, fields, enums, relationships, business-flow nodes, and flow edges for the question

### Requirement: Database query tool is read-only
The system SHALL allow database tool execution only for policy-approved read operations and MUST reject insert, update, delete, DDL, privileged, or unsafe statements before forwarding the request. The Internal API Platform MUST also enforce read-only policy before touching the real data source.

#### Scenario: Select query is approved
- **WHEN** Agent calls `query_database` with a policy-approved read query
- **THEN** the internal API platform executes the query through the database gateway and returns a bounded, summarized result

#### Scenario: Mutating query is rejected
- **WHEN** Agent calls `query_database` with an insert, update, delete, DDL, or privileged operation
- **THEN** the system rejects the request and records the rejected tool call without sending an unsafe operation to the real database

### Requirement: Redis tools are read-only
The system SHALL allow Redis evidence collection only through approved get and bounded scan operations and MUST reject delete, set, expire, flush, or script execution operations before forwarding the request. The Internal API Platform MUST also enforce Redis read-only policy before touching the real Redis source.

#### Scenario: Redis key is read
- **WHEN** Agent calls `query_redis_get` for an approved key pattern
- **THEN** the internal API platform returns the masked value summary and records the access

#### Scenario: Redis mutation is requested
- **WHEN** Agent requests Redis deletion, mutation, expiration, flush, or scripting
- **THEN** the system rejects the request because MVP tools are read-only and does not forward the mutation to the real Redis source

### Requirement: Loki queries are bounded
The system SHALL constrain Loki queries by allowed tenant, allowed selector labels, time range, query size, and result size before executing the request. The Internal API Platform MUST also enforce Loki tenant, selector, time range, and result-size limits before querying the real Loki source.

#### Scenario: Loki query is within limits
- **WHEN** Agent calls `query_loki` with an allowed selector and time range
- **THEN** the internal API platform returns a bounded log summary and records the query metadata

#### Scenario: Loki query exceeds limits
- **WHEN** Agent calls `query_loki` with a disallowed selector, excessive time range, or excessive result size
- **THEN** the system rejects or truncates the request according to policy and records the decision

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

### Requirement: Internal tool endpoints have fixed MVP paths
The system SHALL map each MVP read-only tool to a fixed Internal API Platform HTTP endpoint.

#### Scenario: Context endpoints are called
- **WHEN** Agent calls `get_er_context` or `get_business_flow_context`
- **THEN** the HTTP client calls `/tools/context/er` or `/tools/context/business-flow` with the project code and query text

#### Scenario: Evidence endpoints are called
- **WHEN** Agent calls `query_loki`, `query_database`, `query_redis_get`, or `query_redis_scan`
- **THEN** the HTTP client calls the matching `/tools/loki/query`, `/tools/database/query`, `/tools/redis/get`, or `/tools/redis/scan` endpoint

### Requirement: Tool responses are bounded before persistence
The system SHALL persist only bounded safe summaries of Internal API Platform request and response data.

#### Scenario: Large platform response is returned
- **WHEN** the internal platform returns a response larger than the configured tool summary limit
- **THEN** the system stores a truncated summary and marks the summary as truncated where supported

#### Scenario: Sensitive platform response is returned
- **WHEN** the internal platform response contains sensitive fields or credential-like values
- **THEN** the system masks or omits those values before writing tool-call summaries or audit payloads

### Requirement: Internal API Platform 必须提供只读 schema 目录
系统 SHALL 提供只读 schema directory 工具或 endpoint，用于按 `user_id`、`environment`、`base`、`workshop` 返回当前调用者可访问的数据表和字段摘要。该能力 MUST 复用 topology 解析、访问控制、workshop 前缀隔离和响应大小限制。

#### Scenario: 查询 workshop schema 目录
- **WHEN** Agent 为 `sanjiu/guanlan/GL001` 请求数据库 schema 目录
- **THEN** Internal API Platform 只返回该用户有权访问且表名符合 `GL001` workshop 前缀的表和字段摘要

#### Scenario: schema 目录不泄露连接密钥
- **WHEN** schema directory 返回数据库元数据
- **THEN** 响应不得包含 host、port、username、password、DSN、tenant secret 或其它连接凭据

#### Scenario: schema 目录受大小限制
- **WHEN** 可访问表或字段数量超过配置上限
- **THEN** 平台返回 bounded 摘要并标记 `truncated=true` 或等价字段

### Requirement: 数据库网关必须返回模型可停止的结构化限制结果
系统 SHALL 对表不存在、字段不存在、跨 workshop 前缀、无可用 schema、非 SELECT、空 schema directory 等无法继续诊断的情况返回安全、结构化、可审计的错误摘要。摘要 MUST 让 Agent 能区分“换一个已知字段继续查”和“停止并报告证据不足”。

#### Scenario: 查询未出现在 schema 中的表
- **WHEN** Agent 请求查询未出现在当前 workshop schema 目录中的表
- **THEN** 平台返回结构化错误摘要，指示该表不可用于当前目标，并建议使用 schema directory 或停止诊断

#### Scenario: 查询不存在字段
- **WHEN** Agent 请求查询目标表中不存在的字段
- **THEN** 平台返回结构化错误摘要，包含安全字段限制说明，而不是未脱敏数据库原始错误

#### Scenario: 空 schema directory
- **WHEN** 当前目标没有任何可访问表或字段
- **THEN** 平台返回空目录和明确限制原因，使 Agent 能产出“不具备诊断证据”的报告

### Requirement: Loki diagnostics must remain read-only and bounded
Internal API Platform SHALL provide Loki diagnostic operations only as read-only, bounded requests and MUST apply the same tenant, selector label, time range, response size, redaction, and access-control policies used by `query_loki`.

#### Scenario: Bounded label diagnostics
- **WHEN** Agent or developer tooling requests Loki labels or label values through Internal API Platform
- **THEN** the platform returns only bounded diagnostic summaries and records the access decision

#### Scenario: Disallowed diagnostic selector
- **WHEN** a Loki diagnostic request includes a disallowed selector label or exceeds configured limits
- **THEN** the platform rejects the request with a safe non-secret error summary

### Requirement: Tool platform shall expose actionable empty-result metadata
Internal API Platform SHALL distinguish an empty Loki result from platform failure and provide safe metadata that helps determine whether the likely cause is tenant, label, selector, keyword, or time-window mismatch.

#### Scenario: Empty Loki result
- **WHEN** a Loki query succeeds but returns no streams or no log lines
- **THEN** the platform returns `line_count=0`, `stream_count`, selector metadata, time-window metadata, and safe hints instead of treating the request as an upstream failure

#### Scenario: Loki upstream unavailable
- **WHEN** Loki is unreachable or returns retryable upstream errors
- **THEN** the platform classifies the result as retryable upstream failure and does not return misleading empty-result hints

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

