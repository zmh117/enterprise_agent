## ADDED Requirements

### Requirement: Tool calls go through the fixed standard MCP server
The system SHALL expose built-in read-only tools to the Agent Runtime only through the deployment-fixed `tool-mcp` Streamable HTTP server. The Runtime MUST NOT open database, Redis or Loki connections, and MUST NOT receive a dynamic MCP URL or use a private fake HTTP platform contract.

#### Scenario: Agent queries database evidence
- **WHEN** the Python Agent Runtime calls `query_database`
- **THEN** it invokes the fixed `tool-mcp` Tool identifier and `tool-mcp` performs the governed read through the resolved Database Resource Revision

#### Scenario: MCP URL is supplied by a request
- **WHEN** a Job payload, Agent configuration or Tool argument supplies a server URL
- **THEN** the system rejects or ignores the dynamic URL and uses only the deployment-fixed standard MCP server

### Requirement: tool-mcp image bundles Oracle Instant Client
若平台支持 Oracle thick/legacy 连接，系统 SHALL 仅在 `tool-mcp` 镜像中安装匹配架构的 Oracle Instant Client，并由 Oracle Resource Revision 的固定 Provider 契约选择 thick/legacy 模式；API、Worker 和 Agent Runtime 镜像 MUST NOT 包含该客户端。

#### Scenario: 构建 tool-mcp Oracle 镜像
- **WHEN** vendor 目录提供受支持的 Oracle Instant Client
- **THEN** `tool-mcp` 可以初始化 thick client，Worker/API/Runtime 镜像不包含该客户端

#### Scenario: 未提供 thick client
- **WHEN** Oracle Resource 要求 thick 模式但镜像没有客户端
- **THEN** 资源验证和 Tool Call 失败关闭且不回退到不兼容模式

### Requirement: tool-mcp resolves one current published resource per call
`tool-mcp` SHALL 在每次资源型 Tool Call 中按资源类型、Agent 显式提供且通过当前数据范围校验的 environment/base/workshop 及可选 placement，从 PostgreSQL 解析一个启用 Resource Identity 的最新 Published Revision。系统 MUST NOT 使用 Application Resource Mapping、Job-frozen Resource Revision、YAML runtime topology、第一候选或 Last Known Good 回退。

#### Scenario: 当前资源唯一可解析
- **WHEN** 调用目标匹配一个启用 Resource Identity 的最新 Published Revision
- **THEN** `tool-mcp` 使用该 Revision 的单次一致配置和 Secret 快照执行，并记录实际 Revision

#### Scenario: 当前资源零命中或多命中
- **WHEN** 调用目标未匹配资源或匹配多个候选
- **THEN** 该 Tool Call 在建立上游连接前失败关闭并返回安全错误分类

### Requirement: tool-mcp provides the read-only schema directory
系统 SHALL 由 `tool-mcp` 的 `get_schema_directory` Tool 按当前授权目标、唯一 Published Database Resource Revision 和资源内表范围返回只读、有界 schema 摘要；目标没有 Workshop 时不得要求虚拟前缀。

#### Scenario: 查询 workshop schema 目录
- **WHEN** Agent 为 `sanjiu/guanlan/GL001` 请求 schema 目录且当前数据库资源限制前缀为 `GL001_`
- **THEN** `tool-mcp` 只返回当前用户有权访问且符合资源限制的表和字段摘要

#### Scenario: schema 目录不泄露连接密钥
- **WHEN** schema directory 返回数据库元数据
- **THEN** 响应不得包含 host、port、username、password、DSN、tenant secret 或其它连接凭据

### Requirement: Resource Revision atomically publishes connection and data scope
DB、Redis、Loki Resource Draft SHALL 在同一个内容哈希中保存 Provider 连接配置、Secret references 和 `scope_bindings`，通过一次技术验证发布为一个不可变 Resource Revision。系统 MUST NOT 创建独立 Workshop Partition Policy、Loki Scope Policy 或另一套 Policy Revision 生命周期。

#### Scenario: 修改数据范围
- **WHEN** 管理员修改数据库表前缀、Redis namespace 或 Loki selector binding
- **THEN** 同一个 Resource Draft revision 增加、此前验证失效，并且必须重新验证后发布新的 Resource Revision

#### Scenario: 修改连接但保留范围
- **WHEN** 管理员从 Published Revision 创建 Draft 并轮换连接或 Secret reference
- **THEN** Draft 同时复制该 Revision 的 scope bindings，重新验证连接与范围后一次发布

### Requirement: Resource management UI edits connection and scope in one Draft
“平台治理 → 工具资源” SHALL 在同一 Resource Draft 中分区编辑连接和数据范围，并只提供一次保存、验证和发布生命周期；界面 MUST NOT 把数据范围表现为独立页面、独立发布物或 Application Resource Mapping。

#### Scenario: 新建数据库资源
- **WHEN** 管理员选择数据库 Provider、平台目标、Secret 和 Workshop 表前缀
- **THEN** 前端提交一个包含连接配置与 scope bindings 的 Resource Draft，且不提交 Secret 明文

#### Scenario: 查看发布版本
- **WHEN** 管理员查看已发布的 DB、Redis 或 Loki Resource Revision
- **THEN** 页面只读展示该版本的连接安全摘要和数据范围，并要求从该版本创建 Draft 后才能修改

### Requirement: Loki Draft discovers arbitrary exact labels before unified publish
Loki Resource Draft SHALL 在连接测试成功后有界发现当前可见 label keys，并允许管理员按此前已选精确条件逐级发现任意 key 的候选 values。平台 target 与 Loki label 不要求同名；管理员 MUST 将一个 Environment 或 Environment/Base 目标显式映射到一个或多个唯一 key 的精确 `key=value` AND 条件。

#### Scenario: 平台基地使用不同名称的 Loki labels
- **WHEN** 平台目标 `prod/guanlan` 的实际日志范围由 `cluster=cn-prod-01`、`namespace=mes` 和 `app=edge-gateway` 标识
- **THEN** 管理员可逐级选择这些 key/value 并把生成的精确 selector 保存到同一个 Loki Resource Draft

#### Scenario: 提交任意 selector 语法
- **WHEN** Draft 包含任意 LogQL、OR、否定、正则、通配、重复 key、空 value 或未声明结构
- **THEN** 管理 API 在保存 Draft 时拒绝且不访问 Loki

## MODIFIED Requirements

### Requirement: 业务应用发布必须绑定具体 Resource Revision
业务应用发布 MUST NOT 绑定或保存 Resource Revision。工具资源保持独立发布；`tool-mcp` MUST 在每次 Tool Call 时按 Agent 提供且通过当前角色数据范围校验的目标、资源类型与可选 placement 解析唯一 Published Resource Revision，并记录实际版本。

#### Scenario: 资源发布新版本
- **WHEN** 某 Resource 发布新 revision 且旧 revision 已停用
- **THEN** 后续 Tool Call 只可解析当前可用且唯一的 revision，不修改既有 Job 的 MCP Tool Snapshot

#### Scenario: 应用尝试提交资源绑定
- **WHEN** Application Draft 或 Publish payload 包含 Resource Revision、slot 或 mapping
- **THEN** 系统拒绝旧字段且不保存兼容映射

### Requirement: Secret 缺失必须阻止相关资源而非回退
Redis、Loki 或 Database Published Revision 的 Secret 无法解析时，系统 MUST 只让依赖该 Revision 的验证或 Tool Call 失败关闭；MUST NOT 使用环境变量、空值、旧 Secret、旧 Revision 或 Last Known Good 回退。

#### Scenario: Redis 密码 Secret 被禁用
- **WHEN** `tool-mcp` 在单次调用中无法解析 Redis `password_ref`
- **THEN** Tool Call 返回安全配置错误且不访问 Redis

### Requirement: Loki diagnostics shall expose bounded label discovery
系统 SHALL 由 `tool-mcp` 提供受限的 Loki label 诊断能力，用于列出当前授权目标在指定时间窗口内可见的 label 名称。

#### Scenario: 查询可见 labels
- **WHEN** 授权用户请求指定 environment/base/workshop 的 Loki labels
- **THEN** `tool-mcp` 返回 bounded label 名称列表、tenant 信息是否已配置、时间窗口和 truncated 标记

#### Scenario: label 查询超出限制
- **WHEN** 请求的时间窗口或响应大小超过平台限制
- **THEN** `tool-mcp` SHALL 拒绝或截断响应并返回可审计错误分类

### Requirement: Loki diagnostics shall expose bounded label values
系统 SHALL 由 `tool-mcp` 提供受限的 Loki label values 诊断能力，用于列出允许 label 的候选值，帮助确认服务名、job 名或 container 名是否存在。

#### Scenario: 查询允许 label 的 values
- **WHEN** 授权用户请求允许 label 的 values
- **THEN** `tool-mcp` 返回 bounded values、label 名称、时间窗口、truncated 标记和资源摘要

#### Scenario: 查询不允许 label
- **WHEN** 用户请求未在 allowlist 中的 label values
- **THEN** `tool-mcp` MUST 拒绝请求并说明 label 不允许

### Requirement: Database query tool is read-only
The system SHALL allow database tool execution only for policy-approved read operations against the unique current Published Database Resource Revision resolved for the Tool Call. It MUST reject insert, update, delete, DDL, privileged, unsafe, unparseable, multi-statement or out-of-scope queries before accessing the data source, and SHALL apply dialect-aware table restrictions to every physical table reference.

#### Scenario: Select query is approved
- **WHEN** Agent calls `query_database` with a policy-approved read query whose every table matches the resolved Resource restrictions
- **THEN** `tool-mcp` executes it through the exact resolved Revision and returns a bounded, summarized result

#### Scenario: Mutating query is rejected
- **WHEN** Agent calls `query_database` with an insert, update, delete, DDL or privileged operation
- **THEN** the system rejects the request and records the rejected Tool Call without sending it to the real database

#### Scenario: Query crosses resource table scope
- **WHEN** a scoped query references any table outside the resolved Resource restrictions
- **THEN** `tool-mcp` rejects the whole query before opening or using the upstream connection

### Requirement: Redis tools are read-only
The system SHALL allow Redis evidence collection only through approved GET and bounded SCAN operations against the unique current Published Redis Resource Revision resolved for the Tool Call. GET keys and SCAN patterns MUST begin with an allowed complete namespace prefix from that Revision, and all mutation, script, regular-expression, cross-namespace or prefix-leading-wildcard operations MUST be rejected before accessing Redis.

#### Scenario: Redis key is read
- **WHEN** Agent calls `query_redis_get` for a complete key beginning with an allowed namespace prefix
- **THEN** `tool-mcp` returns the masked bounded value summary and records the exact Resource Revision

#### Scenario: Redis mutation is requested
- **WHEN** Agent requests Redis deletion, mutation, expiration, flush or scripting
- **THEN** the system rejects the request and does not forward it to Redis

#### Scenario: Redis scan is outside namespace
- **WHEN** Agent submits a regex, prefix-leading wildcard or a pattern outside all allowed complete namespace prefixes
- **THEN** `tool-mcp` rejects the SCAN before contacting Redis

### Requirement: Loki queries are bounded
The system SHALL constrain Loki queries by the unique current Published Loki Resource Revision, its tenant and mandatory selector configuration, plus allowed diagnostic filters, time range, query size and result size. Mandatory selector conditions MUST be injected server-side and MUST NOT be overridden, removed or widened by the Agent.

#### Scenario: Loki query is within limits
- **WHEN** Agent calls `query_loki` with allowed diagnostic filters and a bounded time range
- **THEN** `tool-mcp` combines them with the Resource Revision's mandatory selector, returns a bounded log summary and records selector metadata

#### Scenario: Loki query exceeds limits
- **WHEN** Agent requests a disallowed label, conflicts with a mandatory key, submits arbitrary LogQL, or exceeds time or result limits
- **THEN** `tool-mcp` rejects or truncates according to policy and records the decision

#### Scenario: Workshop target uses broader resource scope
- **WHEN** a Job target contains a Workshop but the resolved Loki Resource is scoped to Environment or Base
- **THEN** `tool-mcp` uses exactly the Resource Revision's selector and does not infer a Workshop, replica or placement label

### Requirement: Tool platform resolves secrets only in infrastructure layer
系统 SHALL 仅在拥有外部连接的基础设施适配器中解析 `secret://platform/<code>`。`tool-mcp` 只在建立 DB、Redis、Loki 连接时解析对应 Secret；File Service 只在其 MinIO 存储适配器中解析 MinIO Secret。Agent、模型、Runtime、File Worker、MCP Tool 参数与响应、Job、Resource Revision、审计和业务领域服务 MUST NOT 接收或保存原始 Secret。

#### Scenario: Database tool uses platform secret ref
- **WHEN** 已发布数据库 revision 的 `password_ref` 为 `secret://platform/order_db_password`
- **THEN** `tool-mcp` 数据库基础设施适配器在创建受限连接前解析该 Secret
- **AND** 其他层只看见 reference 和 configured 状态

#### Scenario: File Service uses MinIO secret ref
- **WHEN** File Service 配置引用有效平台 MinIO Secret
- **THEN** 只有 MinIO 基础设施适配器获得解密值
- **AND** File MCP、Runtime 和 File Worker 看不到原始凭据

#### Scenario: Secret value appears in tool result
- **WHEN** 上游结果或异常意外包含 credential
- **THEN** 服务必须在返回、持久化或发送给模型前脱敏

#### Scenario: Unsupported provider reference appears
- **WHEN** Published Resource Revision 包含新的 `env:`、`vault:` 或 `kms:` 引用
- **THEN** 资源解析必须失败关闭，不得尝试兼容回退

### Requirement: DB-backed resource bindings preserve read-only guardrails
系统 SHALL 确保每次 Tool Call 解析的唯一 Published DB、Redis 或 Loki Resource Revision 继续执行只读、安全、限流、脱敏和审计策略；运行时不得使用名称默认值、最近父级、旧 Revision 或第一候选回退。

#### Scenario: Published Database Resource enables query_database
- **WHEN** 当前目标唯一解析到一个 Published Database Resource Revision
- **THEN** `query_database` 执行只读 SQL、全部表引用范围、超时、行数和字节限制

#### Scenario: Published Redis Resource enables scan
- **WHEN** 当前目标唯一解析到一个含 namespace 限制的 Published Redis Resource Revision
- **THEN** `query_redis_scan` 执行完整 key prefix、迭代、数量和结果脱敏限制

#### Scenario: Published Loki Resource enables query
- **WHEN** 当前目标唯一解析到一个含 tenant 和 selector 限制的 Published Loki Resource Revision
- **THEN** `query_loki` 执行强制 selector、允许附加过滤、时间窗和响应限制

#### Scenario: Target has multiple matches
- **WHEN** 一个资源类型、目标和 placement 产生多个 Published Resource 候选
- **THEN** `tool-mcp` 失败关闭且不访问任何候选上游

### Requirement: Tool responses are bounded before persistence
The system SHALL persist only bounded safe summaries of `tool-mcp` request and response data.

#### Scenario: Large tool response is returned
- **WHEN** a Tool result is larger than the configured response or persistence limit
- **THEN** `tool-mcp` rejects the oversized MCP result or the persistence path stores a bounded truncated summary according to the Tool contract

#### Scenario: Sensitive tool response is returned
- **WHEN** an upstream response contains sensitive fields or credential-like values
- **THEN** the system masks or omits those values before returning MCP content or writing Tool Call and audit summaries

### Requirement: Loki diagnostics must remain read-only and bounded
`tool-mcp` SHALL provide Loki runtime diagnostic Tools only as read-only, bounded requests using the unique current Published Loki Resource Revision and its mandatory selector. Management-time Resource Draft testing MUST use a separate authenticated control-plane contract and MUST NOT bypass runtime selector policy.

#### Scenario: Bounded runtime label diagnostics
- **WHEN** Agent requests allowed Loki labels or label values through `tool-mcp`
- **THEN** the service applies the mandatory selector, returns only bounded diagnostic summaries and records the access decision

#### Scenario: Management label discovery
- **WHEN** an authorized administrator discovers labels while testing a Loki Resource Draft
- **THEN** the platform uses the separate bounded management endpoint and does not add that endpoint to the Agent Tool Catalog

#### Scenario: Disallowed diagnostic selector
- **WHEN** a runtime diagnostic request includes a disallowed selector label or exceeds configured limits
- **THEN** `tool-mcp` rejects the request with a safe non-secret error summary

### Requirement: Tool platform shall expose actionable empty-result metadata
`tool-mcp` SHALL distinguish an empty Loki result from upstream failure and provide safe metadata that helps determine whether the likely cause is tenant, label, selector, keyword or time-window mismatch.

#### Scenario: Empty Loki result
- **WHEN** a Loki query succeeds but returns no streams or no log lines
- **THEN** `tool-mcp` returns `line_count=0`, stream count, selector metadata, time-window metadata and safe hints instead of treating the request as an upstream failure

#### Scenario: Loki upstream unavailable
- **WHEN** Loki is unreachable or returns retryable upstream errors
- **THEN** `tool-mcp` classifies the result as retryable upstream failure and does not return misleading empty-result hints

### Requirement: DB-backed runtime preserves read-only tool behavior
系统 SHALL 确保 `tool-mcp` 从 PostgreSQL 解析 Published Resource Revision 后仍执行只读、安全、限流、脱敏和审计策略。

#### Scenario: DB-backed database resource is queried
- **WHEN** Agent 调用 `query_database` 且当前目标唯一解析到数据库资源
- **THEN** `tool-mcp` 仍执行只读 SQL 校验、表范围校验、行数限制和响应摘要

#### Scenario: DB-backed Redis resource is queried
- **WHEN** Agent 调用 `query_redis_get` 或 `query_redis_scan` 且当前目标唯一解析到 Redis 资源
- **THEN** `tool-mcp` 仍执行只读命令白名单、key namespace 限制和结果脱敏

#### Scenario: DB-backed Loki resource is queried
- **WHEN** Agent 调用 `query_loki` 且当前目标唯一解析到 Loki 资源
- **THEN** `tool-mcp` 仍执行 selector、时间范围、行数和响应大小限制

### Requirement: Tool platform consumes DB-backed runtime config
系统 SHALL 允许 `tool-mcp` 的超时、行数、Loki 限制和 schema directory 限制等有类型运行参数从 DB-backed runtime config 读取；只有对应配置没有数据库值时才使用受控 env/default 值，资源连接事实 MUST 始终来自 Published Resource Revision。

#### Scenario: DB config sets Loki line limit
- **WHEN** runtime config 中为 `tool-mcp` 配置 `LOKI_MAX_LINES=200`
- **THEN** Loki 查询限制使用该值

#### Scenario: DB config value is absent
- **WHEN** 指定参数没有 DB-backed value
- **THEN** `tool-mcp` 使用该定义的 env/default 值且不改变资源解析来源

### Requirement: Tool Call 必须校验精确代码实现
Agent Runtime 和 `tool-mcp` MUST 在构建和执行 Tool Call 时校验 Job 冻结的 MCP server code、Tool identifier 与 schema hash 精确匹配当前代码 Manifest；不得仅凭工具名称相似即执行，也不得要求已删除的 Tool Release、Handler Version 或 Implementation Digest。

#### Scenario: 当前实现精确匹配
- **WHEN** Job Snapshot 的 server code、Tool identifier 和 schema hash 均与当前代码 Manifest 一致
- **THEN** 调用可以进入后续 Job、权限、资源和只读策略校验

#### Scenario: 当前 schema 漂移
- **WHEN** Tool 名称相同但 schema hash 不同
- **THEN** Runtime 或 `tool-mcp` 拒绝调用并记录安全 drift 错误，不自动使用当前实现

## REMOVED Requirements

### Requirement: Redis and Loki resolve at the base level
**Reason**: 该 Requirement 依赖已删除的 Application Resource Mapping、Job-frozen Resource Revision 和独立策略 Revision。
**Migration**: 使用新增的 `tool-mcp resolves one current published resource per call`，资源范围和 selector 保存在 Published Resource Revision 中。

### Requirement: Internal API Platform image bundles Oracle Instant Client
**Reason**: 独立镜像和服务已经退役。
**Migration**: 使用新增的 `tool-mcp image bundles Oracle Instant Client`。

### Requirement: Tool calls go through internal API platform
**Reason**: 旧 HTTP client、fake client 和功能开关均已删除。
**Migration**: 使用新增的 `Tool calls go through the fixed standard MCP server`。

### Requirement: Tool definitions are persisted
**Reason**: Tool Release、Handler Version 和 Implementation Digest 生命周期已经由代码 Manifest 与 publication 中的 identifier/schema hash 取代。
**Migration**: 使用既有 `内置只读工具实现必须来自代码 Manifest` 与标准 MCP runtime requirements。

### Requirement: Internal API Platform loads topology from PostgreSQL configuration
**Reason**: 不再存在独立 topology snapshot 服务或 YAML runtime fallback。
**Migration**: 每次调用直接从 PostgreSQL 唯一解析当前 Published Resource Revision。

### Requirement: 运行时必须原子热加载并保留 Last Known Good
**Reason**: 旧 activation generation 与 Application Last Known Good 已删除。
**Migration**: 单次 Tool Call 捕获一致 Revision/Secret 事实；不可用时仅该调用失败关闭。

### Requirement: Tool platform exposes configuration source in health and debug output
**Reason**: `tool-mcp` 不维护独立 topology generation，其健康检查只证明数据库与审计依赖就绪。
**Migration**: 资源版本和失败原因记录在实际 Tool Call 与 MCP Operation Audit 中。

### Requirement: Internal tool endpoints have fixed MVP paths
**Reason**: 旧私有 HTTP endpoints 已由标准 MCP Tool identifier 取代。
**Migration**: Runtime 只调用部署固定 `tool-mcp` 的标准 MCP `/mcp` transport。

### Requirement: Internal API Platform 必须提供只读 schema 目录
**Reason**: 独立平台服务已退役。
**Migration**: 使用新增的 `tool-mcp provides the read-only schema directory`。

### Requirement: Internal API Platform uses DB-backed runtime snapshot when available
**Reason**: 不再构建独立 topology/resource binding/access-policy snapshot，也不允许 YAML fallback。
**Migration**: 每次调用解析当前唯一 Published Resource Revision。

### Requirement: Invalid DB-backed configuration fails closed
**Reason**: 旧 service-level `database-invalid`/YAML fallback 状态不再存在。
**Migration**: 无效、缺失或歧义资源在单次验证或 Tool Call 中安全失败。

### Requirement: Runtime configuration status is observable and secret-safe
**Reason**: 旧 health 中的 topology source/revision/resource count 契约已删除。
**Migration**: 使用 API runtime config diagnostics、Resource 管理状态和实际 Tool Call/MCP Audit 证据，不在 `tool-mcp /health` 暴露资源清单。

### Requirement: Internal API Platform resolves Web-managed secrets
**Reason**: 独立平台 SecretResolver 所有者已退役。
**Migration**: 使用 `Tool platform resolves secrets only in infrastructure layer`，由 `tool-mcp` 的具体资源适配器解析。

### Requirement: Local Internal API Platform preserves the read-only tool contract
**Reason**: 本地 fake HTTP 平台和 client 已永久删除。
**Migration**: 本地与生产均使用标准 `tool-mcp`；测试通过受控 fixture 替代 fake evidence。

### Requirement: Local Loki evidence is bounded before persistence
**Reason**: 旧本地平台执行路径已删除。
**Migration**: 使用标准 `tool-mcp` 的 bounded result 与统一 Tool Call/MCP Audit 持久化边界。

### Requirement: Local platform errors follow existing retry classification
**Reason**: `HttpInternalApiClient` 已删除。
**Migration**: `tool-mcp` 和只读适配器返回统一安全错误分类。

### Requirement: Workshop is distinguished by Redis key prefix
**Reason**: 该 Requirement 把 namespace 保存到独立 Workshop Partition Policy Revision，与统一 Resource Revision 冲突。
**Migration**: Redis namespace prefixes 保存到同一 Resource Draft/Revision 的 `scope_bindings`，并由 `Redis tools are read-only` 在访问上游前执行。

### Requirement: Redis 和 Loki 必须由已发布 Resource Revision 提供
**Reason**: 该 Requirement 仍要求 Application binding 和 Job-frozen Resource Revision。
**Migration**: 每次 Tool Call 按目标解析当前唯一 Published Resource Revision。

### Requirement: Loki scope is enforced by environment and optional base selector policy
**Reason**: 独立 Loki Scope Policy 与同一 Resource Revision 发布连接和 selector 的决定冲突。
**Migration**: Loki selector conditions 保存于 Resource Revision 的 Environment/Environment-Base `scope_bindings`。

### Requirement: Loki Scope Selector Policy 必须使用精确 AND 条件
**Reason**: 不再创建独立 Scope Selector Policy。
**Migration**: 精确 AND 条件由 `Loki Draft discovers arbitrary exact labels before unified publish` 约束。

### Requirement: Scope Policy 必须独立验证并不可变发布
**Reason**: 范围不再拥有独立验证与发布生命周期。
**Migration**: 连接与范围在同一个 Resource Draft 中统一验证并发布。

### Requirement: Application Publication 必须冻结精确 Loki 资源与 Scope Policy
**Reason**: Application Resource Mapping 和 Job-frozen Resource Revision 已删除。
**Migration**: Application 只冻结 MCP Tool identifier/schema hash；资源在调用时唯一解析。

### Requirement: Resource 管理界面必须区分策略关联与应用运行绑定
**Reason**: 页面不再管理独立 Scope Policy 或 Application Resource Mapping。
**Migration**: 使用同一 Resource Draft 内的“连接配置”和“数据范围”分区。

### Requirement: Published Scope Policy 必须作为不可覆盖的运行时 selector
**Reason**: 不再存在 Published Scope Policy。
**Migration**: Published Resource Revision 的 mandatory selector binding 由 `Loki queries are bounded` 强制执行。

### Requirement: 工具平台只能解析 Job 固化的已发布资源
**Reason**: Job 不再固化 Handler 或 Resource Revision。
**Migration**: Job 固化 MCP Tool snapshot，资源由每次调用当前唯一解析。

### Requirement: Redis 和 Loki 必须使用发布 binding 的范围边界
**Reason**: 旧文本依赖 Job-frozen Resource Revision 与 Execution Scope binding。
**Migration**: 范围来自当前唯一 Published Resource Revision 的 `scope_bindings`，调用参数不得扩大。

### Requirement: Workshop Resource Partition Policy 必须版本化发布
**Reason**: 数据范围不再拥有独立 Policy Identity/Draft/Revision。
**Migration**: DB/Redis 范围与连接统一保存在 Resource Draft/Revision。

### Requirement: 数据库车间策略第一阶段必须恰好包含一个精确表名前缀
**Reason**: 不再存在数据库车间 Policy。
**Migration**: 精确表前缀保存到 Database Resource Revision 的目标 binding。

### Requirement: Schema Directory 必须按冻结的数据库前缀过滤
**Reason**: 前缀不再由 Job-frozen Policy Revision 提供。
**Migration**: `get_schema_directory` 使用当前解析 Resource Revision 的精确表前缀。

### Requirement: 数据库执行前必须验证所有物理表引用
**Reason**: 旧 Requirement 的范围来源是独立冻结 Policy。
**Migration**: 物理表校验由 `Database query tool is read-only` 以当前 Resource restrictions 执行。

### Requirement: Redis 车间策略必须保存一个或多个精确完整 namespace 前缀
**Reason**: 不再存在 Redis 车间 Policy。
**Migration**: namespace prefixes 保存到 Redis Resource Revision 的目标 binding。

### Requirement: Redis GET 和 SCAN 必须强制执行冻结前缀
**Reason**: 前缀不再来自冻结 Policy Revision。
**Migration**: `Redis tools are read-only` 使用当前解析 Resource Revision 的 namespace prefixes。

### Requirement: Redis 连接测试与 namespace 验证必须分离
**Reason**: 连接和范围必须在同一 Resource Draft 技术验证与发布周期中完成。
**Migration**: 验证器可分步骤检查连接与精确范围，但只产生一个 Resource Draft 验证结果。

### Requirement: 同一 Workshop 的所有 placement 必须共享一个策略语义
**Reason**: 不再存在 Application Mapping 或独立 Partition Policy Revision。
**Migration**: 每个 placement Resource Revision 自身携带完整连接和范围，调用按明确 placement 唯一解析。
