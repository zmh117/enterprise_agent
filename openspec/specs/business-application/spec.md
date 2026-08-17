# business-application Specification

## Purpose
定义业务应用对 Agent、Capability、内置工具、入口、权限和运行策略的装配、发布与路由契约。
## Requirements

<!-- Reconciled from mcp_new capability: `application-tool-resource-composition` -->

### Requirement: Agent 与 Application 必须冻结精确 MCP Tool 子集
Agent Publication SHALL 冻结代码 Manifest 中精确 Tool identifier 与 schema hash；Application Publication MUST 只冻结所选 Agent Tool Envelope 的显式子集，不得保存 Capability Release、Handler Version、Resource Mapping 或动态 Server URL。

#### Scenario: 应用选择 Agent 工具子集
- **WHEN** 管理员从 Agent Publication 的 MCP Tool Envelope 选择部分工具并发布应用
- **THEN** Application Publication 冻结 identifier/schema hash 子集且后续代码变化不自动替换

### Requirement: Job 必须冻结工具但不得冻结调用目标
Job 创建时 MUST 冻结 Agent/Application Tool 交集、当前用户有效 Tool grant 与发布/授权摘要；MUST NOT 从 DingTalk Routing Context 或用户消息冻结 `environment`、`base`、`workshop`、`placement`，也 MUST NOT 复制 Application Resource Mapping。目标由 Agent 按已发布 Skill 在每次 Tool Call 中显式提供，并由服务端实时复核当前数据范围。

#### Scenario: 配置在 Job 重试前变化
- **WHEN** Tool Manifest、角色 Grant、工具资源或后续用户消息在 Job 首次执行后变化
- **THEN** 重试继续使用原 Job 工具发布快照，但使用本次 Tool Call 目标，并对撤权、越界和资源歧义失败关闭

#### Scenario: Routing Context 目标为空但消息提供环境
- **WHEN** DingTalk Routing Context 的目标字段为空而当前消息明确要求 `environment=test`
- **THEN** Agent 可以按 Skill 以 `environment=test` 调用已分配 Tool，服务端不得用空 Routing Context 覆盖或拒绝该目标

### Requirement: Tool 可调用性必须满足业务治理交集
运行时 MUST 只暴露同时满足 Agent Envelope、Application 子集、有效角色 Tool grant、应用访问、业务数据范围、Manifest/schema 一致和唯一资源解析的 Tool。

#### Scenario: 用户有工具权限但应用未选择
- **WHEN** 用户具有 Tool grant 但 Application Publication 未选择该 Tool
- **THEN** 模型不得获得该 Tool，直接调用也必须被拒绝

### Requirement: 遗留目标冻结存储必须不存在
系统 MUST NOT 保留 `business_application_revision_target`、`business_application_publication_target`、`agent_job_execution_scope` 或 `agent_job.execution_scope_id/execution_scope_hash` 作为运行目标或授权事实；会话隔离继续使用 `agent_session.execution_scope_hash`，实际工具目标只来自本次 Tool Call 并实时鉴权。

#### Scenario: 已有数据库升级
- **WHEN** 已执行旧目标冻结迁移的数据库升级到本变更最终 schema
- **THEN** 遗留目标表、Job 目标列和索引被删除，而历史 Job 主记录、Tool Call 审计与会话隔离事实保持可读

<!-- Reconciled from mcp_new capability: `business-application-admin-workbench` -->

### Requirement: 管理API受统一身份和应用级权限保护
系统 SHALL 复用现有Web Session、RBAC和CSRF保护Business Application管理API，并 MUST 使用`business_application`资源及read、create、edit、publish、activate动作进行授权。

#### Scenario: 有权用户读取应用
- **WHEN** 已认证内部用户具有目标项目或应用的read权限
- **THEN** API返回其可见的业务应用列表和详情
- **AND** 不返回无权访问应用的摘要

#### Scenario: 未授权用户访问具体应用
- **WHEN** 用户无权读取指定应用
- **THEN** API返回404或等效防枚举结果
- **AND** 审计记录拒绝原因但不泄露应用内容

#### Scenario: 缺少CSRF执行写操作
- **WHEN** 已登录用户创建、编辑、发布、激活或停用应用但请求缺少有效CSRF
- **THEN** 系统拒绝请求且不产生控制面变更

### Requirement: 管理API覆盖业务应用完整控制面生命周期
系统 SHALL 提供应用列表、详情、创建、元数据更新、草稿保存、校验、发布、发布历史、环境激活、环境停用和effective配置查询接口。

#### Scenario: 创建并发布应用
- **WHEN** 有权限用户依次创建应用、保存合法草稿、校验并发布
- **THEN** 每个接口返回明确的应用、revision、validation或publication资源
- **AND** 响应包含下一步所需的revision与完整性摘要

#### Scenario: 查询应用详情
- **WHEN** 用户读取业务应用详情
- **THEN** API返回稳定定义、最新草稿、校验结果、publication历史、各环境deployment和`runtime_wired`状态
- **AND** 不返回组件内部Secret或底层连接信息

#### Scenario: 请求包含未知字段
- **WHEN** 创建或编辑请求包含协议未定义字段
- **THEN** API返回422并拒绝整个请求

### Requirement: 管理API提供稳定的并发与错误契约
系统 MUST 使用expected revision处理所有可变资源，并 SHALL 区分validation、conflict、forbidden、not found和integrity错误。

#### Scenario: 草稿revision冲突
- **WHEN** 客户端使用过期expected revision保存草稿
- **THEN** API返回409和当前revision的非敏感摘要
- **AND** 客户端能够刷新后人工合并而不是静默覆盖

#### Scenario: 发布校验失败
- **WHEN** 用户发布存在多个组件或策略错误的草稿
- **THEN** API返回可定位到字段、binding或组件的全部安全错误
- **AND** 不只返回首个错误或内部堆栈

### Requirement: Web提供真实的业务应用列表与详情工作区
系统 SHALL 将“业务应用”导航连接到真实列表和详情页面，并 MUST 使用管理API数据替换该区域的静态应用fixture。

#### Scenario: 查看业务应用列表
- **WHEN** 已有管理会话的用户进入业务应用
- **THEN** 页面展示真实应用名称、编码、项目、状态、最新revision、publication和环境激活摘要
- **AND** 提供清晰的加载、空数据和错误状态

#### Scenario: 查看业务应用详情
- **WHEN** 用户选择一个可见应用
- **THEN** 页面展示概览、组成配置、校验结果、发布历史和环境状态
- **AND** 流程设计只展示被引用Workflow Publication及尚未提供画布的说明

#### Scenario: 前端未登录
- **WHEN** 管理API返回401
- **THEN** 页面显示需要现有管理会话的明确状态
- **AND** 不显示虚构业务应用、模拟成功数据或本变更内的登录表单

### Requirement: Web支持受控的应用编辑、校验和发布
系统 SHALL 为有权限用户提供严格表单来创建应用、编辑草稿、请求校验、发布和管理环境激活，并 MUST 根据权限、revision和校验结果控制动作可用性。

#### Scenario: 保存应用草稿
- **WHEN** 用户选择合法Agent Publication、Workflow Publication、Trigger、Delivery和策略并提交
- **THEN** 页面发送当前expected revision并展示服务器返回的新revision
- **AND** 页面不会将Secret、底层URL或任意工具配置提交给API

#### Scenario: 校验失败后修正
- **WHEN** API返回字段和组件校验错误
- **THEN** 页面在对应配置区域展示错误并保留用户可安全重试的输入
- **AND** 发布和激活动作保持禁用

#### Scenario: 发布但尚未运行时接线
- **WHEN** 用户成功发布或激活应用
- **THEN** 页面更新publication与deployment状态
- **AND** 明确提示该基础版本尚未接管钉钉或Webhook运行时

### Requirement: Capability和数据源安全边界在真实页面中保持有效
系统 MUST 只展示受目录治理的API Capability引用，第一版在目录未接入时 MUST 禁止录入任意Capability、HTTP、SQL、Redis命令、LogQL、Shell和底层连接配置。

#### Scenario: 查看Capability组成区域
- **WHEN** 用户查看或编辑应用组成
- **THEN** 页面显示Capability目录尚未接入和当前列表为空的状态
- **AND** 不提供自由文本URL、SQL、Redis、Loki或工具名输入框

#### Scenario: 查看Channel和Delivery引用
- **WHEN** 页面展示需要凭据的connector
- **THEN** 只显示connector名称、ID、方向和配置状态
- **AND** 不显示Secret URI解析结果、Token、密码或完整Webhook URL

### Requirement: 业务应用工作区满足响应式和可访问性要求
系统 SHALL 在桌面和窄屏下保持列表、详情、表单、校验错误、版本历史和环境状态可读，并 MUST 为状态、禁用原因和异步操作提供文本语义。

#### Scenario: 窄屏编辑应用
- **WHEN** 用户在窄屏查看详情或表单
- **THEN** 页面使用单列或可滚动局部区域保持字段和操作可访问
- **AND** 不出现阻止整体阅读的横向页面溢出

#### Scenario: 键盘和辅助技术操作
- **WHEN** 用户通过键盘或辅助技术浏览、提交或查看错误
- **THEN** 表单标签、状态、错误摘要、按钮和禁用原因具有可理解名称
- **AND** 关键状态不只通过颜色表达

<!-- Reconciled from mcp_new capability: `business-application-control-plane` -->

### Requirement: 系统持久化稳定的业务应用聚合
系统 SHALL 为每个 Business Application 持久化唯一编码、名称、描述、项目范围、负责人、生命周期状态和当前修订信息，并 MUST 将业务应用作为 Agent、Workflow、Channel 和未来 API Capability 的装配边界。

#### Scenario: 创建业务应用
- **WHEN** 有创建权限的内部用户提交合法且未被占用的应用编码、名称和项目范围
- **THEN** 系统创建稳定的业务应用定义和初始草稿修订
- **AND** 创建操作不会启动 Agent Job 或修改任何入口路由

#### Scenario: 重复应用编码
- **WHEN** 用户创建的应用编码已经存在
- **THEN** 系统拒绝创建并返回可识别的冲突错误
- **AND** 已存在应用及其草稿保持不变

### Requirement: 业务应用通过草稿修订装配版本化组件
系统 SHALL 使用草稿修订保存一个 Agent Publication、零个或一个 Workflow Publication、Trigger Binding、Delivery Binding、会话策略、执行策略和 API Capability 引用，并 MUST NOT 直接引用可变的 Agent 或 Workflow 草稿。

#### Scenario: 保存完整应用草稿
- **WHEN** 用户为业务应用选择已发布 Agent、已发布 Workflow、合法 Trigger 和 Delivery，并保存策略
- **THEN** 系统创建新的应用草稿 revision 并保存各组件的稳定引用
- **AND** 先前 revision 的内容保持不变

#### Scenario: 尝试引用组件草稿
- **WHEN** 用户提交 Agent Revision 或 Workflow 草稿而不是 Publication
- **THEN** 系统拒绝该引用并返回对应字段错误

#### Scenario: Capability目录尚未接入
- **WHEN** 应用草稿包含非空 API Capability 编码而当前没有可解析的 Capability Catalog
- **THEN** 系统可以保存该草稿引用用于后续补全
- **AND** 系统 MUST 在发布校验中将其标记为未解析并阻止发布

### Requirement: 应用策略采用严格的受控结构
系统 SHALL 对 Trigger、Actor、Session、Execution 和 Delivery 策略执行严格 schema 校验，MUST 拒绝未知字段、未知枚举、越界限制、任意 URL、底层查询语言和敏感凭据。

#### Scenario: 保存钉钉当前发送人策略
- **WHEN** 钉钉 Trigger 使用 `CURRENT_SENDER` actor policy 并引用允许入口的 connector
- **THEN** 系统接受该受控策略并保存非敏感 connector 与路由标识

#### Scenario: 保存Webhook服务身份策略
- **WHEN** Webhook Trigger 使用 `SERVICE_ACCOUNT` actor policy
- **THEN** 系统要求引用一个已启用的内部服务主体
- **AND** 不允许在策略中直接提交外部系统用户名、密码或 Token

#### Scenario: 提交不安全配置
- **WHEN** 草稿包含数据库连接、Redis地址、Loki地址、SQL、LogQL、Shell、任意HTTP URL、Password、Secret或Token字段
- **THEN** 系统拒绝保存并返回安全的字段级校验错误
- **AND** 错误、日志和审计中不回显敏感值

### Requirement: 应用写入使用乐观并发控制
系统 MUST 要求应用元数据和草稿写请求携带预期 revision，并 SHALL 在预期 revision 与当前值不一致时拒绝覆盖。

#### Scenario: 更新最新草稿
- **WHEN** 用户提交的 expected revision 等于当前应用 revision
- **THEN** 系统原子创建下一草稿 revision 并返回新的 revision

#### Scenario: 两个管理员并发编辑
- **WHEN** 第二个管理员基于已经过期的 revision 保存应用
- **THEN** 系统返回冲突错误并包含当前 revision 的非敏感摘要
- **AND** 不覆盖第一个管理员已经保存的修改

### Requirement: 应用生命周期不删除历史事实
系统 SHALL 支持 enabled、disabled 和 archived 生命周期状态，MUST 保留草稿、发布快照、部署和审计历史，并 MUST 阻止 disabled 或 archived 应用的新发布和激活。

#### Scenario: 停用业务应用
- **WHEN** 有管理权限的用户将应用从 enabled 改为 disabled
- **THEN** 系统保留全部历史数据并拒绝后续发布或激活
- **AND** 已有环境 deployment 必须由显式停用操作处理，不进行隐式数据删除

#### Scenario: 归档业务应用
- **WHEN** 用户归档一个不存在活动 deployment 的业务应用
- **THEN** 系统将应用标记为 archived 并从默认可编辑列表中隐藏
- **AND** 历史查询仍可读取其 publication 和 audit

### Requirement: 控制面变更不自动改变现有数据面
系统 MUST 将业务应用草稿、发布和激活作为控制面配置管理，第一版 MUST NOT 自动修改钉钉入口、Webhook入口、Agent Job创建、RabbitMQ消费或Delivery路径。

#### Scenario: 发布并激活应用
- **WHEN** 管理员发布业务应用并在测试环境激活
- **THEN** 系统更新业务应用控制面数据和解析读模型
- **AND** 现有钉钉和Webhook消息仍沿用原默认Agent执行链路

#### Scenario: 查询应用运行时接线状态
- **WHEN** 管理端读取应用详情或激活结果
- **THEN** 响应明确返回当前 `runtime_wired=false` 或等效状态
- **AND** 不暗示该应用已经接管生产入口

<!-- Reconciled from mcp_new capability: `business-application-execution-policy` -->

### Requirement: 业务应用执行策略必须固定到Agent Job
系统 MUST 在业务应用路由命中且创建 Agent Job 前，从命中的 Business Application Publication 读取 `max_turns`、`timeout_seconds` 和 `max_tool_calls`，计算有效执行策略并把请求值、有效值、策略版本及来源 Publication 一并持久化到 Job。迁移后的每个新 Agent Job MUST 具有合法 v1 Execution Policy 快照；Worker MUST 只使用 Job 固定的策略，MUST NOT 在消费、重试或执行时重新解析当前活动 Deployment。

#### Scenario: 命中业务应用并创建Job
- **WHEN** 钉钉消息命中一个活动 Business Application Publication
- **THEN** Job 在发布到 RabbitMQ 前保存不可变的业务应用 Execution Policy 快照
- **AND** 快照记录 Business Application Publication、Agent Publication 和配置 hash 来源

#### Scenario: Job入队后激活新版本
- **WHEN** Job 已入队后管理员发布或激活了不同的业务应用策略
- **THEN** 已入队 Job 及其后续重试继续使用原固定策略
- **AND** 只有新创建的 Job 使用新策略

#### Scenario: 非业务应用入口创建Job
- **WHEN** 调试入口、普通 Agent 入口或其他非 Business Application 入口创建新 Job
- **THEN** Job 创建服务从固定 Agent Publication 或运行时默认值生成合法 v1 Execution Policy 快照
- **AND** 不允许持久化空策略 Job

#### Scenario: Worker遇到缺失策略的Job
- **WHEN** Worker 读取到缺少 v1 Execution Policy 快照或快照无法通过 schema 校验的 Job
- **THEN** 系统以不可重试的 Job 完整性错误停止执行
- **AND** 不使用 Agent Publication 或全局默认值在 Worker 阶段补齐策略

### Requirement: 有效执行策略必须确定且不能扩大Agent限制
系统 SHALL 以固定 Agent Publication 的执行限制为基础，对 `max_turns` 和 `timeout_seconds` 取业务应用请求值与 Agent 限制中的更严格值；Agent Publication 缺少对应值时 SHALL 使用现有运行时默认值。`max_tool_calls` SHALL 使用业务应用快照中的规范化值，并遵守现有字段范围。管理 API 和运行记录 MUST 同时区分请求值与有效值。

#### Scenario: 业务应用策略比Agent更严格
- **WHEN** Agent Publication 允许 `max_turns=20` 且业务应用请求 `max_turns=8`
- **THEN** Job 的有效 `max_turns` 为 `8`

#### Scenario: 业务应用策略比Agent更宽松
- **WHEN** Agent Publication 允许 `timeout_seconds=180` 且业务应用请求 `timeout_seconds=300`
- **THEN** Job 的有效 `timeout_seconds` 为 `180`
- **AND** 管理端能够看到请求值 `300` 和有效值 `180`

#### Scenario: 禁止所有工具调用
- **WHEN** 业务应用配置 `max_tool_calls=0`
- **THEN** Agent 可以生成不调用工具的答复
- **AND** 第一次内部工具调用在进入 ToolRegistry 前被策略拒绝

### Requirement: Worker必须强制执行三个策略字段
系统 MUST 对每次 Agent 执行 attempt 强制执行有效 `max_turns`、`timeout_seconds` 和 `max_tool_calls`。工具调用次数 SHALL 统计该 attempt 内所有进入内部 MCP 工具桥的成功或失败调用尝试，超过上限的调用 MUST NOT 进入 ToolRegistry 或任何下游数据源。

#### Scenario: 达到最大轮次
- **WHEN** Agent 执行达到固定的 `max_turns` 且未产生有效最终结果
- **THEN** 系统以稳定的最大轮次耗尽错误结束该 attempt
- **AND** 保留耗尽前已产生的安全工具事件

#### Scenario: 达到墙钟超时
- **WHEN** Agent attempt 超过固定的 `timeout_seconds`
- **THEN** 系统取消当前 SDK 执行并记录安全超时原因
- **AND** 后续是否重试继续遵守现有 timeout retry 策略及同一固定执行策略

#### Scenario: 超过最大工具调用数
- **WHEN** 当前 attempt 已使用完 `max_tool_calls`
- **THEN** 下一次工具调用以 `execution_policy_max_tool_calls_exhausted` 或等价稳定错误码终止
- **AND** 系统不调用 ToolRegistry、不访问数据库、Redis、Loki 或其他下游
- **AND** 该策略耗尽不得作为普通瞬时传输错误重试

### Requirement: 策略耗尽必须可审计并安全通知
系统 MUST 保存策略来源、有效值、实际工具调用次数、耗尽字段、Job 状态和安全错误码，并 SHALL 复用现有失败投递链把不含内部配置或敏感数据的提示回复到原钉钉会话。

#### Scenario: 工具调用预算耗尽
- **WHEN** Job 因 `max_tool_calls` 耗尽失败
- **THEN** 运行记录显示固定有效上限、已使用次数和稳定错误码
- **AND** 原钉钉会话收到安全失败提示
- **AND** 审计不包含 Secret、Token、完整工具响应或私有模型推理

#### Scenario: 查询成功Job的策略来源
- **WHEN** 管理员查看一个由业务应用创建并成功完成的 Job
- **THEN** 运行记录展示 Business Application Publication、Agent Publication、请求策略和有效策略

### Requirement: 接管状态必须区分同步关键路径和后台治理缺口
系统 SHALL 仅使用影响消息同步执行关键路径的组件计算 `runtime_status`，并 MUST 继续逐字段报告不在关键路径上的治理能力。Trigger routing、Agent Publication、会话上下文策略、Execution Policy、声明的 Workflow 以及 Delivery 属于同步关键路径；未实现的 `retention_days` 清理属于非阻塞后台治理缺口。

#### Scenario: 执行策略全部接线但retention未接线
- **WHEN** Trigger、Agent Publication、会话上下文、三个 Execution Policy 字段和 Delivery 均已执行，未配置 Workflow 或其他未支持的同步能力，但 `retention_days` 仍为 `stored_only`
- **THEN** `runtime_wired` 为 `true` 且整体 `runtime_status` 为 `wired`
- **AND** `retention_days` 继续显示 `stored_only` 和稳定 reason code
- **AND** 管理端显示非阻塞数据治理提示，不宣称已执行历史消息清理

#### Scenario: Execution Policy仍有字段未执行
- **WHEN** 任一已配置 Execution Policy 字段未被 Worker 强制执行
- **THEN** 整体 `runtime_status` 为 `partially_wired`
- **AND** 未执行字段明确显示 `stored_only`

#### Scenario: 已配置Workflow但没有执行引擎
- **WHEN** Publication 声明了 Workflow Publication 但运行时仍不执行 Workflow
- **THEN** Workflow 保持 `stored_only`
- **AND** 整体 `runtime_status` 保持 `partially_wired`

### Requirement: 本变更不得实现retention清理
系统 MUST NOT 因本变更新增按 `retention_days` 删除或归档会话、消息、摘要、附件、Job、工具调用或审计事件的 Worker、定时任务或队列。

#### Scenario: retention_days已经到期
- **WHEN** 某会话年龄超过其保存的 `retention_days`
- **THEN** 本变更不自动删除或归档该会话数据
- **AND** 管理端继续把该字段标记为尚未接线的治理能力

### Requirement: 迁移必须删除不兼容旧Job及关联运行数据
系统 MUST 在维护窗口中删除迁移前没有 v1 Execution Policy 快照的旧 Agent Job，并 MUST 同步清理依赖这些 Job 的 session、message、step、tool call、artifact、delivery、attachment、关联 Webhook 运行事件和 Job 级 audit 数据。系统 MUST 保留用户、外部身份、RBAC、Agent、Business Application、Publication、Deployment、Connector、Secret 和其他控制面配置。

#### Scenario: 测试数据库包含旧Job
- **WHEN** 执行本变更数据库迁移且现有 Agent Job 没有 v1 Execution Policy 快照
- **THEN** 系统按外键安全顺序删除旧 Job 及其关联运行数据
- **AND** 迁移结束后 `agent_job` 不存在缺少合法策略快照的记录

#### Scenario: 旧Job包含附件对象
- **WHEN** 被删除的旧 Job 关联 MinIO 中的附件或运行产物对象
- **THEN** 一次性维护清理流程删除对应对象和数据库元数据
- **AND** 不留下能够被新会话继续引用的孤儿附件

#### Scenario: 保留控制面配置
- **WHEN** 旧运行数据清理完成
- **THEN** 已配置用户、身份绑定、Agent Publication、Business Application Publication、local Deployment 和 Connector 仍然存在
- **AND** 管理员无需重新建立控制面配置

<!-- Reconciled from mcp_new capability: `business-application-publication` -->

### Requirement: 发布前执行跨组件完整校验
系统 MUST 在创建 Business Application Publication 前校验应用状态、草稿完整性、Agent Publication、Workflow Publication、Channel Connector、Trigger、Actor、Delivery、MCP Tool 子集、业务范围和策略约束。所选 Agent Publication MUST 包含受支持且一致的 `python-v1` runtime kind；应用草稿不得保存 Runtime override、API Capability 或 Resource Mapping。历史 `typescript-v1` Application Publication 只可读取，不得用于创建新 Publication。

#### Scenario: 发布合法草稿
- **WHEN** enabled 应用引用有效 Python Agent Publication、Agent Envelope 内的 MCP Tool 子集和其它合法组件
- **THEN** 系统允许创建 Publication，Runtime 由 Agent Publication 唯一派生并固定为 `python-v1`

#### Scenario: 引用已禁用或不存在的组件
- **WHEN** 草稿引用不存在、已禁用、完整性失败或范围冲突的组件
- **THEN** 系统拒绝且不创建部分 Publication

#### Scenario: 未解析MCP Tool
- **WHEN** 草稿包含所选 Agent Publication Envelope 中不存在或 schema hash 不一致的 Tool
- **THEN** 系统拒绝并指出未解析 Tool，不映射为其它工具

#### Scenario: Agent Runtime不受支持
- **WHEN** 所选 Agent Publication runtime kind 缺失、为 `typescript-v1`、不受支持或与 Definition 不一致
- **THEN** 系统拒绝且不猜测或改写 Runtime

#### Scenario: 应用提交旧平台字段
- **WHEN** payload 提交 runtime override、API Capability、Handler、Connection 或 Resource Mapping 字段
- **THEN** 系统拒绝旧字段且不保存兼容数据

### Requirement: 发布创建不可变且可验证的应用快照
系统 SHALL 为每次成功发布创建不可变 snapshot，冻结应用元数据、组件 Publication ID/revision/hash、Agent runtime kind、Trigger、Delivery、精确 MCP Tool 子集、业务范围和策略，并保存 schema version 与 canonical SHA-256。Snapshot MUST NOT 包含 API Capability、Handler、API Connection 或 Resource Mapping。

#### Scenario: 创建应用发布快照
- **WHEN** 合法 revision 首次发布
- **THEN** 系统在单一事务中创建 Publication、Snapshot、hash 和审计

#### Scenario: 组件后续产生新版本
- **WHEN** Agent、Workflow 或 Tool Manifest 后续变化
- **THEN** 已有 Publication 仍使用冻结版本；只有新应用 Revision 可采用新值

#### Scenario: 检测快照篡改
- **WHEN** canonical hash、Runtime 投影或 Tool schema hash 不一致
- **THEN** 系统拒绝解析和激活并记录安全审计

### Requirement: 发布与环境激活相互分离
系统 SHALL 允许 publication 在不影响任何环境的情况下创建，并 MUST 通过显式 deployment 操作将一个有效 publication 激活到指定环境。

#### Scenario: 仅发布不激活
- **WHEN** 管理员成功发布一个应用 revision
- **THEN** publication 出现在历史中但所有环境 deployment 保持原值
- **AND** Resolver 不会因为发布本身自动选择该版本

#### Scenario: 激活到测试环境
- **WHEN** 有 activate 权限的用户将有效 publication 激活到 test 环境并携带正确 expected revision
- **THEN** 系统原子更新该应用 test deployment
- **AND** production环境 deployment 不受影响

### Requirement: 环境激活拒绝Trigger路由冲突
系统 MUST 在激活时使用 environment、trigger type、connector ID 和规范化 routing key 检查所有活动 deployment，并 SHALL 拒绝导致非确定性路由的冲突。

#### Scenario: 激活唯一Trigger
- **WHEN** publication 的每个 Trigger 在目标环境都没有被其他活动应用占用
- **THEN** 系统允许激活并建立唯一解析投影

#### Scenario: 两个应用争用同一路由键
- **WHEN** 另一个已激活应用已经占用相同 environment、trigger type、connector ID 和 routing key
- **THEN** 系统拒绝激活并返回冲突应用的安全标识
- **AND** 目标环境现有 deployment 保持不变

### Requirement: Resolver确定性读取活动应用
系统 SHALL 按 application/environment 或规范化 Trigger 键解析唯一活动 Publication，并返回 Agent/Workflow、Trigger、Delivery、MCP Tool 子集、业务范围、策略和完整性摘要；MUST NOT 返回旧 Capability/Resource Mapping 或 Secret。

#### Scenario: 按应用解析活动发布
- **WHEN** 查询 enabled 应用在 test 环境的有效配置
- **THEN** Resolver 返回唯一 Publication 与 MCP Tool 子集且不含 Secret

#### Scenario: 按Trigger解析活动应用
- **WHEN** 使用唯一 environment、trigger type、connector ID 和 routing key 查询
- **THEN** Resolver 返回唯一业务应用及活动 Publication

#### Scenario: 没有有效部署
- **WHEN** 应用未激活、已停用或完整性失败
- **THEN** Resolver 返回非重试配置错误且不回退

### Requirement: 历史publication可以显式重新激活
系统 SHALL 允许有权限的用户把仍然满足当前完整性校验且引用 Python Agent Publication 的历史 Application Publication 重新激活到环境以实现回退，并 MUST 支持显式停用环境 deployment。引用 `typescript-v1` Agent Publication 的历史版本 MUST 保持只读且不得重新激活。

#### Scenario: 回退到历史Python版本
- **WHEN** 用户选择一个通过当前完整性和依赖校验且 runtime kind 为 `python-v1` 的历史 publication 并激活
- **THEN** deployment 原子指向该历史 publication
- **AND** 系统记录旧、新 publication ID 和操作人

#### Scenario: 尝试激活历史TypeScript版本
- **WHEN** 用户选择仍引用 `typescript-v1` Agent Publication 的历史 Application Publication
- **THEN** 系统拒绝激活并提示创建引用 Python Agent Publication 的新 revision
- **AND** 当前 deployment 保持不变

#### Scenario: 停用环境部署
- **WHEN** 用户对当前 deployment 执行 deactivate 并提供正确 expected revision
- **THEN** 系统将该环境标记为未激活并移除活动路由投影
- **AND** publication 历史保持不变

### Requirement: 发布和解析过程不得保存或暴露凭据
系统 MUST 只在应用 snapshot、deployment、Resolver结果和审计中保存非敏感组件标识与Secret引用，MUST NOT 保存或返回真实密码、Token、Webhook Secret、完整敏感URL或底层数据源连接。

#### Scenario: 发布包含connector引用的应用
- **WHEN** 应用引用需要凭据的钉钉、Webhook或未来API平台connector
- **THEN** snapshot只保存connector ID和非敏感策略
- **AND** 凭据继续由connector或Credential边界解析

#### Scenario: 查看发布历史
- **WHEN** 管理员读取publication列表或详情
- **THEN** API返回版本、hash、组件引用、环境和审计摘要
- **AND** 不返回任何Secret值或可直接访问外部系统的认证材料

### Requirement: 应用必须通过Agent Publication选择Runtime
Business Application 管理 API 与前端 SHALL 允许管理员从有效 Python Agent Publication 中选择一个版本，并展示 Agent code、publication revision 和只读 `python-v1` runtime kind。发布新 Agent 不得自动切换任何应用；切换必须创建并发布新的应用 revision，并按现有规则显式激活。历史 TypeScript Application Publication SHALL 保留原 runtime kind 供审计，但不得成为新草稿来源或重新激活目标。

#### Scenario: 应用选择Python Agent
- **WHEN** 管理员选择有效 Python Agent Publication
- **THEN** 应用页面显示 `python-v1`，后续新 Job 从该 Publication 固定 Python Runtime

#### Scenario: 活动应用从TypeScript迁移到Python
- **WHEN** 现有 deployment 引用历史 TypeScript Agent Publication
- **THEN** 管理员必须创建引用 Python Agent Publication 的新 Application revision、发布并显式激活
- **AND** 系统不修改旧 Application Publication、Agent Publication 或其 hash

#### Scenario: 应用选择TypeScript Agent
- **WHEN** 管理员或旧客户端尝试为新 revision 选择 `typescript-v1` Agent Publication
- **THEN** 系统拒绝发布且不自动替换为相似 Python Agent

#### Scenario: Agent发布新版本
- **WHEN** 已被应用引用的 Python Agent 发布新 revision
- **THEN** 应用继续使用原 Agent Publication，直到管理员显式更新、发布并激活应用

<!-- Reconciled from mcp_new capability: `business-application-role-access` -->

### Requirement: 业务应用是用户运行授权的入口对象
系统 SHALL 允许角色对具体业务应用授予 `invoke` 或等价使用能力。业务应用路由下命中的应用授权 MUST 封装该应用固定的项目和 Agent 运行入口许可，普通管理员不得再为同一路径手工组合项目和 Agent 使用权限。

#### Scenario: 用户通过角色获得应用访问
- **WHEN** 已绑定且启用的用户通过有效角色获得当前激活业务应用的使用权限
- **THEN** 系统允许继续检查该应用的能力和数据范围，而不要求额外配置底层项目和 Agent 使用策略

#### Scenario: 用户未获得应用访问
- **WHEN** 已绑定用户没有任何有效角色允许当前业务应用
- **THEN** 系统在创建 Agent job 前拒绝请求并返回“当前用户无权使用该业务应用”

### Requirement: 每个业务应用独立配置能力和数据范围
系统 SHALL 让角色在每个业务应用授权项下独立选择只读业务能力和环境、基地、车间范围。同一角色绑定多个业务应用时，一个应用的数据范围 MUST NOT 自动用于另一个应用。

#### Scenario: 同一角色的两个应用使用不同范围
- **WHEN** 角色为生产应用选择生产一号基地、为测试应用选择测试基地
- **THEN** 两个应用分别使用自己的能力和范围进行授权，不发生跨应用继承

### Requirement: 业务能力选择受多层安全上限约束
系统 SHALL 只允许角色选择同时满足“业务应用已装配、Agent publication 已允许、平台工具已启用、工具已注册且只读”的业务能力。任一上限后续收紧时 MUST 立即从有效能力集合中排除对应能力。

#### Scenario: 角色勾选未装配能力
- **WHEN** 客户端提交不属于目标业务应用装配集合的能力
- **THEN** 后端拒绝整个授权区提交

#### Scenario: Agent 移除已授权工具
- **WHEN** 新 Agent publication 不再允许角色曾经选择的工具
- **THEN** 该工具不再暴露给运行时，授权中心显示“被 Agent 安全上限阻止”

### Requirement: 当前全部保存明确资源集合
系统 SHALL 将管理员选择的“当前全部”展开为保存时存在的明确环境、基地或车间标识集合，不得创建包含未来新增资源的动态通配授权。

#### Scenario: 授权后新增基地
- **WHEN** 角色保存“当前全部基地”后平台新增一个基地
- **THEN** 新基地默认不属于该角色范围，管理员必须重新编辑角色才能授权

### Requirement: 多角色业务访问按应用合并
系统 SHALL 按当前业务应用合并用户全部有效角色的允许能力和明确数据范围，并 MUST 让高级拒绝优先。系统 MUST 保留每项有效访问的角色来源用于预览和审计。

#### Scenario: 多角色合并同一应用能力
- **WHEN** 一个角色允许日志能力，另一个角色允许数据库能力，且二者都允许同一应用
- **THEN** 用户在各自数据范围内获得两个能力，除非命中高级拒绝或其它安全上限

### Requirement: 平台管理员不隐式获得业务访问
系统 MUST 将管理后台全权限与业务应用使用权限分离。`platform-admin` 只有在另一个显式业务授权项允许时才能运行应用、调用能力或访问数据。

#### Scenario: 平台管理员仅管理授权
- **WHEN** `platform-admin` 未加入任何业务访问角色
- **THEN** 该用户可以创建和配置角色，但不能直接运行受保护业务应用

### Requirement: 旧原始策略仅作为受控兼容和高级例外
系统 SHALL 在独立身份授权重置 change 完成前保留现有用户/角色原始策略的安全兼容读取，不得删除或静默扩大旧策略。命中的应用级显式拒绝 MUST 阻止旧策略回退；新角色配置不得要求普通管理员理解旧策略。

#### Scenario: 旧用户尚未重新配置
- **WHEN** 用户尚无新业务应用授权但仍命中既有项目和 Agent 允许策略
- **THEN** 兼容模式可以保持其原有授权效果，并在授权解释中标记“旧策略兼容”

#### Scenario: 应用级拒绝存在
- **WHEN** 用户命中目标业务应用的高级拒绝
- **THEN** 系统拒绝访问，不得用旧项目或 Agent 允许策略绕过

### Requirement: 服务账号仅通过业务授权参与非交互式入口
系统 SHALL 允许服务账号通过业务访问角色获得 Webhook 等非交互式业务应用权限，但 MUST NOT 因该角色获得管理后台登录或功能权限。

#### Scenario: Webhook 服务账号有业务角色
- **WHEN** Webhook 触发器的启用服务账号获得目标业务应用、能力和数据范围授权
- **THEN** 系统按该服务账号的角色执行应用授权和工具范围检查

<!-- Reconciled from mcp_new capability: `business-application-runtime-routing` -->

### Requirement: 应用部署只使用local且与业务数据环境相互独立
系统 MUST 只允许创建、激活、回退、查询或停用 `local` Business Application Deployment，并 MUST NOT 使用 Channel event 的业务数据 `routing.environment` 选择应用版本。

#### Scenario: 本地运行时处理三九数据范围
- **WHEN** 服务运行于 `APP_ENV=local` 且钉钉事件的 `routing.environment` 为 `sanjiu`
- **THEN** 系统只查询该应用的 `local` Deployment
- **AND** `sanjiu` 原样保留在 Agent Job 的业务 routing context 中

#### Scenario: 管理端请求非local部署
- **WHEN** 管理端请求 `test`、`staging`、`production` 或其他非 `local` Deployment
- **THEN** 管理 API 拒绝请求并返回 `environment` 字段错误
- **AND** 系统不创建 Deployment 或 route 投影

### Requirement: 系统返回统一且真实的运行时接线状态
系统 SHALL 由单一运行时就绪评估器计算 `runtime_wired`、整体 `runtime_status` 和逐组件状态，并 MUST 在应用列表、详情、Publication、Deployment、effective 查询、激活响应和审计中使用同一结果。

#### Scenario: 当前环境存在可执行钉钉路由
- **WHEN** 数据面闸门开启，当前部署环境存在完整且受支持的活动钉钉 route
- **THEN** `runtime_wired` 为 `true`
- **AND** Trigger routing、Agent Publication、Session Policy 和 Delivery 分别返回其真实组件状态

#### Scenario: 只有部分配置已接线
- **WHEN** 钉钉路由可以执行但 Workflow 或 Execution Policy 字段仍只被存储
- **THEN** 整体状态为 `partially_wired`
- **AND** 未执行字段返回 `stored_only` 及稳定 reason code

#### Scenario: 活动路由完整性失败
- **WHEN** 当前环境的活动 route 指向 hash 不一致、schema 不支持或依赖缺失的 Publication
- **THEN** 整体状态为 `blocked`
- **AND** 系统不得把该应用显示为已完整接管

#### Scenario: 数据面闸门关闭
- **WHEN** `FEATURE_PUBLISHED_AGENT_RUNTIME` 关闭
- **THEN** `runtime_wired` 为 `false` 且整体状态为 `not_wired`
- **AND** 响应明确指出数据面闸门未开启

### Requirement: 第一阶段运行时只接管受支持的钉钉Trigger
系统 MUST 只将 `dingtalk_private + CURRENT_SENDER` 和 `dingtalk_group + CURRENT_SENDER` 标记为第一阶段可执行 Trigger，并 SHALL 将 Webhook、Workflow 和 API Capability 等未接线路径明确标记为 `stored_only` 或 `unsupported`。

#### Scenario: 评估钉钉私聊应用
- **WHEN** Publication 包含合法 `dingtalk_private` Trigger 和当前发送人 actor policy
- **THEN** 运行时就绪评估器按钉钉私聊支持矩阵校验该 Trigger

#### Scenario: 评估Webhook Trigger
- **WHEN** Publication 包含 Webhook Trigger
- **THEN** 本变更不让 Business Application Resolver 接管该 Webhook
- **AND** 管理端状态明确为 `stored_only` 而不是已生效

#### Scenario: Publication包含非空Capability
- **WHEN** 应用引用尚未接入目录的 API Capability
- **THEN** 现有发布校验继续阻止发布
- **AND** 系统不得将其映射为数据库、Redis、Loki 或其他内部工具

### Requirement: 活动路由解析是确定性的三态结果
系统 SHALL 将运行时路由解析结果建模为 `matched`、`not_matched` 或 `blocked`，并 MUST 使用部署环境、Trigger type、受信 connector ID 和规范化 routing key 唯一解析活动应用。

#### Scenario: 唯一路由命中
- **WHEN** 当前环境存在唯一且完整的活动 route 与事件规范化路由键相同
- **THEN** Resolver 返回 `matched`、应用、Publication、Deployment、route 和逐组件状态

#### Scenario: 没有活动路由
- **WHEN** 当前环境不存在与事件匹配的活动 route
- **THEN** Resolver 返回 `not_matched`
- **AND** 不把“没有匹配”表示为完整性异常

#### Scenario: 命中路由但Publication损坏
- **WHEN** route 投影存在但关联 Publication 无法通过 schema、hash 或引用完整性校验
- **THEN** Resolver 返回 `blocked` 和安全 reason code
- **AND** 不返回其他业务应用或默认 Agent 作为匹配结果

### Requirement: 未命中和命中后异常均失败关闭
系统 MUST 对 `not_matched` 和 `blocked` 的钉钉事件停止 Job 创建与 MQ 发布、记录审计并触发安全失败通知，MUST NOT 使用默认 Agent 兼容路径。

#### Scenario: 未配置业务应用路由
- **WHEN** 合法钉钉消息的路由结果为 `not_matched`
- **THEN** 系统不创建 Agent Job 或发布 RabbitMQ 消息
- **AND** 记录 `business_application.route.not_matched`
- **AND** 钉钉用户收到“当前机器人未配置可用的业务应用，请联系管理员”

#### Scenario: 已匹配应用配置无效
- **WHEN** 合法钉钉消息命中 route 但运行时结果为 `blocked`
- **THEN** 系统不创建 Agent Job
- **AND** 不静默回退到默认 Agent 或其他应用
- **AND** 钉钉用户收到不含敏感细节的错误通知

### Requirement: 命中应用后固定不可变运行版本
系统 MUST 以命中的 Business Application Publication 固定 Agent Publication 和所有已支持策略，MUST NOT 允许 Channel event、后续激活或 Worker 重新解析覆盖已经固定的版本。

#### Scenario: 入口携带相同Agent Publication
- **WHEN** 命中应用且事件携带的 Agent Publication 与应用快照完全一致
- **THEN** 系统使用应用快照版本创建 Job并记录一致性来源

#### Scenario: 入口尝试覆盖Agent Publication
- **WHEN** 命中应用但事件携带不同 Agent Publication、revision 或 hash
- **THEN** 系统将路由标记为 `blocked/agent_override_conflict`
- **AND** 不创建使用任一冲突版本的 Job

#### Scenario: Job入队后激活新版本
- **WHEN** Job 已固定 Publication 并入队，管理员随后激活新应用 Publication
- **THEN** 已入队 Job 继续使用原固定版本
- **AND** 后续新事件才解析到新版本

### Requirement: 激活回退和停用具有明确运行影响
系统 SHALL 在激活历史或最新 Publication 前执行运行时预检，并 MUST 在激活、回退和停用响应中返回受影响 route、固定的 `local` 部署、接线状态与未命中失败说明。

#### Scenario: 激活到当前运行环境
- **WHEN** 管理员把通过预检的 Publication 激活到当前 `APP_ENV`
- **THEN** 系统原子更新 Deployment 与 route 投影
- **AND** 下一条匹配的新事件使用该 Publication

#### Scenario: 激活已知不可执行的路由
- **WHEN** 当前环境 Publication 的受支持钉钉 Trigger 缺少 bot/conversation identity、有效 Agent 或 reply-original Delivery
- **THEN** 系统拒绝激活并返回字段级或组件级错误
- **AND** 现有 Deployment 保持不变

#### Scenario: 回退到历史Publication
- **WHEN** 管理员重新激活一个仍通过当前运行时预检的历史 Publication
- **THEN** 后续新事件使用历史 Publication
- **AND** 审计记录旧、新 Publication ID 和操作主体

#### Scenario: 停用当前Deployment
- **WHEN** 管理员显式停用当前环境 Deployment
- **THEN** 系统移除对应活动 route 投影
- **AND** 后续无匹配事件失败关闭且不创建 Job
- **AND** 已入队 Job 不受影响

### Requirement: 路由决策可审计且不泄露敏感信息
系统 MUST 以 correlation ID 串联路由、Job、Agent 和 Delivery 阶段，并 SHALL 记录应用、Publication、Deployment、route、结果和安全 reason code，MUST NOT 在运行状态或审计中记录 Secret、Token、完整 session webhook 或敏感原始 payload。

#### Scenario: 应用路由成功创建Job
- **WHEN** 匹配事件成功创建 Agent Job
- **THEN** 审计包含 `matched`、application code、Publication ID、Deployment ID、route ID、job ID 和 correlation ID
- **AND** 不包含可直接调用钉钉的临时凭据

#### Scenario: 路由被阻止
- **WHEN** route 因完整性或策略错误被阻止
- **THEN** 审计记录稳定 reason code 和安全摘要
- **AND** 管理员可以从运行记录定位到对应应用版本

<!-- Reconciled from mcp_new capability: `business-application-ui-prototype` -->

### Requirement: 原型展示一个Runtime多个业务应用的产品模型
系统 SHALL 展示一个共享Agent Runtime、多个Agent Profile和多个Business Application之间的关系，业务应用 MUST 作为前端主要管理对象，而不是把Channel、Workflow、Profile和Capability展示为缺少装配关系的平行资源。

#### Scenario: 查看业务应用组成
- **WHEN** 用户查看任一业务应用卡片或关系摘要
- **THEN** 页面展示该应用引用的Agent Profile、Workflow、触发方式、API Capability数量、输出渠道和发布状态
- **AND** 不暗示每个应用需要部署独立Agent Runtime

### Requirement: 原型展示三个代表性业务应用
系统 SHALL 展示钉钉私聊诊断助手、钉钉群聊诊断助手和Webhook告警分析助手，三个示例 MUST 体现不同的会话主体、触发身份和流程形态。

#### Scenario: 查看钉钉私聊应用
- **WHEN** 用户查看钉钉私聊诊断助手
- **THEN** 页面展示按应用、租户和钉钉用户构成的人员会话语义
- **AND** API调用主体来自当前消息发送人的内部身份

#### Scenario: 查看钉钉群聊应用
- **WHEN** 用户查看钉钉群聊诊断助手
- **THEN** 页面展示群会话上下文和必须@机器人等触发条件
- **AND** 明确API权限仍按当前消息发送人判断而不是按群共享

#### Scenario: 查看Webhook告警应用
- **WHEN** 用户查看Webhook告警分析助手
- **THEN** 页面展示签名与幂等、服务账号、固定API节点、Agent分析和钉钉投递的静态流程
- **AND** 不把Webhook请求伪装成真实人员身份

### Requirement: 原型展示应用工作区目标页签
系统 SHALL 以静态页签或关系卡形式展示应用概览、流程设计、渠道与触发器、能力授权和发布管理的目标结构，但 MUST NOT 实现真实路由和编辑行为。

#### Scenario: 评审应用工作区
- **WHEN** 用户查看业务应用区域
- **THEN** 页面能够识别五个目标工作区及各自职责
- **AND** 编辑、测试、保存、发布和回滚入口处于不可操作状态

### Requirement: 原型区分确定性API节点与Agent自主能力
系统 SHALL 在Workflow预览中区分显式API Capability节点和Agent自主决策节点，并展示两种模式可以在同一流程内组合。

#### Scenario: 查看Webhook混合流程
- **WHEN** 用户查看Webhook告警分析流程
- **THEN** 固定告警查询和日志查询以显式API节点展示
- **AND** Agent节点展示其可继续自主选择的只读Capability集合

### Requirement: 原型展示API Capability而非底层数据源工具
系统 SHALL 使用业务能力编码、名称、描述、风险、环境和可用状态展示Capability，并 MUST NOT 提供数据库、Redis、Loki连接或任意查询语言的配置入口。

#### Scenario: 查看能力目录预览
- **WHEN** 用户查看API能力区域
- **THEN** 页面展示类似`log.query.application`、`order.query.detail`和`cache.query.status`的业务能力
- **AND** 不展示DSN、数据库方言、Redis地址、Loki地址、SQL、Redis命令、LogQL、Shell或任意HTTP URL

### Requirement: 原型展示能力授权交集和版本冻结
系统 SHALL 展示有效能力由平台发布、应用授权、Workflow节点授权、Agent Profile授权和当前主体数据权限取交集，并展示应用发布冻结所引用的Profile、Workflow、Capability、Channel和策略版本。

#### Scenario: 评审应用有效能力
- **WHEN** 用户查看应用的能力授权摘要
- **THEN** 页面展示权限交集而不是“允许全部API”的单一开关
- **AND** 高风险写能力显示为未授权或MVP不可用

#### Scenario: 评审发布快照
- **WHEN** 用户查看发布管理摘要
- **THEN** 页面展示发布版本引用的Profile Revision、Workflow Revision、Capability Version和Channel Binding
- **AND** 不提供真实发布或回滚操作

### Requirement: Business Application 草稿配置任务工作区自然周期
系统 SHALL 在 Business Application 草稿中提供严格结构的 `task_workspace_retention_period`，只允许 `DAY`、`WEEK` 或 `MONTH`，新草稿默认选择 `WEEK`。该字段只控制任务工作区自然周期，MUST NOT 被解释为消息附件、保留文件、消息、Job、工具调用或审计的内容保留期。

#### Scenario: 管理员配置月工作区
- **WHEN** 管理员在业务应用前端选择 `MONTH` 并保存合法预期 revision
- **THEN** 系统创建新草稿 revision并返回规范化策略

#### Scenario: 提交未知周期
- **WHEN** 客户端提交 `ROLLING_24_HOURS`、任意天数或未知字段
- **THEN** 系统使用字段级错误拒绝
- **AND** 不创建部分草稿 revision

### Requirement: Publication 冻结任务工作区保留策略
每个新 Business Application Publication MUST 显式冻结 `task_workspace_retention_period` 并纳入 canonical snapshot、schema version、hash、有效解析结果和审计。既有 Publication 缺少该字段时 MUST 稳定解释为 `WEEK`；管理端后续修改只影响新 Revision 和新 Publication，不得追溯改写既有 Publication 或已创建工作区。

#### Scenario: 发布后修改草稿策略
- **WHEN** 已发布的 P1冻结 `DAY`，管理员随后把新草稿改为 `MONTH`
- **THEN** P1和由P1创建的工作区继续使用 `DAY`
- **AND** 只有后续新 Publication创建的新工作区使用 `MONTH`

#### Scenario: 解析旧 Publication
- **WHEN** 活动历史 Publication 的 snapshot schema 中没有任务工作区保留字段
- **THEN** Resolver 返回规范化 `WEEK`及兼容来源摘要
- **AND** 不修改历史 snapshot或hash

### Requirement: 管理端展示工作区策略的真实接线状态
业务应用列表、详情、发布预览和运行时就绪评估 SHALL 展示任务工作区保留策略及其来源。发布前 MUST 校验 File Service 与 File Worker 能执行该策略；配置已冻结但依赖未就绪时 MUST 返回明确的非敏感组件状态，不得宣称生命周期已执行。

#### Scenario: File Worker 未就绪
- **WHEN** Publication 配置合法但 File Worker 清理能力不可用
- **THEN** 管理端显示任务工作区生命周期组件未就绪及稳定 reason code
- **AND** 不把消息附件或其它 `retention_days` 状态冒充为工作区策略状态

### Requirement: 任务文件能力依赖消息附件策略
Business Application 草稿与管理前端 MUST 显式保存并展示 `session_policy.attachments_enabled` 和 `continuous_conversation_enabled`，不得因表单缺字段把既有值重置为关闭。启用任务工作区时系统 MUST 同时启用消息附件处理和连续会话；后端 MUST 拒绝任务工作区已启用但任一依赖已关闭的矛盾新草稿。历史 Publication 仍按其冻结快照解析，不得追溯改写。

#### Scenario: 管理员启用任务工作区
- **WHEN** 管理员在草稿中启用任一会自动启用任务工作区的任务文件能力
- **THEN** 前端同时把 `session_policy.attachments_enabled` 和 `continuous_conversation_enabled` 设置为 `true`
- **AND** 保存、发布与后续重新编辑均保留该值

#### Scenario: 客户端提交矛盾配置
- **WHEN** 客户端提交 `task_file_features.workspace_enabled=true` 且 `session_policy.attachments_enabled=false`
- **THEN** 后端以 `session_policy.attachments_enabled` 字段级错误拒绝新草稿
- **AND** 不创建部分草稿 Revision

#### Scenario: 客户端关闭连续会话但启用工作区
- **WHEN** 客户端提交 `task_file_features.workspace_enabled=true` 且 `session_policy.continuous_conversation_enabled=false`
- **THEN** 后端以 `session_policy.continuous_conversation_enabled` 字段级错误拒绝新草稿
- **AND** 不创建部分草稿 Revision

### Requirement: File MCP 功能开关必须冻结真实工具能力
当Business Application草稿启用`file_mcp_enabled`、`runtime_file_edit_enabled`或`default_file_delivery_enabled`时，所选Agent Publication MUST 已冻结平台代码清单中的File MCP工具，且Application草稿 MUST 显式选择完成该功能所需的精确File MCP Tool子集。保存、校验、发布和运行时就绪评估 MUST 拒绝或明确报告“功能已开但工具未冻结”的配置，不得仅凭功能开关宣称File MCP可用，也不得把File MCP工具绕过Agent/Application Publication自动注入Job。

#### Scenario: 功能已开但Agent未发布File MCP工具
- **WHEN** 管理员启用`file_mcp_enabled`，但所选Agent Publication没有任何`file-service` Tool
- **THEN** 后端以`agent_publication_id`和`mcp_tools`字段级错误拒绝保存新草稿
- **AND** 前端展示需先创建包含File MCP工具的新Agent Publication

#### Scenario: 功能已开但Application未选择File MCP工具
- **WHEN** 所选Agent Publication含File MCP工具且管理员启用`file_mcp_enabled`，但Application草稿未选择任何`file-service` Tool
- **THEN** 后端以`mcp_tools`字段级错误拒绝保存新草稿
- **AND** 不创建看似可用但Job快照不含File MCP的Publication
