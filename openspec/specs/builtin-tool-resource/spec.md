# builtin-tool-resource Specification

## Purpose
定义内置只读工具、资源版本、业务拓扑、数据库、Redis 和 Loki 的治理、发布、绑定与执行边界，确保模型不能绕过受管资源和只读策略。

## Requirements

<!-- Reconciled from mcp_new capability: `base-scoped-redis-loki` -->

### Requirement: Redis and Loki resolve at the base level
The system SHALL allow Redis to resolve from an exact Environment-level or Base-level Resource Mapping and to be inherited by child Workshops through their frozen namespace policies. Loki SHALL instead resolve from an exact global or Environment-level Resource Mapping plus an Environment and optional Base Scope Policy; Loki MUST NOT require a Base, Workshop or placement-level connection binding.

#### Scenario: Redis routed to base upstream
- **WHEN** a Redis request targets Environment `sanjiu`, Base `guanlan`, Workshop `GL001`
- **THEN** the platform uses the base Resource Revision frozen by the Job and applies GL001's namespace Policy Revision

#### Scenario: Redis routed to environment upstream
- **WHEN** an Environment has no Base layer and its Job freezes one environment-level Redis Resource Revision
- **THEN** the platform uses that revision without creating a default Base or Workshop policy

#### Scenario: Loki routed through global upstream
- **WHEN** an Application Publication maps Environment `sanjiu-test1` to a global Loki Resource Revision and an exact Scope Policy
- **THEN** the platform queries that upstream and injects the Policy's Environment and optional Base selector

#### Scenario: Loki routed through environment upstream
- **WHEN** an Application Publication maps one Environment to its own Loki Resource Revision
- **THEN** the platform uses that exact revision and Scope Policy without considering cloud/edge placement

### Requirement: Workshop is distinguished by Redis key prefix
The system SHALL constrain Workshop-scoped Redis reads using one or more exact complete namespace prefixes stored in the Job's frozen Workshop Partition Policy Revision. It SHALL allow only GET and bounded SCAN, require a complete prefix before any wildcard, and reject cross-namespace, regex or unbounded patterns.

#### Scenario: Key within workshop prefix accepted
- **WHEN** a Redis GET for Workshop `GL001` targets a key beginning with `cr999.crmes.CRMES_TEST_GL#GL001@$`
- **THEN** the platform executes the read against the exact frozen Resource Revision

#### Scenario: Key outside workshop prefix rejected
- **WHEN** a Redis request for Workshop `GL001` targets a key in the `CZ002` namespace or uses `*GL001*`
- **THEN** the platform rejects the request as a policy violation before contacting Redis

#### Scenario: Mutating Redis command rejected
- **WHEN** a Redis request uses a non-read command such as `SET`, `DEL`, `EXPIRE`, `FLUSHDB` or `EVAL`
- **THEN** the platform rejects it as not read-only

#### Scenario: Base has no workshop layer
- **WHEN** Redis is bound to an effective Environment or Base leaf without Workshops
- **THEN** the platform uses the frozen unpartitioned target scope and does not require a synthetic key prefix

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

### Requirement: Redis 和 Loki 必须由已发布 Resource Revision 提供
Redis 与 Loki 的地址、认证、tenant/数据库号及查询边界 MUST 来自业务应用发布绑定的具体 Resource Revision，并被复制到 Job Execution Scope。

#### Scenario: Redis 发布新 revision
- **WHEN** Redis Resource Identity 发布新 revision 但应用未重新发布
- **THEN** 已发布应用和新建 Job 继续使用原绑定 revision

#### Scenario: Loki 请求覆盖 tenant
- **WHEN** 工具参数请求与绑定 revision 不同的 tenant
- **THEN** 平台必须拒绝或强制使用绑定 tenant，不能扩大范围

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
Redis 或 Loki Published Revision 的 Secret 无法解析时，系统 MUST 保留 Last Known Good；没有 LKG 时仅阻止依赖该资源的应用。

#### Scenario: Redis 密码 Secret 被禁用
- **WHEN** runtime reload 无法解析 Redis `password_ref`
- **THEN** Redis revision 标为 degraded，且不得从 env 或旧配置回退

### Requirement: Loki scope is enforced by environment and optional base selector policy
The system SHALL constrain Loki queries using the exact Environment and optional Base Scope Policy frozen by the Job, independent of whether the Job's business target contains a Workshop. Multiple Bases in one Environment MUST use separate named policies rather than OR conditions.

#### Scenario: Environment-only Loki query
- **WHEN** a Scope Policy maps `customer=sanjiu-test1` to one Environment without a Base condition
- **THEN** every runtime query includes that exact mandatory condition

#### Scenario: Base-scoped Loki query
- **WHEN** a Scope Policy maps `customer=sanjiu-test1 AND workshop=guanlan` to Base `guanlan`
- **THEN** every runtime query includes both exact conditions and treats the physical `workshop` value as a Base mapping

#### Scenario: Workshop Job does not add a label
- **WHEN** a Job target is `sanjiu-test1/guanlan/GL001`
- **THEN** the effective Loki selector remains the frozen Environment/Base Policy and does not add `GL001`, replica or placement conditions automatically


<!-- Reconciled from mcp_new capability: `built-in-readonly-tool-governance` -->

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

### Requirement: 已发布资源不得原地修改或普通删除
Draft 可以删除；Published Revision MUST NOT 被原地修改或通过普通 CRUD 物理删除，只能 disable 或 archive。

#### Scenario: 修改已发布 revision
- **WHEN** 管理员尝试修改 Published Revision 的连接字段或 Secret 引用
- **THEN** 系统必须拒绝，并要求从该版本创建新 Draft

### Requirement: 业务应用发布必须绑定具体 Resource Revision
业务应用发布 MUST NOT 绑定或保存 Resource Revision。工具资源保持独立发布；`tool-mcp` MUST 在每次 Tool Call 时按 Agent 提供且通过当前角色数据范围校验的目标、资源类型与可选 placement 解析唯一 Published Resource Revision，并记录实际版本。

#### Scenario: 资源发布新版本
- **WHEN** 某 Resource 发布新 revision 且旧 revision 已停用
- **THEN** 新 Tool Call 只可解析当前可用且唯一的 revision，既有 Job 若无法满足其冻结边界则失败关闭

#### Scenario: 应用尝试提交资源绑定
- **WHEN** Application Draft 或 Publish payload 包含 Resource Revision、slot 或 mapping
- **THEN** 系统拒绝旧字段且不保存兼容映射

### Requirement: 运行时必须原子热加载并保留 Last Known Good
`tool-mcp` SHALL 在单次调用内读取一个一致的资源 revision/Secret 快照并完成连接；系统 MUST NOT 维护 Internal API Platform activation 或 Application Last Known Good 映射。资源解析或连接失败时仅该 Tool Call 失败，不能回退到未授权旧 revision。

#### Scenario: 当前资源可解析
- **WHEN** 唯一 Published Resource Revision、active Secret 和驱动均可用
- **THEN** Tool Call 使用该一致快照执行并记录 revision

#### Scenario: 资源或 Secret 不可用
- **WHEN** revision 被禁用、Secret 缺失或连接初始化失败
- **THEN** Tool Call 以安全配置错误失败且不使用旧缓存或其他候选

### Requirement: 工具资源管理界面必须展示实际生效状态
“平台治理 → 工具资源” MUST 支持 DB、Redis、Loki 的列表、Draft 编辑、Secret 选择、测试、发布、disable/archive，并区分 draft、published、effective 和 activation 状态。

#### Scenario: 管理员查看资源详情
- **WHEN** 资源新版本已发布但运行时加载失败
- **THEN** 界面必须同时显示 Published Revision、当前 Effective Revision、失败状态和安全错误，不能误报已生效

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
系统 SHALL 提供受限的 Loki label 诊断能力，用于列出当前授权目标在指定时间窗口内可见的 label 名称。

#### Scenario: 查询可见 labels
- **WHEN** 授权用户请求指定 environment/base/workshop 的 Loki labels
- **THEN** Internal API Platform 返回 bounded label 名称列表、tenant 信息是否已配置、时间窗口和 truncated 标记

#### Scenario: label 查询超出限制
- **WHEN** 请求的时间窗口或响应大小超过平台限制
- **THEN** Internal API Platform SHALL 拒绝或截断响应并返回可审计错误分类

### Requirement: Loki diagnostics shall expose bounded label values
系统 SHALL 提供受限的 Loki label values 诊断能力，用于列出允许 label 的候选值，帮助确认服务名、job 名或 container 名是否存在。

#### Scenario: 查询允许 label 的 values
- **WHEN** 授权用户请求允许 label 的 values
- **THEN** Internal API Platform 返回 bounded values、label 名称、时间窗口、truncated 标记和数据源摘要

#### Scenario: 查询不允许 label
- **WHEN** 用户请求未在 allowlist 中的 label values
- **THEN** Internal API Platform MUST 拒绝请求并说明 label 不允许

### Requirement: Loki probe shall explain empty query results
系统 SHALL 提供 Loki selector probe 或等价诊断结果，用于解释指定 selector、keyword 和时间窗口为何没有命中日志。

#### Scenario: selector 无命中
- **WHEN** Loki 查询返回 `line_count=0`
- **THEN** 响应 summary SHALL 包含 selector、query、minutes、stream_count、line_count 和 empty result hints

#### Scenario: selector 有命中
- **WHEN** Loki probe 在指定时间窗口内命中日志流
- **THEN** 响应 summary SHALL 返回 stream_count、line_count 或可用样本摘要，并保持结果大小受限

### Requirement: Loki diagnostics shall preserve tenant and topology isolation
Loki 诊断 endpoint SHALL 使用与真实 `query_loki` 相同的 environment/base/workshop 解析、tenant 设置、workshop label 注入和访问控制。

#### Scenario: 车间隔离诊断
- **WHEN** 用户请求 GL001 的 Loki 诊断
- **THEN** 平台 SHALL 注入或强制 GL001 对应的 workshop label
- **AND** 响应 MUST NOT 返回 GL002 专属日志样本

#### Scenario: tenant 错误
- **WHEN** Loki upstream 返回 tenant/auth 相关错误
- **THEN** 平台 SHALL 返回安全错误摘要和 retryable 分类
- **AND** 响应 MUST NOT 暴露认证 token 或 secret


<!-- Reconciled from mcp_new capability: `loki-scope-selector-policy` -->

### Requirement: Loki Resource 只允许 global 或 environment 连接范围
系统 SHALL 允许 Loki Resource Revision 声明 global scope 或一个精确 Environment scope，并 MUST NOT 把 Base、Workshop 或 cloud/edge placement 作为 Loki 连接资源范围。

#### Scenario: 当前统一 Loki
- **WHEN** 一个 Loki 实例采集多个 Environment 的日志
- **THEN** 管理员可把该 Resource Revision 发布为 global，并通过不同 Scope Policy 收窄各 Environment

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
标签 key/value 发现结果 SHALL 仅作为当前 Draft 和测试会话的填写辅助证据；系统 MUST NOT 自动保存完整标签目录、自动创建 Scope Policy 或在运行时查询发现目录来扩大范围。

#### Scenario: 管理员关闭未保存页面
- **WHEN** 标签发现成功但管理员没有保存 Policy Draft
- **THEN** 系统不创建可发布 selector，发现缓存按受控期限失效

#### Scenario: Loki 后续出现新 label value
- **WHEN** Published Scope Policy 创建后 Loki 出现新的 label value
- **THEN** 既有 Policy 和 Application Publication 不自动改变

### Requirement: Loki Scope Selector Policy 必须使用精确 AND 条件
每个 Loki Scope Selector Policy Draft MUST 绑定一个精确 Loki Resource Revision、一个平台 Environment 和可选 Base，并 SHALL 包含一个或多个唯一 key 的精确非空 `key=value` 条件；条件只允许 AND，禁止重复 key、OR、否定、正则、通配和任意 LogQL。

#### Scenario: 保存环境 selector
- **WHEN** 管理员为 Environment `sanjiu-test1` 保存 `customer=sanjiu-test1`
- **THEN** 系统保存规范化的一个精确条件和业务范围映射

#### Scenario: 保存环境加基地 selector
- **WHEN** 管理员为 Environment `sanjiu-test1`、Base `guanlan` 保存 `customer=sanjiu-test1 AND workshop=guanlan`
- **THEN** 系统保存两个唯一 key 的精确条件，并明确物理 `workshop` value 映射逻辑 Base

#### Scenario: 多个基地使用一个 OR 策略
- **WHEN** 管理员尝试用 OR 在一个 Policy 中包含 `guanlan` 与 `tianjin`
- **THEN** 系统拒绝并要求为每个 Base 建立独立命名 Policy

#### Scenario: 提交重复或模糊条件
- **WHEN** Draft 含重复 key、正则、`!=`、`=~`、空 value 或任意 LogQL 片段
- **THEN** 系统拒绝保存或验证

### Requirement: Scope Policy 必须独立验证并不可变发布
系统 SHALL 为 Loki Scope Selector Policy 管理 Draft、机器验证证据和不可变 Published Revision；验证 MUST 绑定 Resource Revision、规范化条件 hash、Verifier Version 和有界响应摘要，内容或资源变化后旧证据失效。

#### Scenario: 验证 selector 有匹配
- **WHEN** 受限查询成功并命中日志流
- **THEN** 系统保存匹配数量、截断标记、hash 和时间，不保存无界日志正文

#### Scenario: 验证 selector 零匹配
- **WHEN** 受限查询被 Loki 正常接受但当前没有匹配流
- **THEN** 验证可以成功并携带 zero-match warning，Publish 不得自动移除任何条件

#### Scenario: 发布后修改条件
- **WHEN** 管理员尝试修改 Published Policy Revision
- **THEN** 系统拒绝并要求复制为新 Draft、重新验证和发布

### Requirement: Application Publication 必须冻结精确 Loki 资源与 Scope Policy
Application Publication MUST 为每个 Loki slot 和有效 Environment 冻结精确 Loki Resource Revision、Scope Policy ID/revision/hash；一个有效 Environment MUST NOT 同时命中 global 与 environment Loki 或多个 Scope Policy。

#### Scenario: global Loki 服务两个环境
- **WHEN** 一个应用使用同一 global Loki 查询两个 Environment
- **THEN** Publication 为每个 Environment 分别冻结指向同一 Resource Revision 的独立 Scope Policy

#### Scenario: 环境切换独立 Loki
- **WHEN** 管理员为某 Environment 发布新的独立 Loki Resource
- **THEN** 既有 Publication 仍使用原 global Mapping，只有新 Application Publication 可显式切换

#### Scenario: 同一环境配置重叠
- **WHEN** 同一 Loki slot 的 global 与 environment Mapping 或两个 Policy 同时覆盖一个 Environment
- **THEN** Application Publish 拒绝歧义配置

### Requirement: Resource 管理界面必须区分策略关联与应用运行绑定
Loki Resource 管理界面 SHALL 只把 Draft 或 Published Revision 引用该 Resource Identity 的 Scope Policy 作为关联策略，并 MUST 明确展示 Policy 冻结的 Resource Revision 与该 Resource 当前 Published Revision 是否一致；策略选择或编辑 MUST NOT 被表述为 Application Publication 运行绑定。

#### Scenario: 同一环境存在多个 Loki Resource
- **WHEN** 同一 Environment 下的两个 Scope Policy 分别引用不同 Loki Resource Identity
- **THEN** 每个 Resource 的关联策略选择器只显示引用该 Resource Identity 的 Policy，不按相同 Environment 混入另一个 Resource 的 Policy

#### Scenario: Policy 仍引用历史 Resource Revision
- **WHEN** Loki Resource 已发布新 Revision，但 Scope Policy 最新 Published Revision 仍冻结该 Resource 的旧 Revision
- **THEN** 页面标记“历史 Resource Revision”，同时显示 Policy Revision、冻结 Resource Revision 和当前 Resource Revision，并提供显式复制新 Draft 到当前 Resource Revision 的操作

#### Scenario: 查看运行绑定状态
- **WHEN** 管理员查看一个 Scope Policy
- **THEN** 页面显示引用其精确 Published Policy Revision 的 Application Publication；没有引用时明确显示未绑定任何已发布应用，且不因下拉选中 Policy 而宣称已运行绑定

#### Scenario: PostgreSQL 中策略尚未被应用使用
- **WHEN** 管理员创建新 Scope Policy 或查看尚无 Application Publication 引用的历史 Policy
- **THEN** 后端在 PostgreSQL 中稳定返回空的应用使用列表，页面仍完整显示策略创建或管理区域，不返回服务器内部错误

### Requirement: Published Scope Policy 必须作为不可覆盖的运行时 selector
运行时 MUST 从 Job Snapshot 注入 Published Scope Policy 的全部精确条件；Agent 只能添加 Tool Manifest 明确允许的诊断过滤条件，最终 selector 必须为强制条件与附加条件的 AND，且附加条件不得覆盖或冲突同名强制 key。

#### Scenario: Agent 添加允许的 logtype
- **WHEN** Manifest 允许 `logtype` 诊断过滤且 Agent 请求一个精确 value
- **THEN** 运行时把该条件与强制 Environment/Base selector 进行 AND 合并

#### Scenario: Agent 覆盖 customer
- **WHEN** Agent 请求不同的 `customer`、tenant 或删除强制条件
- **THEN** 平台拒绝调用或忽略冲突输入并始终使用冻结范围，不得扩大查询

#### Scenario: 请求任意 LogQL selector
- **WHEN** Agent 输入包含 OR、负向匹配、正则或任意 selector 字符串
- **THEN** 平台在访问 Loki 前拒绝请求

### Requirement: Loki 不得宣称 Workshop 或 placement 授权隔离
第一阶段 Loki 授权范围 SHALL 止于 Environment 和可选 Base；`role`、`replica`、`app`、`logtype` 只能作为受控诊断过滤，MUST NOT 被解释为用户角色、Resource Placement 或可靠 Workshop 身份。

#### Scenario: Job 目标包含 GL001
- **WHEN** Job 业务目标为某 Base 下 Workshop GL001
- **THEN** Loki 查询仍使用该 Environment/Base 的强制 Scope Policy，不自动注入 `workshop=GL001` 或 `replica=GL001`

#### Scenario: 日志 label role 为 edge
- **WHEN** Loki 流包含 `role=edge`
- **THEN** 系统只把它作为采集侧诊断属性，不据此授予 edge 权限或改变 Resource Placement

### Requirement: 空结果健康必须与生命周期分离
系统 SHALL 监测 Published Scope Policy 的查询结果并可标记 `EMPTY` 或 `DEGRADED` 健康状态；长期零匹配 MUST NOT 自动 disable、archive、切换 Policy 或放宽 selector。

#### Scenario: Published Policy 长期零匹配
- **WHEN** 多次受控健康探测均被 Loki 接受但返回零流
- **THEN** 管理端显示 EMPTY/DEGRADED 和最后证据，运行时继续按原 selector 返回空结果

#### Scenario: Loki 上游不可用
- **WHEN** 健康探测因连接、认证或超时失败
- **THEN** 系统标记安全的上游健康错误，与“成功但为空”区分，并且不泄露 Secret


<!-- Reconciled from mcp_new capability: `multi-dialect-database-gateway` -->

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

### Requirement: Internal API Platform image bundles Oracle Instant Client
若平台支持 Oracle thick/legacy 连接，系统 SHALL 仅在 `tool-mcp` 镜像中安装匹配架构的 Oracle Instant Client，并由 Oracle Resource Revision 显式选择模式；Internal API Platform 镜像和服务 MUST 不存在。

#### Scenario: 构建 tool-mcp Oracle 镜像
- **WHEN** vendor 目录提供受支持的 Oracle Instant Client
- **THEN** `tool-mcp` 可以初始化 thick client，Worker/API/Runtime 镜像不包含该客户端

#### Scenario: 未提供 thick client
- **WHEN** Oracle Resource 要求 thick 模式但镜像没有客户端
- **THEN** 资源验证和 Tool Call 失败关闭且不回退到不兼容模式


<!-- Reconciled from mcp_new capability: `platform-access-control` -->

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
The system MUST authenticate the calling service with a required Bearer Token and MUST resolve caller, application, Handler and scope facts from the persisted `X-Agent-Job-Id`. User and scope headers are consistency hints only and cannot grant access.

#### Scenario: Missing service Token rejected
- **WHEN** a tool request arrives without a valid Internal API service Token
- **THEN** the platform rejects the request before reading or executing the target resource

#### Scenario: Unknown or non-running Job rejected
- **WHEN** the Token is valid but the supplied Job does not exist or is not in an allowed execution state
- **THEN** the platform rejects the request and records the rejection

#### Scenario: Header identity conflicts with Job
- **WHEN** a user, application or scope Header conflicts with the persisted Job facts
- **THEN** the platform rejects the request and MUST NOT trust the Header value

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


<!-- Reconciled from mcp_new capability: `real-tools-runtime` -->

### Requirement: Real-tools 必须通过标准 MCP Tool Runtime 执行
真实工具验收 SHALL 启动 PostgreSQL、RabbitMQ、`tool-mcp`、两个 Agent Runtime、Worker 与所需工具资源；MUST NOT 启动 Internal API Platform 或配置 `INTERNAL_API_*`。

#### Scenario: 真实数据库工具链
- **WHEN** Python 或 TypeScript Agent Job 对已授权目标调用数据库只读 Tool
- **THEN** 请求沿 `Runtime -> tool-mcp -> Resource` 完成并记录精确审计

### Requirement: Real-tools 验收必须覆盖拒绝和恢复
验收 MUST 覆盖未授权 Tool、数据范围越界、资源零命中、多命中、Secret 不可用、只读策略拒绝以及配置恢复后的成功调用。

#### Scenario: 歧义资源修复
- **WHEN** 两个资源导致调用被拒绝，管理员停用冲突 revision 后重试新 Job
- **THEN** 新调用唯一解析并成功，旧失败历史保持不变


<!-- Reconciled from mcp_new capability: `workshop-resource-partition-policy` -->

### Requirement: Workshop Resource Partition Policy 必须版本化发布
系统 SHALL 为每个需要共享物理资源的逻辑 Workshop 管理稳定 Policy Identity、可编辑 Draft、机器验证证据和不可变 Published Revision；修改任何前缀或规则后 MUST 创建新 Draft、重新验证并发布新 revision。

#### Scenario: 发布已验证策略
- **WHEN** 授权管理员发布内容 hash 与当前成功证据一致的 Policy Draft
- **THEN** 系统创建不可变 Published Revision 并记录 workshop、规则、验证摘要、actor 和时间

#### Scenario: 修改已发布策略
- **WHEN** 管理员尝试原地修改 Published Revision 的数据库或 Redis 前缀
- **THEN** 系统拒绝并要求复制为新 Draft

#### Scenario: 策略发布新版本
- **WHEN** Workshop Policy 发布新 revision 但应用未重新发布
- **THEN** 既有 Application Publication 和 Job 继续使用原 revision

### Requirement: 数据库车间策略第一阶段必须恰好包含一个精确表名前缀
需要 Workshop 隔离的数据库 Policy MUST 为该 Workshop 保存恰好一个非空、非通配、非正则的表名前缀；前缀比较 MUST 遵循目标数据库方言的标识符规范化规则。

#### Scenario: 配置 GL001 表前缀
- **WHEN** 管理员为 Workshop `GL001` 保存数据库前缀 `GL001_`
- **THEN** 系统接受该 Draft 并在验证和运行时使用规范化后的精确前缀

#### Scenario: 提交多个或模糊前缀
- **WHEN** Draft 提交前缀列表、正则、空值、`*` 或 `%`
- **THEN** 系统拒绝保存或验证

#### Scenario: 目标没有 Workshop 层级
- **WHEN** Environment 或 Base 是实际叶子目标且没有 Workshop 子节点
- **THEN** 该目标的数据库 Mapping 不要求创建虚拟 Workshop Policy

### Requirement: Schema Directory 必须按冻结的数据库前缀过滤
数据库 Schema Directory MUST 只返回名称满足 Job 冻结 Policy Revision 精确前缀的表及其有界字段摘要；不得暴露其它 Workshop 的表名或连接信息。

#### Scenario: GL001 查询 schema 目录
- **WHEN** Job 目标为 GL001 且冻结前缀为 `GL001_`
- **THEN** Schema Directory 只返回符合方言比较规则的 `GL001_` 表和有界字段摘要

#### Scenario: 同库存在 GL002 表
- **WHEN** 数据库同时包含 `GL001_` 和 `GL002_` 开头的表
- **THEN** GL001 的 Schema Directory 不返回 `GL002_` 表名或字段

### Requirement: 数据库执行前必须验证所有物理表引用
数据库网关 MUST 在连接和执行前解析只读 SQL 中所有物理表引用，并逐一验证其满足冻结的表名前缀；无法可靠解析、动态表名、多语句或任一越界引用 MUST 被拒绝。

#### Scenario: 查询允许的单表
- **WHEN** 只读 SQL 仅引用符合 `GL001_` 前缀的表
- **THEN** 请求可进入既有只读语法、权限、超时和结果边界校验

#### Scenario: Join 跨车间表
- **WHEN** SQL 同时引用 `GL001_ORDER` 与 `GL002_ORDER`
- **THEN** 网关在访问数据库前拒绝整个请求

#### Scenario: SQL 表引用无法静态确定
- **WHEN** SQL 使用平台不支持且无法可靠解析的动态表名或方言结构
- **THEN** 网关失败关闭，不以字符串包含判断放行

### Requirement: Redis 车间策略必须保存一个或多个精确完整 namespace 前缀
共享 Redis 的 Workshop Policy SHALL 保存一个或多个非空的精确完整 key namespace 前缀；每个前缀 MUST 包含由部署契约定义的固定 namespace 与 Workshop code 边界，例如 `cr999.crmes.CRMES_TEST_GL#GL001@$`，并 MUST NOT 使用正则或通配符。

#### Scenario: 配置一个完整前缀
- **WHEN** 管理员为 GL001 保存 `cr999.crmes.CRMES_TEST_GL#GL001@$`
- **THEN** 系统接受其作为一个精确 namespace 前缀

#### Scenario: 一个 Workshop 有多个合法 namespace
- **WHEN** 同一 Workshop 的业务数据确实分布在两个固定 namespace
- **THEN** Policy 可以保存两个分别验证的精确前缀，而不是一个宽泛共同前缀

#### Scenario: 提交模糊 namespace
- **WHEN** 管理员提交 `*GL001*`、正则或只包含 `GL001` 的片段
- **THEN** 系统拒绝该 Policy Draft

### Requirement: Redis GET 和 SCAN 必须强制执行冻结前缀
`query_redis_get` 的完整 key MUST 以冻结 Policy Revision 中某个完整 namespace 前缀开头；`query_redis_scan` 的 pattern MUST 从某个完整前缀开始且通配符只能出现在该前缀之后。系统 MUST 继续限制命令、迭代次数、返回数量、字节和脱敏。

#### Scenario: GET 命中允许前缀
- **WHEN** GL001 Job 请求 key `cr999.crmes.CRMES_TEST_GL#GL001@$EBRDataText.809901890274822.Sheet4.rows`
- **THEN** 请求可进入只读 GET 执行和结果边界校验

#### Scenario: GET 跨 Workshop
- **WHEN** GL001 Job 请求以 `cr999.crmes.CRMES_TEST_CZ#CZ002@$` 开头的 key
- **THEN** 平台在访问 Redis 前拒绝请求

#### Scenario: 有界 SCAN pattern
- **WHEN** GL001 Job 使用 `cr999.crmes.CRMES_TEST_GL#GL001@$[BATCH_RECORD]:*` pattern
- **THEN** 平台在既有 SCAN 次数与返回上限内执行

#### Scenario: 前缀前出现通配符
- **WHEN** SCAN pattern 为 `*GL001*` 或通配符出现在完整 namespace 前缀内
- **THEN** 平台拒绝请求且不向 Redis 发送 SCAN

### Requirement: Redis 连接测试与 namespace 验证必须分离
Redis Resource 连接测试 MUST 只验证受治理连接字段、Secret、认证、TLS、database 和 PING，不得枚举 key；Partition Policy 验证 MUST 由系统为每个精确前缀生成有界 `prefix*` SCAN，并只保存匹配数、截断标志、摘要 hash、时间和脱敏错误。

#### Scenario: 测试 Redis 连接
- **WHEN** 管理员点击 Redis Resource Draft 的连接测试
- **THEN** 系统不执行 KEYS 或 SCAN，不返回任何业务 key

#### Scenario: 验证前缀存在数据
- **WHEN** 系统生成的有界 SCAN 找到匹配 key
- **THEN** 验证证据保存匹配数量和摘要，不保存完整 key 列表

#### Scenario: 验证前缀零匹配
- **WHEN** 有界 SCAN 成功但没有匹配 key
- **THEN** Policy 可以带明确 warning 发布，系统不得自动缩短或扩大前缀

### Requirement: 同一 Workshop 的所有 placement 必须共享一个策略语义
对于同一逻辑 Workshop，Application Publication 中 cloud、edge 或无 placement 的同类资源 Mapping MUST 使用同一个 Workshop Partition Policy Revision；系统 MUST NOT 允许为不同 placement 配置不同数据库或 Redis 隔离边界。

#### Scenario: 云边使用同一 Policy
- **WHEN** GL001 同时绑定 cloud 和 edge 数据库 Resource Revision
- **THEN** 两条 Mapping 都引用同一个 GL001 Partition Policy Revision

#### Scenario: 云边策略不一致
- **WHEN** cloud Mapping 引用 GL001 Policy A 而 edge Mapping 引用 GL001 Policy B
- **THEN** Application Publish 拒绝并指出同一逻辑 Workshop 的策略不一致


<!-- Reconciled from mcp_new capability: `standard-mcp-tool-runtime` -->

### Requirement: 双 Runtime 只使用固定标准 MCP Tool Server
系统 SHALL 由单一 `tool-mcp` 服务使用官方 MCP SDK 向 Python 与 TypeScript Runtime 提供工具；Runtime MUST 只连接部署固定的私网地址和 `server_code=tool-mcp`，不得接受 Agent、Application、用户或模型提供的 MCP Server URL。

#### Scenario: 两个 Runtime 调用同一工具
- **WHEN** Python 与 TypeScript Runtime 分别执行冻结了同一 Tool 的 Job
- **THEN** 两端必须使用同一 MCP Tool schema 和等价执行语义

#### Scenario: payload 提供自定义 Server
- **WHEN** 请求或模型输出包含自定义 MCP URL、Server code 或 transport
- **THEN** Runtime 和 `tool-mcp` 必须在连接或调用前拒绝

### Requirement: MCP Tool 实现必须由代码 Manifest 拥有
系统 MUST 从代码 Manifest 注册稳定 Tool identifier、描述、输入 Schema、只读标记、资源类型和实现函数；数据库和管理 API MUST NOT 创建或覆盖 URL、SQL、Shell、脚本、模板或任意可执行实现。

#### Scenario: 部署合法 Manifest
- **WHEN** `tool-mcp` 启动并加载无冲突的代码 Manifest
- **THEN** MCP `tools/list` 只返回当前 Job 冻结且授权的 Manifest 子集

#### Scenario: 管理端提交动态实现
- **WHEN** 管理端尝试创建任意 MCP/HTTP/SQL/Shell/脚本实现
- **THEN** 系统拒绝且不持久化该内容

### Requirement: MCP 调用必须绑定有效 Job
每个 MCP 调用 MUST 携带非敏感 Job 标识；`tool-mcp` MUST 重新读取 Job，并要求状态为 RUNNING、Runtime/protocol 合法、Tool 存在于 Job 冻结集合且 schema hash 一致。

#### Scenario: 合法 Job 调用冻结工具
- **WHEN** RUNNING Job 调用其冻结的精确 Tool
- **THEN** `tool-mcp` 进入资源、权限和只读策略校验

#### Scenario: Job 或 Tool 不匹配
- **WHEN** Job 不存在、非 RUNNING、Tool 未冻结或 schema hash 漂移
- **THEN** 调用在连接上游前失败关闭

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
`tool-mcp` MUST 不签发或验证 Bearer Token/JWT，不挂载 Runtime Grant，不拥有 signing key，不新增 MCP 专用 RBAC、授权表或 Resource Mapping；业务权限由 Job、角色、应用和工具实现复核。

#### Scenario: Runtime 调用 MCP
- **WHEN** Runtime 发起工具调用
- **THEN** 请求不包含 Runtime Grant、模型 Key、Internal API Token 或 MCP access token

#### Scenario: 请求携带 Authorization
- **WHEN** MCP HTTP 请求携带 Authorization header
- **THEN** 服务拒绝该请求，避免形成未定义凭据协议

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
