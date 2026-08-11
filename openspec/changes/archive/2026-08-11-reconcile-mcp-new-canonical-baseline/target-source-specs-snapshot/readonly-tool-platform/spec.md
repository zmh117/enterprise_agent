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
The system SHALL persist governance metadata for exact Built-in Tool Releases, Agent Tool Envelopes and Application Tool Allowlists, while the executable definition itself MUST originate from the code Manifest. Runtime tool preparation MUST use the exact Release ID, Handler Version and Implementation Digest frozen by the Job instead of a name-only enabled flag.

#### Scenario: Tool registry is loaded
- **WHEN** the Agent runtime prepares available tools for a job
- **THEN** it intersects the code Registry with the Job's exact Tool Releases, Application Allowlist, stable tool-use grants, target scope and resource-policy readiness

#### Scenario: Database attempts to define implementation
- **WHEN** a persisted tool record contains executable SQL, script, arbitrary URL or another dynamic implementation field
- **THEN** runtime rejects the record and never executes it

#### Scenario: legacy-v1 name-only binding is encountered after removal
- **WHEN** a new or recoverable Job lacks an exact Tool Execution Snapshot and only references `legacy-v1`
- **THEN** runtime rejects execution and reports a non-retryable migration error

### Requirement: Context search returns compact relevant graph context
The system SHALL provide tools to retrieve relevant ER and business-flow context for a user question without loading all available tables, fields, or flow nodes into the Agent prompt.

#### Scenario: Agent searches order context
- **WHEN** the user asks why an order is stuck in a business status
- **THEN** the context tools return only relevant ER tables, fields, enums, relationships, business-flow nodes, and flow edges for the question

### Requirement: Database query tool is read-only
The system SHALL allow database tool execution only for policy-approved read operations against the exact Resource Revision and Workshop Partition Policy Revision frozen by the Job. It MUST reject insert, update, delete, DDL, privileged, unsafe, unparseable, multi-statement or cross-prefix queries before accessing the data source, and SHALL apply dialect-aware table-prefix checks to every physical table reference.

#### Scenario: Select query is approved
- **WHEN** Agent calls `query_database` with a policy-approved read query whose every table matches the frozen Workshop prefix
- **THEN** the Internal API Platform executes it through the exact database Resource Revision and returns a bounded, summarized result

#### Scenario: Mutating query is rejected
- **WHEN** Agent calls `query_database` with an insert, update, delete, DDL or privileged operation
- **THEN** the system rejects the request and records the rejected tool call without sending it to the real database

#### Scenario: Query crosses workshop prefix
- **WHEN** a Workshop-scoped query references any table outside the frozen exact table prefix
- **THEN** the Internal API Platform rejects the whole query before opening or using the upstream connection

### Requirement: Redis tools are read-only
The system SHALL allow Redis evidence collection only through approved GET and bounded SCAN operations against the exact Resource Revision and Workshop Partition Policy Revision frozen by the Job. GET keys and SCAN patterns MUST begin with an allowed complete namespace prefix, and all mutation, script, regular-expression, cross-namespace or prefix-leading-wildcard operations MUST be rejected before accessing Redis.

#### Scenario: Redis key is read
- **WHEN** Agent calls `query_redis_get` for a complete key beginning with one frozen namespace prefix
- **THEN** the Internal API Platform returns the masked bounded value summary and records the exact resource and policy revision

#### Scenario: Redis mutation is requested
- **WHEN** Agent requests Redis deletion, mutation, expiration, flush or scripting
- **THEN** the system rejects the request and does not forward it to Redis

#### Scenario: Redis scan is outside namespace
- **WHEN** Agent submits `*GL001*`, a regex or a pattern outside all frozen complete namespace prefixes
- **THEN** the platform rejects the SCAN before contacting Redis

### Requirement: Loki queries are bounded
The system SHALL constrain Loki queries by the exact Resource Revision, tenant and mandatory Loki Scope Policy frozen by the Job, plus allowed diagnostic filters, time range, query size and result size. The mandatory selector MUST be injected server-side as exact AND conditions and MUST NOT be overridden, removed or widened by the Agent.

#### Scenario: Loki query is within limits
- **WHEN** Agent calls `query_loki` with allowed diagnostic filters and a bounded time range
- **THEN** the Internal API Platform combines them with the frozen mandatory selector, returns a bounded log summary and records selector metadata/hash

#### Scenario: Loki query exceeds limits
- **WHEN** Agent requests a disallowed label, conflicts with a mandatory key, submits arbitrary LogQL, or exceeds time or result limits
- **THEN** the system rejects or truncates according to policy and records the decision

#### Scenario: Workshop target uses base-level Loki policy
- **WHEN** a Job target contains a Workshop but its Loki Policy is scoped to Environment and Base
- **THEN** the platform uses exactly that Policy and does not infer a Workshop, replica or placement label

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
系统 SHALL 仅在 Internal API Platform infrastructure adapter 建立 DB、Redis、Loki 外部连接时解析 `secret://platform/<code>`。Agent、模型、Tool Service、Job、Resource Revision、审计和响应 MUST NOT 接收或保存原始 Secret。

#### Scenario: Database tool uses platform secret ref
- **WHEN** 已发布数据库 revision 的 `password_ref` 为 `secret://platform/order_db_password`
- **THEN** infrastructure adapter 在创建受限连接前解析该 Secret，其他层只看见 reference 和 configured 状态

#### Scenario: Secret value appears in tool result
- **WHEN** 上游结果或异常意外包含 credential
- **THEN** 平台必须在返回、持久化或发送给模型前脱敏

#### Scenario: Unsupported provider reference appears
- **WHEN** 运行时快照包含新的 `env:`、`vault:` 或 `kms:` 引用
- **THEN** 快照装载必须失败并保留 Last Known Good，不得尝试回退解析

### Requirement: DB-backed resource bindings preserve read-only guardrails
系统 SHALL 确保从 Job Execution Snapshot 加载的精确 DB、Redis、Loki Resource Revision 及策略 Revision 继续执行只读、安全、限流、脱敏和审计策略；运行时不得重新查询 latest Resource 或以名称、默认值、最近父级和第一候选回退。

#### Scenario: DB config enables query_database
- **WHEN** Job Snapshot 为数据库 slot 冻结了 Resource Revision 和 Workshop Partition Policy
- **THEN** `query_database` 仍执行只读 SQL、全部表引用前缀、超时、行数和字节限制

#### Scenario: Redis config enables scan
- **WHEN** Job Snapshot 为 Redis slot 冻结了 Resource Revision 和 namespace Policy
- **THEN** `query_redis_scan` 仍执行完整 key prefix、迭代、数量和结果脱敏限制

#### Scenario: Loki config enables query
- **WHEN** Job Snapshot 冻结了 Loki Resource 与 Scope Policy
- **THEN** `query_loki` 仍执行 tenant、强制 selector、允许附加过滤、时间窗和响应限制

#### Scenario: Snapshot has multiple matches
- **WHEN** 一个 slot、目标和 placement 产生多个 Resource Mapping
- **THEN** Internal API Platform 失败关闭且不访问任何候选上游

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
系统 SHALL 提供只读 schema directory 工具或 endpoint，用于按 Job 冻结的用户、业务目标、数据库 Resource Revision 和 Workshop Partition Policy 返回可访问的数据表和字段摘要。该能力 MUST 复用授权、方言感知的精确表前缀和响应大小限制；目标没有 Workshop 时不得要求虚拟前缀。

#### Scenario: 查询 workshop schema 目录
- **WHEN** Agent 为 `sanjiu/guanlan/GL001` 请求数据库 schema 目录且冻结前缀为 `GL001_`
- **THEN** Internal API Platform 只返回该用户有权访问且表名符合精确前缀的表和字段摘要

#### Scenario: 查询无 workshop 的 schema 目录
- **WHEN** Job 目标是没有 Workshop 层级的 Environment 或 Base
- **THEN** 平台按该目标冻结的 Resource 和访问范围返回目录，不构造默认 Workshop 前缀

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
Internal API Platform SHALL provide Loki runtime diagnostic operations only as read-only, bounded requests using the exact Resource Revision and mandatory Scope Policy frozen by the Job. Management-time label discovery SHALL use a separate authenticated Draft-test contract and MUST NOT be exposed as an Agent tool or bypass runtime selector policy.

#### Scenario: Bounded runtime label diagnostics
- **WHEN** Agent requests allowed Loki labels or label values through Internal API Platform
- **THEN** the platform applies the mandatory selector, returns only bounded diagnostic summaries and records the access decision

#### Scenario: Management label discovery
- **WHEN** an authorized administrator discovers labels after testing a Loki Resource Draft
- **THEN** the platform uses the separate bounded management endpoint and does not add that endpoint to the Agent Tool Catalog

#### Scenario: Disallowed diagnostic selector
- **WHEN** a runtime diagnostic request includes a disallowed selector label or exceeds configured limits
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

### Requirement: Local Internal API Platform preserves the read-only tool contract
The system SHALL treat the local development Internal API Platform as an implementation of the same read-only Internal API Platform contract used by Agent tools.

#### Scenario: Local platform uses fixed MVP endpoint paths
- **WHEN** `HttpInternalApiClient` calls the local platform
- **THEN** the local platform serves the same MVP paths as the real platform: `/tools/context/er`, `/tools/context/business-flow`, `/tools/loki/query`, `/tools/database/query`, `/tools/redis/get`, and `/tools/redis/scan`

#### Scenario: Local platform returns the standard envelope
- **WHEN** a local platform tool endpoint succeeds
- **THEN** it returns `summary`, `raw`, `truncated`, and `metadata` fields compatible with `HttpInternalApiClient`

#### Scenario: Local platform denies unsupported tools safely
- **WHEN** a configured Agent calls an endpoint that is not backed by a real local data source
- **THEN** the local platform returns a safe non-success error instead of fake evidence or a direct data-source call

### Requirement: Local Loki evidence is bounded before persistence
The system SHALL persist only bounded local Loki evidence summaries from the local Internal API Platform.

#### Scenario: Loki returns many log lines
- **WHEN** Loki returns more lines or bytes than the configured local platform summary limit
- **THEN** the local platform truncates the summary, marks the response as truncated, and avoids returning an unbounded raw payload for persistence

#### Scenario: Loki response contains sensitive-looking values
- **WHEN** log lines contain credential-like values or secrets
- **THEN** the local platform or downstream tool summary path masks or omits sensitive values before they are written to tool-call summaries or audit records

### Requirement: Local platform errors follow existing retry classification
The system SHALL format local platform errors so `HttpInternalApiClient` can classify them consistently with real Internal API Platform errors.

#### Scenario: Loki upstream timeout occurs
- **WHEN** the local platform cannot reach Loki due to timeout or transient upstream failure
- **THEN** it returns an HTTP status and safe body that `HttpInternalApiClient` maps to `RetryableExecutionError`

#### Scenario: Local policy rejects Loki input
- **WHEN** the local platform rejects a Loki query because the input violates policy
- **THEN** it returns an HTTP status and safe body that `HttpInternalApiClient` maps to a non-retryable policy or validation error

### Requirement: 第一版 Web 不动态创建 executable tools
系统 SHALL 允许管理端查看、启停和分配已有只读工具，但 MUST NOT 在本 change 中通过 Web 创建任意 HTTP、MCP、Shell、代码或 SQL executable adapter。

#### Scenario: 管理员打开工具分配页
- **WHEN** 管理员编辑默认诊断 Agent 的工具集合
- **THEN** 页面只列出系统已注册且可分配的只读工具

#### Scenario: 请求提交任意 HTTP 工具定义
- **WHEN** 客户端尝试通过本 change 的管理 API 创建新的动态 HTTP API 工具
- **THEN** 系统拒绝或不存在该能力，并要求使用后续专门的工具定义 change

### Requirement: 运行时工具集合包含角色业务能力交集
系统 SHALL 将最终暴露和执行的工具集合限制为“代码注册且只读、平台工具已启用、业务应用已装配、固定 Agent publication 已允许、当前用户有效角色已允许、当前应用数据范围已允许”的交集。任何一层拒绝或缺失 MUST 阻止工具暴露和执行。

#### Scenario: 角色允许但应用未装配
- **WHEN** 角色包含某只读能力但当前业务应用未装配该能力
- **THEN** 运行时不向模型暴露对应工具

#### Scenario: 应用和角色允许但 Agent 未分配
- **WHEN** 业务应用与角色均允许某能力但固定 Agent publication 未分配对应工具
- **THEN** 运行时不向模型暴露或执行该工具

#### Scenario: 所有只读层均允许
- **WHEN** 工具在所有注册、启用、应用、Agent、角色和数据范围检查中均被允许
- **THEN** 运行时可以向模型暴露并在每次调用前重新校验该工具

### Requirement: 角色授权中心不得授予写入型工具
系统 MUST 从角色可选能力目录排除写数据库、修改 Redis、执行 Shell、写文件或其它非只读工具。`platform-admin` 也不得通过角色页面绕过只读风险边界。

#### Scenario: 客户端伪造写工具能力
- **WHEN** 客户端向角色授权 API 提交写入型工具编码
- **THEN** 后端拒绝整个授权区修改并记录安全校验失败

### Requirement: 工具平台只能解析 Job 固化的已发布资源
每次工具调用 MUST 从服务端 Job 事实取得 Handler、Resource Revision 和 Execution Scope，且只能访问已安装、已发布、已绑定、已授权并有效装载的交集。

#### Scenario: 请求直接提交另一个 Resource ID
- **WHEN** Agent 或 HTTP Header 指定未绑定到该 Job 的资源
- **THEN** 平台必须拒绝且不打开连接

### Requirement: 数据库工具必须使用可验证只读账户和结构化 SQL 策略
已发布数据库 revision MUST 通过只读账户权限验证；查询 MUST 经 SQL AST 验证为单条 `SELECT` 或只读 `WITH`，并受 timeout、行数和字节数限制。

#### Scenario: 账户权限无法确定
- **WHEN** 数据库连接成功但验证器无法证明账号不具备写权限
- **THEN** Resource Draft 不得进入 VERIFIED 或 PUBLISHED

#### Scenario: 查询包含 PL/SQL 或存储过程
- **WHEN** 工具请求提交匿名块、CALL、EXEC 或多语句
- **THEN** 平台必须在执行前拒绝

### Requirement: Redis 和 Loki 必须使用发布 binding 的范围边界
Redis key prefix、Loki tenant/label selector 和查询上限 MUST 来自 Job 固化的 Published Resource Revision 与 Execution Scope，调用参数不得扩大范围。

#### Scenario: Redis 请求越过车间前缀
- **WHEN** 工具参数请求不属于当前 workshop 的 key
- **THEN** 平台必须拒绝并记录安全摘要

#### Scenario: Loki payload 覆盖 tenant
- **WHEN** 调用参数提交不同 tenant 或移除强制 label
- **THEN** 平台必须忽略或拒绝该扩大范围的值

### Requirement: Tool Call 必须校验精确代码实现
Agent Runtime 和 Internal API Platform MUST 在构建和执行 Tool Call 时校验 Job 冻结的 Tool Release ID、Handler Version 和 Implementation Digest 与当前代码 Registry 精确一致；不得仅凭工具名称或输入 Schema 相似即执行。

#### Scenario: 当前实现精确匹配
- **WHEN** Job Snapshot 的 Handler Version 和 Implementation Digest 均存在于当前代码 Registry
- **THEN** 调用可以进入后续生命周期、权限、资源和策略校验

#### Scenario: 当前实现 digest 漂移
- **WHEN** 工具名称和版本字符串相同但 Implementation Digest 不同
- **THEN** 运行时拒绝调用并记录 DRIFTED，不自动使用当前实现
