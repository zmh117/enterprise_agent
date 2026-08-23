# builtin-tool-resource Specification

## Purpose
定义内置只读工具、资源版本、业务拓扑、数据库、Redis 和 Loki 的治理、发布、绑定与执行边界，确保模型不能绕过受管资源和只读策略。
## Requirements

<!-- Reconciled from mcp_new capability: `base-scoped-redis-loki` -->

### Requirement: tool-mcp resolves one current published resource per call
`tool-mcp` SHALL 在每次资源型 Tool Call 中按资源类型、Agent 显式提供且通过当前数据范围校验的 environment/base/workshop 及可选 placement，从 PostgreSQL 解析一个启用 Resource Identity 的最新 Published Revision。系统 MUST NOT 使用 Application Resource Mapping、Job-frozen Resource Revision、YAML runtime topology、第一候选或 Last Known Good 回退。
#### Scenario: 当前资源唯一可解析
- **WHEN** 调用目标匹配一个启用 Resource Identity 的最新 Published Revision
- **THEN** `tool-mcp` 使用该 Revision 的单次一致配置和 Secret 快照执行，并记录实际 Revision
#### Scenario: 当前资源零命中或多命中
- **WHEN** 调用目标未匹配资源或匹配多个候选
- **THEN** 该 Tool Call 在建立上游连接前失败关闭并返回安全错误分类

### Requirement: Redis and Loki errors are classified and desensitized
The system SHALL classify Redis and Loki connection timeouts and transient upstream failures as retryable, classify policy violations as non-retryable, and desensitize credentials in all error messages.

#### Scenario: Upstream timeout is retryable
- **WHEN** a base Redis or Loki upstream times out or returns a transient error
- **THEN** the platform returns a retryable error with no credentials in the message

### Requirement: Base Redis may use standalone or cluster mode
The system SHALL connect to a base Redis upstream using either standalone or cluster mode as declared in the base Redis binding. The default mode SHALL be standalone. Workshop key-prefix isolation and read-only command policy SHALL apply equally in both modes.

#### Scenario: Standalone mode uses single-node client
- **WHEN** a base Redis binding is configured with mode `standalone` (or omits mode)
- **THEN** the platform connects with a single-node Redis client using the configured host, port, db, and password

#### Scenario: Cluster mode uses cluster client
- **WHEN** a base Redis binding is configured with mode `cluster` and one or more startup nodes
- **THEN** the platform connects with a Redis Cluster client using those startup nodes and password, and does not rely on a logical `db` index

#### Scenario: Workshop prefix still enforced on cluster
- **WHEN** a Redis GET or SCAN for workshop `GL001` runs against a cluster-mode base
- **THEN** the platform still accepts only keys/patterns within the `GL001` namespace and rejects cross-workshop or unbounded patterns

#### Scenario: Cluster configuration missing nodes is rejected
- **WHEN** a base Redis binding declares mode `cluster` without usable startup nodes
- **THEN** the platform rejects the configuration (or resolution) with a clear non-retryable error before attempting upstream access

### Requirement: Redis 字段契约必须统一
Redis Resource MUST 使用 `host`、`port`、`database`、可选 `username`、`password_ref` 和受控 TLS 配置；管理 API、前端、验证器和运行时不得使用相互不兼容的 `db/user` 别名。

#### Scenario: 旧字段被导入
- **WHEN** import 遇到旧 `db` 或 `user` 字段
- **THEN** 导入器必须显式转换为 canonical 字段并生成 Draft，不能直接发布

### Requirement: Loki 字段契约必须统一
Loki Resource MUST 使用 `base_url`、可选 `tenant_id`、认证 Secret reference、超时和查询上限；管理 API、前端和运行时必须共享同一 schema。

#### Scenario: Draft 使用旧 tenant 字段
- **WHEN** 新建 Draft 直接提交歧义字段 `tenant`
- **THEN** API 必须拒绝或通过有审计的导入转换为 `tenant_id`

### Requirement: Secret 缺失必须阻止相关资源而非回退
Redis、Loki 或 Database Published Revision 的 Secret 无法解析时，系统 MUST 只让依赖该 Revision 的验证或 Tool Call 失败关闭；MUST NOT 使用环境变量、空值、旧 Secret、旧 Revision 或 Last Known Good 回退。
#### Scenario: Redis 密码 Secret 被禁用
- **WHEN** `tool-mcp` 在单次调用中无法解析 Redis `password_ref`
- **THEN** Tool Call 返回安全配置错误且不访问 Redis

### Requirement: Tool calls go through the fixed standard MCP server
The system SHALL expose built-in read-only tools to the Agent Runtime only through the deployment-fixed `tool-mcp` Streamable HTTP server. The Runtime MUST NOT open database, Redis or Loki connections, and MUST NOT receive a dynamic MCP URL or use a private fake HTTP platform contract.
#### Scenario: Agent queries database evidence
- **WHEN** the Python Agent Runtime calls `query_database`
- **THEN** it invokes the fixed `tool-mcp` Tool identifier and `tool-mcp` performs the governed read through the resolved Database Resource Revision
#### Scenario: MCP URL is supplied by a request
- **WHEN** a Job payload, Agent configuration or Tool argument supplies a server URL
- **THEN** the system rejects or ignores the dynamic URL and uses only the deployment-fixed standard MCP server

### Requirement: 内置只读工具实现必须来自代码 Manifest
系统 MUST 由 `tool-mcp` 从代码 Manifest 加载稳定 Tool Identifier、输入 Schema、模型描述、资源类型、只读限制和实现函数；数据库和管理 API MUST NOT 创建或覆盖实现，不再维护 Handler Version、Installation、Verification Evidence 或 Built-in Tool Release。

#### Scenario: 部署合法代码 Manifest
- **WHEN** 新部署包含格式合法且 Identifier/schema 未冲突的只读 MCP Tool Manifest
- **THEN** `tool-mcp` 注册该实现，Agent 管理目录可读取其非敏感定义

#### Scenario: 管理端提交动态实现
- **WHEN** 管理员尝试保存任意 HTTP、MCP、SQL、Shell、脚本、模板、函数或完整 URL 实现
- **THEN** 系统拒绝且不得保存或执行

### Requirement: 运行使用授权必须绑定稳定 Tool Identifier
系统 SHALL 以稳定 MCP Tool Identifier 作为 `tool:use` Grant 目标，并 MUST 在运行时校验 Agent Tool Envelope、Application Tool 子集、应用访问、数据范围和唯一资源解析；Grant MUST NOT 指定 Handler/Release/Server URL。

#### Scenario: 稳定工具授权命中 MCP Tool
- **WHEN** 用户具有某稳定 Identifier 的 `tool:use` 且 Job 冻结同一 identifier/schema hash
- **THEN** 授权进入资源和范围校验

#### Scenario: 应用未选择该工具
- **WHEN** 用户具有 Grant 但 Application Publication 未选择该 Tool
- **THEN** 系统拒绝且不向模型暴露该 Tool

### Requirement: 内置工具管理界面必须展示定义、证据、发布和生效差异
“平台治理 → 只读工具” SHALL 作为只读 MCP Tool Manifest 目录展示 identifier、描述、schema hash、资源类型、安装可用性和近期运行健康；MUST NOT 提供 reconcile、verify、publish、lifecycle 或动态实现编辑动作。

#### Scenario: 管理员查看工具目录
- **WHEN** 管理员具有工具目录读取权限
- **THEN** 页面显示代码 Manifest 和可用性，不显示已删除的 Handler/Release/Evidence 控件

<!-- Reconciled from mcp_new capability: `governed-tool-resource-management` -->

### Requirement: 工具资源必须通过草稿、验证和发布生命周期
DB、Redis、Loki Resource MUST 具有稳定身份、可编辑 Draft、技术验证结果和不可变 Published Revision；正常发布路径为 `DRAFT → VERIFIED → PUBLISHED`，不包含审核审批步骤。

#### Scenario: 发布已验证草稿
- **WHEN** 授权发布者发布字段、Secret、连接和只读检查均通过的 VERIFIED draft
- **THEN** 系统创建新的不可变 revision 并记录发布者、时间、校验摘要和审计

#### Scenario: 发布未验证草稿
- **WHEN** draft 尚未验证或验证结果已因内容变化失效
- **THEN** 系统必须拒绝发布

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

### Requirement: 已发布资源不得原地修改或普通删除
Draft 可以删除；Published Revision MUST NOT 被原地修改或通过普通 CRUD 物理删除，只能 disable 或 archive。

#### Scenario: 修改已发布 revision
- **WHEN** 管理员尝试修改 Published Revision 的连接字段或 Secret 引用
- **THEN** 系统必须拒绝，并要求从该版本创建新 Draft

### Requirement: 业务应用发布必须绑定具体 Resource Revision
业务应用发布 MUST NOT 绑定或保存 Resource Revision。工具资源保持独立发布；`tool-mcp` MUST 在每次 Tool Call 时按 Agent 提供且通过当前角色数据范围校验的目标、资源类型与可选 placement 解析唯一 Published Resource Revision，并记录实际版本。
#### Scenario: 资源发布新版本
- **WHEN** 某 Resource 发布新 revision 且旧 revision 已停用
- **THEN** 后续 Tool Call 只可解析当前可用且唯一的 revision，不修改既有 Job 的 MCP Tool Snapshot
#### Scenario: 应用尝试提交资源绑定
- **WHEN** Application Draft 或 Publish payload 包含 Resource Revision、slot 或 mapping
- **THEN** 系统拒绝旧字段且不保存兼容映射

### Requirement: 工具资源管理界面必须展示实际生效状态
“平台治理 → 工具资源” MUST 支持 DB、Redis、Loki 的列表、Draft 编辑、Secret 选择、测试、发布、disable/archive，并区分 draft、verified、published 和 disabled/archived 状态；MUST NOT 展示已删除的 effective generation 或 activation 状态。

#### Scenario: 管理员查看资源详情
- **WHEN** 资源新版本已发布但验证、Secret、驱动或最近 Tool Call 失败
- **THEN** 界面必须显示 Published Revision、验证结果和安全失败摘要，不能伪造独立 activation 或 Last Known Good

### Requirement: 全量资源重置必须使用四阶段维护命令
系统 MUST 提供 `resource-reset report/prepare/apply/verify`，只清理 DB、Redis、Loki 资源及 revision；Provider、Secret、身份、RBAC、应用、Job、Delivery 和审计必须保留。命令 MUST 不再处理 Application Resource Binding、Resource Mapping、runtime generation 或 activation 表。

#### Scenario: Prepare 后状态发生变化
- **WHEN** apply 前的对象清单 digest 与 prepare 结果不一致
- **THEN** apply 必须拒绝并要求重新 report/prepare

#### Scenario: 仍有运行中的资源依赖 Job
- **WHEN** 维护排空超时且仍存在运行任务
- **THEN** prepare 必须中止，不得强杀任务或继续删除资源

#### Scenario: 用户确认精确清单
- **WHEN** apply 再次展示 operation ID、备份引用和精确资源清单并得到明确确认
- **THEN** 系统在单个受控事务中清理资源，不修改应用或创建 blocked 映射状态

<!-- Reconciled from mcp_new capability: `loki-diagnostics` -->

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

### Requirement: Loki probe shall explain empty query results
系统 SHALL 提供 Loki selector probe 或等价诊断结果，用于解释指定 selector、keyword 和时间窗口为何没有命中日志。

#### Scenario: selector 无命中
- **WHEN** Loki 查询返回 `line_count=0`
- **THEN** 响应 summary SHALL 包含 selector、query、minutes、stream_count、line_count 和 empty result hints

#### Scenario: selector 有命中
- **WHEN** Loki probe 在指定时间窗口内命中日志流
- **THEN** 响应 summary SHALL 返回 stream_count、line_count 或可用样本摘要，并保持结果大小受限

### Requirement: Loki diagnostics shall preserve tenant and topology isolation
Loki 诊断 Tool SHALL 使用与真实 `query_loki` 相同的当前授权目标、唯一 Published Resource Revision、tenant、强制 selector 和访问控制。

#### Scenario: Workshop 目标诊断
- **WHEN** 用户请求 GL001 的 Loki 诊断
- **THEN** 平台 SHALL 使用该目标解析到的 Environment 或 Environment/Base selector binding
- **AND** 不从 Workshop code 自动推断、注入或放宽 Loki label

#### Scenario: tenant 错误
- **WHEN** Loki upstream 返回 tenant/auth 相关错误
- **THEN** 平台 SHALL 返回安全错误摘要和 retryable 分类
- **AND** 响应 MUST NOT 暴露认证 token 或 secret

<!-- Reconciled from mcp_new capability: `loki-scope-selector-policy` -->

### Requirement: Loki Resource 只允许 global 或 environment 连接范围
系统 SHALL 允许 Loki Resource Revision 声明 global scope 或一个精确 Environment scope，并 MUST NOT 把 Base、Workshop 或 cloud/edge placement 作为 Loki 连接资源范围。

#### Scenario: 当前统一 Loki
- **WHEN** 一个 Loki 实例采集多个 Environment 的日志
- **THEN** 管理员可把该 Resource Revision 发布为 global，并在同一 Revision 中为不同 Environment 保存独立 selector binding

#### Scenario: 每环境独立 Loki
- **WHEN** 某 Environment 使用自己的 Loki 实例
- **THEN** 管理员可把该 Resource Revision 发布为该精确 Environment scope

#### Scenario: 提交车间或 placement 范围
- **WHEN** Loki Resource Draft 提交 Workshop scope、cloud placement 或 edge placement
- **THEN** 系统拒绝配置

### Requirement: Loki 连接测试必须提供有界级联标签发现
管理员成功测试 Loki Resource Draft 的 URL、tenant、Secret、超时和连接后，系统 SHALL 在同一受控测试上下文中提供有界 label key 发现；选择 key 后 SHALL 允许按此前已选精确条件查询该 key 的有界 value 列表。

#### Scenario: 测试成功返回 label keys
- **WHEN** 授权管理员点击测试且 Loki 连接成功
- **THEN** API 返回去重、排序、截断标记和上限内的 label key 列表，不返回日志正文

#### Scenario: 级联查询 label values
- **WHEN** 管理员已选择 `customer=sanjiu-test1` 后查询下一个 key 的 values
- **THEN** 系统用该精确条件收窄有界发现请求并返回 value 列表

#### Scenario: 发现请求越界
- **WHEN** 请求包含任意 LogQL、正则、负向匹配、超出允许时间窗或超过数量/字节上限
- **THEN** 系统拒绝或截断并返回安全摘要

#### Scenario: 未通过连接测试直接发现
- **WHEN** Draft 内容变化导致测试证据失效或当前管理员没有有效测试上下文
- **THEN** 系统拒绝标签发现并要求重新测试

### Requirement: 标签发现结果不得成为隐式运行配置
标签 key/value 发现结果 SHALL 仅作为当前 Resource Draft 和测试会话的填写辅助证据；系统 MUST NOT 自动保存完整标签目录、自动创建 selector binding 或在运行时查询发现目录来扩大范围。

#### Scenario: 管理员关闭未保存页面
- **WHEN** 标签发现成功但管理员没有保存 Resource Draft
- **THEN** 系统不创建可发布 selector，发现缓存按受控期限失效

#### Scenario: Loki 后续出现新 label value
- **WHEN** Published Resource Revision 创建后 Loki 出现新的 label value
- **THEN** 既有 Revision 的 selector bindings 不自动改变

### Requirement: Loki 不得宣称 Workshop 或 placement 授权隔离
第一阶段 Loki 授权范围 SHALL 止于 Environment 和可选 Base；`role`、`replica`、`app`、`logtype` 只能作为受控诊断过滤，MUST NOT 被解释为用户角色、Resource Placement 或可靠 Workshop 身份。

#### Scenario: Job 目标包含 GL001
- **WHEN** Job 业务目标为某 Base 下 Workshop GL001
- **THEN** Loki 查询仍使用 Published Resource Revision 中该 Environment/Base 的强制 selector binding，不自动注入 `workshop=GL001` 或 `replica=GL001`

#### Scenario: 日志 label role 为 edge
- **WHEN** Loki 流包含 `role=edge`
- **THEN** 系统只把它作为采集侧诊断属性，不据此授予 edge 权限或改变 Resource Placement

### Requirement: 空结果健康必须与生命周期分离
系统 SHALL 监测 Published Resource Revision 中 Loki selector binding 的查询结果并可标记 `EMPTY` 或 `DEGRADED` 健康状态；长期零匹配 MUST NOT 自动 disable、archive、切换 binding 或放宽 selector。

#### Scenario: Published selector 长期零匹配
- **WHEN** 多次受控健康探测均被 Loki 接受但返回零流
- **THEN** 管理端显示 EMPTY/DEGRADED 和最后证据，运行时继续按原 selector 返回空结果

#### Scenario: Loki 上游不可用
- **WHEN** 健康探测因连接、认证或超时失败
- **THEN** 系统标记安全的上游健康错误，与“成功但为空”区分，并且不泄露 Secret

<!-- Reconciled from mcp_new capability: `multi-dialect-database-gateway` -->

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

<!-- Reconciled from mcp_new capability: `multi-dialect-schema-inspection` -->

### Requirement: SchemaInspectorFactory 必须按数据库引擎选择 inspector
系统 SHALL 提供统一的 `SchemaInspectorFactory`，根据 resolved resource binding 的数据库引擎返回 MySQL、Oracle 或 SQL Server schema inspector。应用服务 MUST 依赖 factory 契约，而不是自行分支或维护引擎 reader 字典。

#### Scenario: 为 Oracle 选择 inspector
- **WHEN** schema directory 请求解析到 engine 为 `oracle` 的 database binding
- **THEN** factory 返回 Oracle schema inspector，且不得回退到 MySQL、SQL Server 或 unsupported 实现

#### Scenario: 不支持的引擎被安全拒绝
- **WHEN** factory 收到未注册的数据库引擎
- **THEN** 系统返回明确的非重试配置错误或 limitation，不尝试使用其它方言

### Requirement: Oracle inspector 必须兼容 Oracle 11g
Oracle schema inspector SHALL 从固定的 Oracle 系统目录视图读取普通表和字段元数据，并 MUST 使用 Oracle 11g 可执行的限界语法。它 MUST NOT 依赖 `FETCH FIRST` 或 `OFFSET ... FETCH`。

#### Scenario: 预览 Oracle 11g schema
- **WHEN** 已授权用户请求 Oracle 11g binding 的 schema directory
- **THEN** inspector 使用 `ALL_TABLES`、`ALL_TAB_COLUMNS` 和 `ROWNUM` 兼容查询返回表名、字段名、数据类型和可空性

#### Scenario: Oracle owner 被限制
- **WHEN** database binding 配置了 schema/owner
- **THEN** inspector 只返回该 owner 下且符合 workshop 表前缀和搜索条件的普通表

### Requirement: SQL Server inspector 必须提供真实 schema 预览
SQL Server schema inspector SHALL 从 SQL Server 系统目录读取目标 database/schema 下的普通表和字段元数据，并返回与其它方言一致的 `SchemaDirectory`。

#### Scenario: 预览 SQL Server schema
- **WHEN** 已授权用户请求 engine 为 `sqlserver` 的 schema directory
- **THEN** inspector 返回目标 schema 下普通表的表名、字段名、数据类型和可空性

#### Scenario: SQL Server 默认使用 dbo
- **WHEN** SQL Server database binding 未配置 schema
- **THEN** inspector 将 `dbo` 作为默认 schema，且不返回其它 schema 的表

### Requirement: Schema 预览必须只读、有界且不泄露连接信息
所有 schema inspector MUST 只执行平台定义的系统目录只读查询，MUST 应用表数、每表字段数、workshop 表前缀和搜索条件限制，并 MUST 对响应和错误进行脱敏。schema 预览 MUST NOT 读取业务表样例行。

#### Scenario: 大型 schema 被截断
- **WHEN** 匹配的表或字段数量超过平台配置上限
- **THEN** inspector 仅返回允许范围内的元数据并标记 `truncated=true` 或等价限制信息

#### Scenario: 响应不包含连接凭据
- **WHEN** Oracle、SQL Server 或 MySQL schema inspector 返回成功或失败结果
- **THEN** 响应和审计摘要不包含 host、port、username、password、DSN、connect descriptor 或原始数据库错误

#### Scenario: 不读取业务数据
- **WHEN** 用户请求 schema 预览
- **THEN** inspector 只查询系统目录元数据，不执行针对业务表的样例数据查询

<!-- Reconciled from mcp_new capability: `oracle-instant-client-runtime` -->

### Requirement: tool-mcp image bundles Oracle Instant Client
若平台支持 Oracle thick/legacy 连接，系统 SHALL 仅在 `tool-mcp` 镜像中安装匹配架构的 Oracle Instant Client，并由 Oracle Resource Revision 的固定 Provider 契约选择 thick/legacy 模式；API、Worker 和 Agent Runtime 镜像 MUST NOT 包含该客户端。
#### Scenario: 构建 tool-mcp Oracle 镜像
- **WHEN** vendor 目录提供受支持的 Oracle Instant Client
- **THEN** `tool-mcp` 可以初始化 thick client，Worker/API/Runtime 镜像不包含该客户端
#### Scenario: 未提供 thick client
- **WHEN** Oracle Resource 要求 thick 模式但镜像没有客户端
- **THEN** 资源验证和 Tool Call 失败关闭且不回退到不兼容模式

### Requirement: Platform enforces environment/base/workshop access scope
The system SHALL enforce platform-side access scope against the actual Business Target Path: Environment, optional Base and optional Workshop. Authorization SHALL be independent of the Agent-side stable Tool Identifier permission, and Resource Placement (`cloud`/`edge`) MUST NOT be a user, group or role authorization dimension.

#### Scenario: In-scope request allowed
- **WHEN** a user authorized for `sanjiu/guanlan/GL001` issues a tool request for that exact target
- **THEN** the platform allows the request to proceed to exact publication, resource and policy resolution

#### Scenario: Environment leaf access
- **WHEN** an Environment has no Base or Workshop and the user is authorized for that Environment leaf
- **THEN** the platform evaluates the real Environment target without requiring placeholder scope grants

#### Scenario: Out-of-scope base rejected
- **WHEN** a user authorized only for one Environment issues a request targeting another Environment or an unauthorized Base
- **THEN** the platform rejects the request with a non-retryable authorization error

#### Scenario: Out-of-scope workshop rejected
- **WHEN** a user authorized for Workshop `GL001` issues a request targeting `GL002`
- **THEN** the platform rejects the request as unauthorized

#### Scenario: Placement differs within an authorized target
- **WHEN** a user authorized for GL001 invokes a tool whose Job Snapshot contains both cloud and edge resources for GL001
- **THEN** target authorization remains GL001; deterministic placement resolution may choose an allowed resource but cannot expand the target scope

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

### Requirement: Access decisions are audited without leaking secrets
The system SHALL audit access-control decisions (allow/deny) with the resolved target and caller, and SHALL NOT record credentials, connection details, or unbounded raw payloads.

#### Scenario: Denied access is audited
- **WHEN** the platform denies a request for being out of scope
- **THEN** it records an audit entry containing the caller, the requested environment/base/workshop, and the deny reason, without any secret material

### Requirement: 管理后台必须由统一身份与 RBAC 原子保护
系统 SHALL 将管理 Web、管理 API、统一身份、Web Session、RBAC 和业务应用控制面视为同一个管理面启停单元。管理面开启时 MUST 要求可解析的统一用户身份和授权；系统不得支持无身份或无 RBAC 的管理后台组合。

#### Scenario: 管理面开启
- **WHEN** `FEATURE_WEB_ADMIN=true`
- **THEN** 管理 Web 和管理 API 启用统一身份、Web Session 与 RBAC 校验
- **AND** 未认证调用方不能访问受保护管理资源

#### Scenario: 管理面关闭
- **WHEN** `FEATURE_WEB_ADMIN=false`
- **THEN** 系统不暴露管理 Web 和管理 API
- **AND** Channel ingress 与已发布 Agent Runtime 不因管理面关闭而自动停止

#### Scenario: 旧身份开关与管理面冲突
- **WHEN** `FEATURE_WEB_ADMIN=true` 但兼容期旧身份或业务应用控制面开关显式为 `false`
- **THEN** 系统拒绝启动并报告冲突配置
- **AND** 系统不得降级为无认证或不完整管理后台

### Requirement: 测试身份不得绕过生产访问控制
系统 MUST 在生产环境拒绝测试身份请求头适配器，无论该请求头由反向代理、客户端还是内部服务提供。

#### Scenario: 生产请求携带测试身份头
- **WHEN** 生产环境收到仅能由测试身份适配器识别的身份请求头
- **THEN** 系统不将其解析为已认证用户
- **AND** 系统按未认证请求拒绝并记录审计事件

### Requirement: 当前全部展开为明确范围
系统 SHALL 在保存授权时把“当前全部环境、基地或车间”展开为当时存在且操作者有权授予的明确资源 ID 集合，并 MUST NOT 提供包含未来新增资源的动态全部选项。

#### Scenario: 新基地在授权后创建
- **WHEN** 管理员保存当前全部基地后新增一个基地
- **THEN** 新基地不进入既有角色授权，除非管理员再次编辑并明确选择

### Requirement: 平台必须全局使用严格应用角色授权
系统 MUST 删除 `compatibility` 配置、执行分支和 fallback；缺少新 RBAC 数据时必须拒绝，不得自动迁移 `permission_policy` 或 `platform_access_grant` 的授权含义。

#### Scenario: 旧策略允许但新角色未授权
- **WHEN** 用户只有旧 permission policy 而没有业务应用角色
- **THEN** 系统必须拒绝创建或执行 Job

### Requirement: 平台必须保持双人管理员不变量
系统 MUST 始终保留至少两个已登录验证、启用且为人类身份的 `platform-admin` 成员；系统账号不计数。

#### Scenario: 禁用操作会只剩一名管理员
- **WHEN** 禁用用户或移除角色会使有效人类平台管理员少于两人
- **THEN** 系统必须在同一事务中拒绝操作

### Requirement: Placement must not be persisted in access grants
新的用户、组和角色数据范围 Grant MUST NOT 保存 cloud、edge、standalone、role label 或 replica 作为授权条件；任何提交此类条件的管理请求 MUST 被拒绝。

#### Scenario: Admin grants edge-only workshop access
- **WHEN** 管理员尝试创建只允许 GL001 edge 资源的用户数据 Grant
- **THEN** 系统拒绝并要求按逻辑 GL001 目标授权

#### Scenario: Existing scope is evaluated for both placements
- **WHEN** 用户拥有 GL001 的允许 Grant 且 Application Publication 为 GL001 配置两个 placements
- **THEN** 授权检查对两者使用相同 GL001 scope，实际 placement 仍由 Tool Call 解析和审计

### Requirement: Stable tool-use permission and data scope must both pass
运行时 MUST 同时要求调用者拥有稳定 Built-in Tool Identifier 的 `tool:use` Grant 和目标 Business Target Path 的允许范围；任一通过都不得替代另一项，也不得因 Grant 稳定而绕过精确 Release/Application 校验。

#### Scenario: Tool grant exists but target denied
- **WHEN** 用户可以使用 `query_redis_get` 但没有目标 GL002 的数据范围
- **THEN** 平台拒绝调用且不访问 Redis

#### Scenario: Target allowed but tool grant missing
- **WHEN** 用户可访问 GL001 但没有目标稳定 Tool Identifier 的使用权限
- **THEN** 模型不获得该工具，直接调用也被拒绝

<!-- Reconciled from mcp_new capability: `readonly-tool-platform` -->

### Requirement: Context search returns compact relevant graph context
The system SHALL provide tools to retrieve relevant ER and business-flow context for a user question without loading all available tables, fields, or flow nodes into the Agent prompt.

#### Scenario: Agent searches order context
- **WHEN** the user asks why an order is stuck in a business status
- **THEN** the context tools return only relevant ER tables, fields, enums, relationships, business-flow nodes, and flow edges for the question

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

### Requirement: tool-mcp provides the read-only schema directory
系统 SHALL 由 `tool-mcp` 的 `get_schema_directory` Tool 按当前授权目标、唯一 Published Database Resource Revision 和资源内表范围返回只读、有界 schema 摘要；目标没有 Workshop 时不得要求虚拟前缀。
#### Scenario: 查询 workshop schema 目录
- **WHEN** Agent 为 `sanjiu/guanlan/GL001` 请求 schema 目录且当前数据库资源限制前缀为 `GL001_`
- **THEN** `tool-mcp` 只返回当前用户有权访问且符合资源限制的表和字段摘要
#### Scenario: 查询无 workshop 的 schema 目录
- **WHEN** Job 目标是没有 Workshop 层级的 Environment 或 Base
- **THEN** `tool-mcp` 按该目标唯一解析的 Resource Revision 和当前访问范围返回目录，不构造默认 Workshop 前缀
#### Scenario: schema 目录不泄露连接密钥
- **WHEN** schema directory 返回数据库元数据
- **THEN** 响应不得包含 host、port、username、password、DSN、tenant secret 或其它连接凭据
#### Scenario: schema 目录受大小限制
- **WHEN** 可访问表或字段数量超过配置上限
- **THEN** `tool-mcp` 返回 bounded 摘要并标记 `truncated=true` 或等价字段

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

### Requirement: 数据库工具必须使用可验证只读账户和结构化 SQL 策略
已发布数据库 revision MUST 通过只读账户权限验证；查询 MUST 经 SQL AST 验证为单条 `SELECT` 或只读 `WITH`，并受 timeout、行数和字节数限制。

#### Scenario: 账户权限无法确定
- **WHEN** 数据库连接成功但验证器无法证明账号不具备写权限
- **THEN** Resource Draft 不得进入 VERIFIED 或 PUBLISHED

#### Scenario: 查询包含 PL/SQL 或存储过程
- **WHEN** 工具请求提交匿名块、CALL、EXEC 或多语句
- **THEN** 平台必须在执行前拒绝

### Requirement: Tool Call 必须校验精确代码实现
Agent Runtime 和 `tool-mcp` MUST 在构建和执行 Tool Call 时校验 Job 冻结的 MCP server code、Tool identifier 与 schema hash 精确匹配当前代码 Manifest；不得仅凭工具名称相似即执行，也不得要求已删除的 Tool Release、Handler Version 或 Implementation Digest。
#### Scenario: 当前实现精确匹配
- **WHEN** Job Snapshot 的 server code、Tool identifier 和 schema hash 均与当前代码 Manifest 一致
- **THEN** 调用可以进入后续 Job、权限、资源和只读策略校验
#### Scenario: 当前 schema 漂移
- **WHEN** Tool 名称相同但 schema hash 不同
- **THEN** Runtime 或 `tool-mcp` 拒绝调用并记录安全 drift 错误，不自动使用当前实现

### Requirement: Real-tools 必须通过标准 MCP Tool Runtime 执行
真实工具验收 SHALL 启动 PostgreSQL、RabbitMQ、`tool-mcp`、`python-agent-runtime`、Worker 与所需工具资源；MUST NOT 启动 TypeScript Agent Runtime、Internal API Platform 或配置 `INTERNAL_API_*`。

#### Scenario: 真实数据库工具链
- **WHEN** Python Agent Job 对已授权目标调用数据库只读 Tool
- **THEN** 请求沿 `python-agent-runtime -> tool-mcp -> Resource` 完成并记录精确审计

### Requirement: Real-tools 验收必须覆盖拒绝和恢复
验收 MUST 覆盖未授权 Tool、数据范围越界、资源零命中、多命中、Secret 不可用、只读策略拒绝以及配置恢复后的成功调用。

#### Scenario: 歧义资源修复
- **WHEN** 两个资源导致调用被拒绝，管理员停用冲突 revision 后重试新 Job
- **THEN** 新调用唯一解析并成功，旧失败历史保持不变

<!-- Reconciled from mcp_new capability: `standard-mcp-tool-runtime` -->

### Requirement: Python Runtime只使用部署固定的MCP Server集合
系统 SHALL 由部署固定的`tool-mcp`使用官方MCP SDK向Python Runtime提供现有只读资源Tool，由部署固定且代码声明为`business-principal-jwt`的业务MCP提供经发布和Job冻结的业务Tool，并由部署固定的`file-service` File MCP接口提供任务文件工具。Runtime MUST只连接Job与Publication冻结且部署注册的私网Server地址，不得接受Agent、Application、用户或模型提供MCP Server URL、鉴权模式或凭据。各Server MUST使用代码拥有的稳定Tool identifier，不得互相代理、回退或复用其它Server的身份令牌。
#### Scenario: Python Runtime调用只读工具
- **WHEN** Python Runtime 执行冻结了合法只读 Tool 的 Job
- **THEN** Runtime 通过 `tool-mcp` 使用冻结 schema 和受治理执行语义
#### Scenario: Python Runtime调用文件工具
- **WHEN** Python Runtime执行冻结了合法File Tool的Job
- **THEN** Runtime通过`file-service`使用冻结schema、独立File Principal JWT和任务工作区边界
#### Scenario: payload提供自定义Server
- **WHEN** 请求或模型输出包含自定义MCP URL、Server code、鉴权模式、Header、Token或transport
- **THEN** Runtime和对应MCP服务必须在连接或调用前拒绝
#### Scenario: Python Runtime调用只读资源工具
- **WHEN** Python Runtime执行冻结了合法只读资源Tool的Job
- **THEN** Runtime通过`tool-mcp`使用冻结schema和受治理执行语义且不携带Authorization
#### Scenario: Python Runtime调用业务 MCP 工具
- **WHEN** Python Runtime执行冻结了合法业务MCP Tool的Job
- **THEN** Runtime只连接该Tool代码固定的业务Server并携带audience匹配的业务Principal JWT

### Requirement: MCP Tool 实现必须由代码 Manifest 拥有
系统 MUST 从代码Manifest注册稳定Tool identifier、server code、描述、输入Schema、操作语义、风险等级、资源类型和实现函数；现有`tool-mcp`只可注册只读资源Tool，File Service只可注册固定任务文件Tool。数据库和管理API MUST NOT创建或覆盖URL、SQL、Shell、脚本、模板、对象键规则或任意可执行实现。

#### Scenario: 部署合法 Manifest
- **WHEN** `tool-mcp`和`file-service`启动并加载无冲突的代码Manifest
- **THEN** 各自`tools/list`只返回当前Job冻结、schema匹配且授权的Manifest子集

#### Scenario: 文件Tool伪装为通用执行器
- **WHEN** File Tool schema接受任意路径、Bucket、对象键、Shell、URL或脚本
- **THEN** Manifest验证拒绝启动或发布

#### Scenario: 管理端提交动态实现
- **WHEN** 管理端尝试创建任意MCP、HTTP、SQL、Shell、脚本或模板实现
- **THEN** 系统拒绝且不持久化该内容

### Requirement: MCP 调用必须绑定有效 Job
每个MCP调用 MUST绑定有效RUNNING Job和Job冻结的精确Tool/schema hash。`tool-mcp`继续接受非敏感Job标识并重新读取Job；业务MCP MUST从自身audience匹配的已验证Principal JWT解析Job和主体，并重新读取用户、Session、Publication、authorization hash和scope；File Service MUST从独立File Principal JWT解析Job并重新读取用户、Session、Publication、Workspace和scope。任一Server均 MUST在Provider Credential解析、上游连接、文件元数据读取或对象操作前拒绝不存在、非RUNNING、Runtime/protocol不合法、Tool未冻结、scope不匹配或schema漂移的调用。
#### Scenario: 合法 Job 调用冻结只读工具
- **WHEN** RUNNING Job调用其冻结的精确只读Tool
- **THEN** `tool-mcp`进入资源、权限和只读策略校验
#### Scenario: 合法 Job 调用冻结文件工具
- **WHEN** RUNNING Job以有效File Principal调用其冻结的精确File Tool
- **THEN** File Service进入任务工作区、文件和操作授权校验
#### Scenario: Job 或 Tool 不匹配
- **WHEN** Job不存在、非RUNNING、Tool未冻结或schema hash漂移
- **THEN** 调用在连接上游或读取文件内容前失败关闭
#### Scenario: 合法 Job 调用冻结只读资源工具
- **WHEN** RUNNING Job调用其冻结的精确只读资源Tool
- **THEN** `tool-mcp`进入资源、权限和只读策略校验
#### Scenario: 合法 Job 调用冻结业务工具
- **WHEN** RUNNING Job以audience和scope匹配的业务Principal调用其冻结的精确业务Tool
- **THEN** 业务MCP进入Provider身份、业务权限和上游调用校验
#### Scenario: Job、Principal 或 Tool 不匹配
- **WHEN** Job不存在、非RUNNING、Principal audience或scope不匹配、Tool未冻结或schema hash漂移
- **THEN** 调用在解析Provider Credential、连接上游或读取文件内容前失败关闭

### Requirement: 工具资源必须按调用目标唯一解析
`tool-mcp` SHALL 使用 Agent 在当前 Tool Call 中提供的 `environment`、可选 `base`/`workshop`/`placement`、Tool 资源类型和当前可用 Published Resource Revision 解析资源；调用目标 MUST 先通过当前角色数据范围校验。匹配结果 MUST 恰好为一个，不得按顺序、默认值、最近父级或最新版本猜测；Job Snapshot 或 Routing Context 中的历史目标字段 MUST NOT 覆盖调用参数。

#### Scenario: test 环境唯一 MySQL 资源
- **WHEN** Tool Call 目标为 `environment=test` 且只有一个符合条件的已发布 MySQL Resource Revision
- **THEN** 工具使用该版本并记录资源 identity/revision 的非敏感审计

#### Scenario: 环境级资源不要求基地或车间
- **WHEN** Agent 调用目标为 `environment=test`、未提供 base/workshop，且存在唯一 environment scope 资源
- **THEN** 资源可以唯一解析，服务端不得要求虚构基地或车间

#### Scenario: 调用目标超出角色数据范围
- **WHEN** Agent 提供的 environment/base/workshop 不在当前用户角色数据范围内
- **THEN** 调用在资源连接前失败关闭，且不得尝试其它环境或候选

#### Scenario: 资源零命中或多命中
- **WHEN** 目标没有资源或存在两个同等候选
- **THEN** Tool Call 返回稳定资源解析错误且不访问任何候选

#### Scenario: cloud 与 edge 并存
- **WHEN** 同一逻辑目标存在 cloud 与 edge 资源
- **THEN** 调用必须提供明确 placement，否则失败关闭

### Requirement: 数据库 Redis Loki 执行必须保持只读安全边界
`tool-mcp` MUST 在进程内执行数据库、Redis 与 Loki 工具，并保留方言感知只读 SQL、表/前缀隔离、行数/超时、Redis Key 前缀、Loki selector/时间/行数和响应大小限制。

#### Scenario: 合法只读数据库查询
- **WHEN** 查询只读取允许表且满足已授权的 Tool Call 目标和上限
- **THEN** 执行器返回有界、脱敏且标记为不可信内部证据的结果

#### Scenario: 写 SQL 或越界目标
- **WHEN** SQL 包含写操作、多语句、未允许表，或参数尝试覆盖资源/租户/前缀事实
- **THEN** 执行器必须在目标执行前拒绝

### Requirement: MCP Transport 不新增认证和治理层
现有`tool-mcp` MUST不签发或验证Bearer Token/JWT，不挂载Runtime Grant、不拥有signing key，也不新增MCP专用RBAC、授权表或Resource Mapping；携带Authorization的`tool-mcp`请求继续拒绝。业务MCP和File MCP MUST复用平台统一Principal签名信任根、Job、角色、Business Application和Tool授权事实，不得自建用户、角色、JWT issuer、凭据表或替代授权模型；业务MCP使用按自身Server隔离的业务Principal，File MCP继续使用独立File Principal。
#### Scenario: Runtime 调用只读 MCP
- **WHEN** Runtime向`tool-mcp`发起工具调用
- **THEN** 请求不包含Runtime Grant、模型Key、Internal API Token、Principal JWT或MCP access token
#### Scenario: tool-mcp 请求携带 Authorization
- **WHEN** `tool-mcp` HTTP请求携带Authorization header
- **THEN** 服务拒绝该请求以维持现有非认证传输边界
#### Scenario: Runtime 调用 File MCP
- **WHEN** Runtime向File Service发起文件工具调用
- **THEN** 请求只携带独立File Principal JWT并由File Service复核现有统一授权和工作区事实
- **AND** File Service不创建独立RBAC或签发Token
#### Scenario: Runtime 调用业务 MCP
- **WHEN** Runtime向固定业务MCP发起冻结Tool调用
- **THEN** 请求只携带该Server audience的短时平台Principal JWT并由业务MCP复核现有统一授权事实
- **AND** 业务MCP不创建独立RBAC或签发平台Principal

### Requirement: 工具调用审计必须精确且不含 Secret
系统 SHALL 记录 Job、Agent/Application Publication、Tool identifier/schema hash、业务目标、实际 placement、Resource Revision、权限判定、correlation id、耗时与有界结果摘要；MUST NOT 记录连接密码、Token、完整 Prompt 或无界上游响应。

#### Scenario: 工具调用完成
- **WHEN** Tool Call 成功或失败
- **THEN** 历史记录足以定位精确工具、目标和资源版本且不泄漏 Secret

### Requirement: 旧平台和专用密钥不得回归
发布检查 MUST 拒绝 `runtime-tool-mcp`、`RUNTIME_TOOL_MCP_*`、HS256 issuer/verifier/signing key、Internal API Platform 服务、Internal API Token secret 或 `INTERNAL_API_*` 配置残留。

#### Scenario: 残留扫描命中旧链路
- **WHEN** 代码、Compose、env 示例或活动规格包含旧运行组件或配置
- **THEN** 验收失败直到残留被删除

### Requirement: File MCP 使用平台短时 Principal JWT
File Service的MCP接口 MUST 只接受平台身份服务签发、TTL不超过300秒且绑定内部用户、租户、RUNNING Job、Session、Agent Publication、Business Application Publication、授权快照和精确File Tool scope的Principal JWT。File Service MUST 使用平台JWKS验证签名、issuer、audience、authorized party、时间、JTI与全部绑定事实，并重新读取当前Job和任务工作区；JWT MUST NOT包含MinIO凭据、对象位置、钉钉凭据或其它下游Secret。

#### Scenario: 合法文件主体调用
- **WHEN** Runtime携带当前RUNNING Job的有效Principal JWT调用已冻结File Tool
- **THEN** File Service验证全部绑定事实并继续文件授权

#### Scenario: JWT与Job不匹配
- **WHEN** JWT的用户、Job、Session、Publication、scope或授权hash与当前事实不一致
- **THEN** File Service在读取文件元数据或MinIO前拒绝

#### Scenario: Agent把凭据放入JWT声明
- **WHEN** Token或请求包含MinIO Access Key、Secret Key、Session Token或对象键
- **THEN** 签发或验证流程拒绝且不记录原值

### Requirement: File MCP 参数不声明平台身份和对象位置
File MCP Tool输入 MUST 使用封闭Schema，只允许必要的文件选择、精确版本、沙盒文件句柄和用户业务意图。模型 MUST NOT声明用户、租户、任务工作区、reply route、Bucket、对象键、上传URL、Credential Reference或MCP Server地址；File Service必须从已验证Principal与Job解析这些事实。

#### Scenario: 模型提交任意对象键
- **WHEN** File Tool参数包含Bucket、对象键或跨工作区File ID
- **THEN** schema或授权校验在对象操作前拒绝

### Requirement: 内部文件调用使用角色隔离的短时 Service Principal
平台身份服务 MUST 使用统一的平台 Principal 签名私钥，为`file-worker`和Delivery Worker按需签发TTL不超过300秒的角色JWT；用户/Job Principal与Service Principal MUST 共享同一公开`PRINCIPAL_JWKS`，不得维护第二套Service Principal签名私钥或JWKS。服务JWT MUST 绑定独立固定issuer、`aud=file-service-internal`、相同的`sub`/`azp`角色、完整固定scope集合、JTI与时间声明；File Service MUST 在独立验证策略中校验这些claims，并确认当前接口所需scope属于该角色的完整集合。共享签名信任根不得使用户/Job Principal通过内部服务接口，也不得使Service Principal通过普通File MCP或其它用户MCP接口。Worker MUST NOT持有平台签名私钥、公开JWKS、另一角色bootstrap credential、预生成长期JWT或共享Internal API Token。

#### Scenario: File Worker换取并使用短时JWT
- **WHEN** File Worker以自己的角色bootstrap credential调用平台内部身份接口
- **THEN** 身份服务签发同时包含附件导入和内容清理固定scope、TTL不超过300秒的Service Principal JWT
- **AND** File Worker可在对应两个File Service接口使用该JWT并在到期前刷新

#### Scenario: Delivery凭据被File Worker使用
- **WHEN** File Worker使用Delivery Worker bootstrap credential或Delivery JWT调用附件导入
- **THEN** 平台身份服务或File Service在文件内容操作前拒绝

#### Scenario: Compose使用静态Service JWT文件
- **WHEN** 部署配置要求挂载预先生成且不会持续刷新的Service JWT
- **THEN** 部署契约测试失败且不得宣称服务身份已接线

### Requirement: File MCP 调用审计与统一 MCP Operation Audit 对齐
每次File MCP Tool调用 MUST 记录统一operation、attempt和event链，包含Job、内部用户、Agent/Application Publication、Tool identifier/schema hash、Workspace、File/Version、授权判定、Commit或Delivery关联、状态、耗时及有界摘要。审计 MUST 排除文件正文、完整Prompt、Principal JWT、MinIO或钉钉凭据、对象键和上传授权材料。

#### Scenario: 文件提交发生版本冲突
- **WHEN** File Tool完成暂存但基础版本不再是当前版本
- **THEN** 审计关联同一operation和提交意图并记录安全冲突结果
- **AND** 不保存文件正文或Secret

<!-- Integrated from archived change: `2026-08-23-unify-mcp-operation-audit/specs/builtin-tool-resource` -->

### Requirement: tool-mcp 必须写入通用 MCP 操作审计
`tool-mcp` SHALL 对每次有效 Job-bound 调用写入通用 `mcp_operation_audit`，覆盖 Tool 生命周期、授权判定、资源解析与实际资源访问。审计 MUST 保存 `mcp_call_id`、Job/Session/Invocation、Agent/Application Publication、Tool identifier/schema hash、业务目标、实际 placement、Resource Revision、状态、稳定错误码、尝试次数、耗时以及有界业务请求和结果。

#### Scenario: 只读资源工具调用成功
- **WHEN** `tool-mcp` 完成数据库、Redis、Loki 或 Schema Tool 调用
- **THEN** 系统保存一条终态 `TOOL` 证据及适用的 `AUTHORIZATION`、`RESOURCE` 证据，并全部关联同一个 `mcp_call_id` 和 `agent_tool_call.id`

#### Scenario: 授权或资源解析被拒绝
- **WHEN** Job、角色数据范围、Tool Binding、Schema hash 或唯一资源解析校验失败
- **THEN** 系统保存 `DENIED` 审计、稳定错误码和安全目标摘要，不建立外部资源连接

#### Scenario: 调用相同工具使用不同资源版本
- **WHEN** 同一 Job 的两个 Tool Call 实际解析到不同允许的 Resource Revision
- **THEN** 每个 `mcp_call_id` 只记录本次解析的精确 Resource Revision，不从 Job 或上一调用复制旧版本

<!-- Integrated from archived change: `2026-08-23-unify-mcp-operation-audit/specs/builtin-tool-resource` -->

### Requirement: tool-mcp 审计必须先于受治理外部访问并失败关闭
`tool-mcp` MUST 在访问数据库、Redis、Loki 或其它受治理资源前创建 MCP Tool Call 根事实与必需审计上下文。若必需的 Agent Tool Call 或 MCP 审计无法持久化，调用 SHALL 以 `mcp_audit_unavailable` 或等价稳定配置错误失败，且不得继续外部访问。

#### Scenario: 审计数据库不可用
- **WHEN** `tool-mcp` 无法创建本次调用的根审计事实
- **THEN** Tool Call 失败关闭并且资源客户端未被调用

<!-- Integrated from archived change: `2026-08-23-unify-mcp-operation-audit/specs/builtin-tool-resource` -->

### Requirement: tool-mcp 必须通过 MCP 元数据返回精确关联标识
`tool-mcp` SHALL 在成功、失败和业务拒绝的 `CallToolResult._meta` 中返回平台命名空间下的 `mcp_call_id` 与 `agent_tool_call_id`。这些字段 MUST 不进入模型可见业务正文、Tool Schema 或用户输入，并 MUST NOT 接受 Agent 提供的同名值覆盖。

#### Scenario: Runtime 收到 tool-mcp 结果
- **WHEN** `tool-mcp` 返回 Tool Result
- **THEN** Runtime 可从 `_meta` 取得服务端生成的关联标识，并从模型可见结果中排除这些平台内部字段

<!-- Integrated from archived change: `2026-08-23-unify-mcp-operation-audit/specs/builtin-tool-resource` -->

### Requirement: 通用 MCP 业务审计保留有界原文但排除认证材料
经授权的 `tool-mcp` 审计 SHALL 在配置大小边界内保留完整业务参数与业务结果，不要求对普通业务字段做脱敏；但 MUST 结构性拒绝或排除密码、Token、Cookie、Authorization Header、连接 Secret、密文、私钥及其它认证材料。

#### Scenario: 业务查询包含普通筛选条件
- **WHEN** Tool Call 参数包含环境、库表、只读 SQL、Key 前缀或 Loki Selector 等授权业务字段
- **THEN** 审计在大小边界内保留这些字段供追溯

#### Scenario: 载荷疑似包含认证字段
- **WHEN** 请求、资源结果或异常中出现认证材料字段
- **THEN** 审计写入拒绝该字段或整个非法载荷，并且不会持久化认证材料

<!-- Integrated from archived change: `2026-08-23-generalize-business-mcp-principal-jwt/specs/builtin-tool-resource` -->

### Requirement: 固定 MCP Server 必须声明唯一鉴权模式
系统 SHALL 在代码拥有的固定MCP Server策略中为每个可部署Server声明恰好一个鉴权模式：`tool-mcp`使用`job-context`，普通业务MCP使用`business-principal-jwt`，`file-service`使用`file-principal-jwt`。Tool Manifest中的每个`server_code` MUST解析到该固定策略，且请求、数据库、Agent、Application、用户或模型不得创建、覆盖或动态选择Server鉴权模式。

#### Scenario: 发布固定业务 MCP Tool
- **WHEN** 代码Manifest新增属于部署固定业务MCP的Tool
- **THEN** 该Server必须显式声明`business-principal-jwt`后才可通过启动、发布和Job快照校验

#### Scenario: 新 Server 未声明鉴权模式
- **WHEN** Tool Manifest引用未知Server或Server没有唯一固定鉴权策略
- **THEN** 启动、发布或Job快照创建失败关闭且不得使用默认鉴权模式

#### Scenario: 请求尝试覆盖鉴权模式
- **WHEN** Runtime请求、Tool参数或模型输出提供auth mode、Server URL、Header或Token
- **THEN** 协议或服务端在连接MCP前拒绝且不持久化这些值

<!-- Integrated from archived change: `2026-08-23-generalize-business-mcp-principal-jwt/specs/builtin-tool-resource` -->

### Requirement: 业务 MCP 只接受自身 audience 的平台 Principal
每个`business-principal-jwt` Server SHALL 只接受平台统一Principal信任根签发、`aud`等于自身固定`server_code`且scope与当前Job对该Server冻结Tool集合完全一致的短时JWT。业务MCP MUST 在访问Provider Credential或上游系统前复核RUNNING Job、内部用户、Session、两个Publication、Tool/schema、authorization hash和当前调用Tool scope，并 MUST 拒绝其它Server、File或Service Principal。

#### Scenario: 同一 Job 调用两个业务 MCP
- **WHEN** Runtime分别携带`aud=ones-mcp`和另一固定业务Server audience的两个JWT调用各自冻结Tool
- **THEN** 每个Server只验证并使用自身JWT，两个调用共享Job provenance但不共享Bearer Token或scope

#### Scenario: 业务 token 被跨 Server 复用
- **WHEN** Runtime把一个业务Server的JWT作为另一个Server的Authorization
- **THEN** 接收Server因audience不匹配而在Provider Credential解析和上游连接前拒绝

#### Scenario: 业务 MCP 收到 File Principal
- **WHEN** 业务MCP收到`aud=file-service`或包含文件工作区claims的Principal
- **THEN** 服务拒绝且不得尝试把File scope解释为业务Tool scope

#### Scenario: 业务调用审计
- **WHEN** 业务MCP Tool调用成功或失败
- **THEN** 统一MCP Operation Audit记录Server、Job、主体、Publication、Tool/schema、授权判定、correlation、状态、耗时和有界摘要
- **AND** 审计不得记录Principal JWT、Provider Credential、完整Prompt或无界上游响应

<!-- Integrated from archived change: `2026-08-23-decouple-document-readiness-from-agent-turns/specs/builtin-tool-resource` -->

### Requirement: File MCP对未就绪或失败表示失败关闭
File Service 的 `file_prepare_materialization` MUST 在读取对象或返回传输控制信息之前确认目标精确版本具有可物化的 Agent 可读内容。当所需 Markdown 表示仍为处理中时，工具 MUST 返回稳定错误码 `file_readable_content_not_ready`；当处理已失败、无文字或内容不可用时，MUST 返回 `file_processing_failed` 或与现有安全拒绝一致的稳定码。错误结果 MUST 只包含错误码、安全文件名和有界状态短语，MUST NOT 包含正文片段、对象键、Docling task ID、重试次数、内部队列名或原始异常。`file_get_metadata` 和 `task_workspace_list_files` MAY 返回有界可读性状态（如 `PENDING`、`AVAILABLE`、`FAILED`），以便 Agent 发现文件存在，但 MUST NOT 把处理中文档描述为可读取正文。`file_deliver_version` 在原件已保存且具备 `DELIVER` 时 MUST NOT 因 Markdown 未就绪而拒绝。系统提示 MUST 规定：收到上述未就绪或失败码时不得推测文件内容、不得根据文件名编造正文，并告知用户可读内容尚未生成或生成失败。

#### Scenario: 按需物化处理中的文档
- **WHEN** RUNNING Job 对可读性仍为 `PENDING` 的文档版本调用 `file_prepare_materialization`
- **THEN** File Service 在创建传输前拒绝，错误码为 `file_readable_content_not_ready`
- **AND** 审计只保留文件身份、错误码和有界状态，不含正文或内部处理器标识

#### Scenario: 按需物化已失败的文档
- **WHEN** 目标版本的 processing run 已 `FAILED` 或可读性为 `UNAVAILABLE`/`NO_TEXT`
- **THEN** `file_prepare_materialization` 返回 `file_processing_failed` 或等价稳定码
- **AND** 不返回空 Markdown 冒充成功

#### Scenario: 查询处理中文件的元数据
- **WHEN** Agent 对处理中文档调用 `file_get_metadata` 或在 `task_workspace_list_files` 中看到该文件
- **THEN** 结果包含安全文件名、精确版本和有界可读性状态
- **AND** 不包含可物化路径、对象位置或派生正文

#### Scenario: 交付原件不依赖表示
- **WHEN** 原件已保存且 Manifest 授予 `DELIVER`，Agent 调用 `file_deliver_version`
- **THEN** File Service 按原始 File Version 排队交付
- **AND** 不因 Markdown 表示仍为 `PENDING` 而拒绝

<!-- Integrated from archived change: `2026-08-23-recall-retained-files-by-time-window/specs/builtin-tool-resource` -->

### Requirement: File MCP 对内容已清理的历史召回项失败关闭
`task_workspace_list_files` MUST 只列出当前 Agent Job File Manifest 快照中的条目，其中可以包含本轮时段召回、未挂接当前活动工作区的保留版本。列表和 `file_get_metadata` MUST 返回有界元数据（安全文件名、File/Version ID、`source_received_at`、版本状态），MUST NOT 返回对象键、凭据或正文。系统 MUST NOT 把 File MCP 列表扩大为当前工作区全部历史文件或 Session 内 360 天附件库；调试用全量目录不在本能力范围。

当目标精确版本或文件状态为 `CONTENT_UNAVAILABLE` 时，`file_prepare_materialization` MUST 在读取对象或返回传输控制信息之前拒绝，稳定错误码 MUST 为既有 `file_content_unavailable`（或与其安全语义一致、文案为「文件内容已不可用，请重新发送文件」的稳定码）。该拒绝 MUST NOT 使用 `file_manifest_item_denied` 冒充「不在清单中」。错误结果 MUST 只包含错误码、安全文件名和有界状态短语。系统提示 MUST 规定：收到该错误码时不得推测或编造正文，不得把「内容已清理」说成「用户没发过这份文件」。

对仅因时段召回进入清单的条目，`file_create_commit_intent` MUST 拒绝；`file_deliver_version` 在原件仍可用且清单授予 `DELIVER` 时 MUST 仍可排队交付。

#### Scenario: 列表可见已清理正文的历史项
- **WHEN** 本 Job 快照包含一份 `CONTENT_UNAVAILABLE` 的时段召回版本
- **THEN** `task_workspace_list_files` 仍返回其安全文件名、版本状态和 `source_received_at`
- **AND** 不返回可物化路径或对象位置

#### Scenario: 物化已清理正文不得报清单外
- **WHEN** RUNNING Job 对快照内 `CONTENT_UNAVAILABLE` 版本调用 `file_prepare_materialization`
- **THEN** File Service 在创建传输前拒绝，错误码为 `file_content_unavailable`
- **AND** 不得返回 `file_manifest_item_denied`

#### Scenario: 历史召回项禁止提交
- **WHEN** Agent 对未挂接当前活动工作区的时段召回 File ID 调用 `file_create_commit_intent`
- **THEN** File Service 拒绝
- **AND** 不创建 staging 对象或新版本

#### Scenario: 快照外历史附件对 File MCP 不可见
- **WHEN** 同一 Session 存在仍在保留期但未写入当前 Job 快照的附件
- **THEN** `task_workspace_list_files` 不返回该附件
- **AND** 使用其 File/Version ID 的物化请求被拒绝

<!-- Integrated from archived change: `2026-08-23-scale-task-workspace-with-bounded-job-working-sets/specs/builtin-tool-resource` -->

### Requirement: File MCP提供冻结且有界的工作区目录发现
File MCP SHALL在代码Manifest中发布`task_workspace_search_files`固定Tool identifier与封闭schema。Agent/Application Publication和Job MUST冻结其精确schema hash后才可调用；服务端必须使用File MCP Principal解析Job、主体、tenant、Session、Publication、workspace和`workspace_catalog_revision_id`，并在每次查询时复核当前角色、Application Tool子集及会话归属。模型不得在Tool参数中声明这些平台身份或目录revision。

该Tool每页 MUST默认返回20且最多返回50个不含正文、对象位置和凭据的元数据项，支持代码注册的名称、格式、UTC来源接收时间和可读状态过滤以及不透明游标。查询 MUST始终针对Job Manifest冻结的不可变目录revision；当前工作区后续变化不得改变该Job的分页结果。Tool结果中的精确File/Version只构成可选择身份，不自动授予MATERIALIZE、EDIT、COMMIT或DELIVER，也不写入初始Manifest。

#### Scenario: Publication冻结新发现Tool
- **WHEN** RUNNING Job的MCP Tool Snapshot包含`task_workspace_search_files`及匹配schema hash
- **THEN** File MCP按当前Principal和workspace执行有界元数据查询
- **AND** 统一MCP Operation Audit记录过滤摘要、目录revision、返回数量和耗时而不记录正文

#### Scenario: Job没有冻结新发现Tool
- **WHEN** Runtime尝试为未冻结该Tool的Job调用`task_workspace_search_files`
- **THEN** File MCP在目录查询前拒绝
- **AND** 不因服务已经部署新Tool而扩大旧Job能力

#### Scenario: 单页请求超过50项
- **WHEN** Tool输入的limit为51或更大
- **THEN** 封闭schema拒绝参数
- **AND** 不执行数据库查询或静默改写为更大上限

#### Scenario: 发现结果用于准备物化
- **WHEN** 兼容Job把发现结果中的精确File/Version传给`file_prepare_materialization`
- **THEN** File Service先执行冻结revision归属、40项工作集和实时授权复核，再准备transfer
- **AND** Runtime在下载前还必须通过统一Sandbox输入分区与224MiB容量预留

<!-- Integrated from archived change: `2026-08-23-scale-task-workspace-with-bounded-job-working-sets/specs/builtin-tool-resource` -->

### Requirement: 动态文件选择沿用既有Principal与统一审计
Manifest外文件的工作集晋升 MUST只发生在已经冻结兼容发现Tool和`file_prepare_materialization`的同一RUNNING Job内。File Service MUST校验两个Tool的Job Snapshot/schema hash、当前Principal全部绑定事实、精确File/Version属于冻结目录revision、内容仍可用且当前主体仍有权访问，并把允许或拒绝结果写入统一MCP Operation Audit及追加工作集事实。Runtime File MCP bridge MUST在创建Sandbox目标文件前调用统一预算预留器；File Service授权成功不得被解释为绕过Runtime文件数、分区或总容量检查。输入与审计 MUST NOT包含文件正文、Principal JWT、MinIO对象位置或凭据。

#### Scenario: 跨工作区精确ID被提交
- **WHEN** Agent把另一个workspace的精确File/Version提交给动态选择路径
- **THEN** File Service在创建工作集事实或transfer前拒绝
- **AND** 审计只保存安全的拒绝码和不透明身份摘要

#### Scenario: 工作集上限拒绝被审计
- **WHEN** 第41个不同File/Version输入触发`job_file_working_set_limit_exceeded`
- **THEN** 统一审计记录Job、Tool、workspace、拒绝码和当前有界计数
- **AND** 不记录正文、对象位置或未受限查询结果

#### Scenario: File MCP物化会突破Sandbox容量
- **WHEN** File Service已经授权精确版本，但Runtime预留发现该输入会使Sandbox超过224MiB或`inputs`40项上限
- **THEN** Runtime在下载字节和创建目标文件前拒绝并安全终结transfer
- **AND** 不因物化来自File MCP而绕过Sandbox预算
