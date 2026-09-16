# execution-delivery Specification

## Purpose
定义 Agent Job 的冻结执行事实、可靠调度、独立 Python Runtime、工具与上下文审计、结果投递和外部操作确认。会话身份与历史窗口见 channel-conversation；文件准入、Manifest 与沙盒见 task-file-workspace；身份签发与 RBAC 见 identity-access。

## Requirements

**任务身份与查询**

### Requirement: Session、Job 与 Message 必须各自拥有明确事实
系统 SHALL 让 Session 保存会话身份与上下文边界，让 `agent_message` 保存有序用户及助手消息，让 `agent_job` 引用 `input_message_id` 并保存固定 provenance、生命周期、重试和结果。创建事务 MUST 固定内部请求人、入口外部身份引用、Agent/Application Publication ID/revision/hash、Deployment/route、routing context、Session Policy、Execution Policy、MCP Tool Snapshot 和授权事实摘要，以及适用的文件 Manifest；不得从当前配置重建历史输入或双写第二份可变消息正文。`agent_session.execution_scope_hash` SHALL 由规范化 routing context 生成并用于会话隔离；Job 不保存独立的 Execution Scope 表或 scope 列，routing context 与会话 hash 不构成工具业务目标或实时授权。

#### Scenario: 创建应用 Job
- **WHEN** 受信入口通过应用、身份和权限校验
- **THEN** 同一事务保存 Session、唯一有序 user message、引用它的 Job 和唯一 dispatch Outbox
- **AND** Webhook Job 另保存 webhook event 与 Trigger publication 来源；未命中活动应用的渠道事件不创建 Job

#### Scenario: 配置在排队后变化
- **WHEN** 应用、Agent 或会话策略在 Job 创建后改变
- **THEN** 执行、重试和 Delivery 使用原冻结来源与 reply route，实际访问继续复核当前授权

#### Scenario: 历史来源缺失
- **WHEN** 历史 Job 缺少应用 provenance 或消息关联
- **THEN** 查询明确返回历史归属或消息不可用状态，不根据当前 Deployment、身份映射或配置回填

### Requirement: Job 状态转换由 Worker 控制
系统 MUST 使用 `WAITING_INPUT`、`PENDING`、`RUNNING`、`RETRY_WAIT`、`SUCCEEDED`、`FAILED` 和 `TIMEOUT` 状态。Worker MUST 原子 claim `PENDING` 或已到期 `RETRY_WAIT`，并在模型调用前复核当前用户、业务应用权限、Publication/hash、Runtime 与执行策略。成功结果和终态时间 MUST 持久化；终态不得重新 claim。文件准入的 `WAITING_INPUT` 仅用于来源下载/导入，详见 task-file-workspace。

#### Scenario: 排队期间权限被撤销
- **WHEN** Worker claim 前发现用户停用、成员到期或应用授权已撤销
- **THEN** Job 以非重试中文安全原因失败，不调用模型或工具

#### Scenario: 重复消息到达
- **WHEN** 两个 Worker 收到同一 PENDING 或到期 RETRY_WAIT Job
- **THEN** 只有一个取得执行权，另一个按数据库状态确认或忽略
- **AND** 已终态 Job 不重新执行、不重复生成成功结果或失败通知

#### Scenario: 文件提交部分失败
- **WHEN** 两个文件提交成功、一个冲突，但 Runtime 正常产出准确最终回复
- **THEN** Job 为 SUCCEEDED，各 Commit 独立记录结果，不新增 PARTIAL Job 状态

### Requirement: Job 工具快照与实际资源解析必须分离
Job MUST 固定内部用户、Agent/Application Publication 和授权事实摘要；MCP Tool Snapshot MUST 冻结允许的 Server/Tool identifier、schema hash 与 effect/confirmation 等执行合同，并保存 authorization hash。快照不得把 routing context、会话 scope hash 或调试范围选择冻结为业务资源目标，也不得保存动态 MCP URL、Handler、Application Resource Mapping 或 Resource Revision binding。每次 Tool Call MUST 在冻结工具集合内重新检查当前角色、应用 Tool 子集与本次业务目标的数据范围；资源型工具 SHALL 按本次参数唯一解析当前 Published Resource Revision，记录实际 placement、Revision、selector/namespace 安全摘要、schema hash 和 correlation ID。

#### Scenario: 同一 Job 查询不同授权目标
- **WHEN** 同一 Job 的两次资源工具调用指定不同目标，且分别通过当前授权和资源唯一性检查
- **THEN** 每次调用记录各自实际目标与 Revision，不用 Job routing context 或 Session hash 替代调用参数，也不创建 Job Execution Scope 快照

#### Scenario: 资源轮换
- **WHEN** Job 创建后同一资源发布新 Revision
- **THEN** 快照不变，后续调用只在当前授权内唯一解析新 Published Revision并记录实际事实，不回退旧 Revision

#### Scenario: 工具 Schema 漂移或资源不唯一
- **WHEN** 当前 Manifest hash 不匹配，或资源解析得到零个/多个候选
- **THEN** 调用在上游连接前失败关闭，不选择相似工具或首个候选

#### Scenario: 运维恢复 Job
- **WHEN** 自动重试、Outbox replay 或授权恢复处理原 Job
- **THEN** 复用原冻结快照与身份，实时复核授权，不提供普通 CRUD 覆盖快照

### Requirement: Job 入口身份与外部业务执行主体必须区分
Job MUST 固定 `internal_user_id` 与适用的入口 `external_identity_id` 引用；该入口引用不等于 ONES 执行主体，Job 不另行冻结 ONES User ID 或 default Team ID。每次 ONES MCP 调用 MUST 先验证当前 RUNNING Job、Principal、冻结工具与当前应用权限，再按 Job 内部请求人唯一解析当前 `enabled` ONES 身份、有效的当前 default Team 与 `ACTIVE` 个人 Credential；缺失、多义、停用或 Team 无效时失败关闭。身份或默认 Team 变化不得改写 Job 的入口来源事实。

#### Scenario: 用户在排队期间切换 Team
- **WHEN** Job 已入队且用户随后更改 default Team
- **THEN** 后续 ONES MCP 调用使用调用时有效的当前 default Team，并复核当前授权，不虚构或回填 Job Team 快照

#### Scenario: 用户轮换同一主体的 Token
- **WHEN** 当前 ONES 身份和 default Team 有效且个人 Credential 已合法更新
- **THEN** 调用解析当前 ACTIVE Credential，不修改 Job 入口身份和 Publication

#### Scenario: 已准备写操作后切换默认 Team
- **WHEN** ONES 写工具已创建冻结执行身份与 Team 的 External Action Intent，随后用户切换 default Team
- **THEN** Worker 保持意图中的执行身份与 Team，要求原身份仍启用且原 Team 仍在当前 Team 集合中，并执行对应操作的身份版本、权限及前置条件检查
- **AND** 不把意图改为新的 default Team；原身份失效或原 Team 被移除时拒绝执行

### Requirement: 运行调试与证据查询必须受当前授权
系统 SHALL 提供受登录态保护的调试 Job 创建和 Job/Step/Tool Call 查询。创建 MUST 使用当前用户，校验 `agent.debug.execute`、业务应用角色、已发布应用及当前授权候选内的调试范围选择；不得接受任意 user、Agent、Resource Revision、Connector 或自定义 reply route。调试接口的 `execution_scope_id` SHALL 标识授权候选并写入 routing context/来源摘要，用于调试会话和幂等隔离，不建立 Job 固定业务目标或免除 Tool Call 实时鉴权。运行中心 SHALL 只列当前用户可用发布与范围，默认 Delivery 为 none，可选投递只能引用已有授权 binding。查询 MUST 限制创建者、适用应用运维用户或平台管理员，并返回步骤、安全工具摘要和独立 Delivery 事实。

#### Scenario: 幂等创建调试
- **WHEN** 同一用户在同一发布和范围下重复提交同一幂等键
- **THEN** 返回同一 job_id，不重复创建 Session、Job 或 Outbox

#### Scenario: 调试越权
- **WHEN** 创建请求缺少任一权限，或查询者不在 Job 可见范围
- **THEN** 安全拒绝且不创建执行副作用或泄漏目标业务证据

#### Scenario: 失败后查询工具调用
- **WHEN** Runtime 超时、失败、轮次耗尽或 Job 等待重试
- **THEN** steps/tool-calls 仍返回已经持久化的真实调用安全摘要，不把失败轨迹丢弃或复制为新调用

### Requirement: 运行中心 Job 查询必须在持久层过滤和分页
Job 列表 SHALL 在数据库查询中应用当前管理范围、所有请求过滤条件、稳定 `(created_at,id)` keyset cursor 和 `limit + 1`，不得先截断固定窗口再于应用进程过滤。相同窗口、过滤条件和 cursor MUST 返回无遗漏、无重复的稳定页面。

#### Scenario: 匹配记录位于未过滤窗口之后
- **WHEN** 时间窗中前 500 条记录不匹配而更早记录匹配指定用户、状态或应用条件
- **THEN** 查询仍返回匹配记录，不因预取上限漏数

#### Scenario: 受限管理员翻页
- **WHEN** 非平台管理员按其 owner 或业务数据范围查询并连续使用 next cursor
- **THEN** 每页只包含授权且符合过滤条件的 Job，页面之间没有重复或越权记录

**可靠调度与恢复**

### Requirement: 消息总线只传递内部身份并保留事务边界
API MUST 只在创建事务写 Job Dispatch Outbox，不直接发布 RabbitMQ。独立 Dispatcher SHALL 在 publisher confirm 后记录发布状态，数据库 claim/lease 支持多副本及至少一次发布。Job 消息只包含 event/job/correlation 等内部标识；Webhook dispatch 只包含 event/correlation，附件任务只包含附件与追踪标识。外部正文、凭据、临时 route、应用快照与文件字节不得进入队列。不同入口 dispatch、Job Outbox、Delivery Outbox 与 Runtime ledger MUST 分别保留其事务所有权。

#### Scenario: 事务回滚
- **WHEN** Job 创建事务回滚
- **THEN** Job 和 dispatch event 均不可见，未发布消息

#### Scenario: 发布后进程退出
- **WHEN** Broker 已接收而 Dispatcher 尚未保存 published 状态
- **THEN** event 可再次发布，消费者依据持久化幂等身份避免重复业务执行

#### Scenario: Broker 暂时不可用
- **WHEN** Dispatcher 发布失败
- **THEN** 已提交 Outbox 保持可恢复并有限退避，不丢失 Job

### Requirement: 重试调度必须由数据库事实驱动
可重试执行失败 SHALL 原子保存 `RETRY_WAIT`、retry metadata、`next_retry_at` 与 retry dispatch 事实；Dispatcher 使用 durable 版本化延迟队列和消息 expiration，经 dead-letter 回主队列。重试不得改变 Job ID、原请求人、Publication、入口 routing context、冻结模型来源或 reply route；实际工具目标、Provider 身份与当前凭据仍按各自调用合同复核和解析。次数耗尽或确定性权限、参数、配置、只读策略拒绝 MUST 进入终态失败/dead-letter，不重新执行。Broker requeue 不得自行增加数据库业务 retry count。

#### Scenario: 重试到期
- **WHEN** retry 消息从延迟队列回到主队列
- **THEN** Worker 以数据库 RETRY_WAIT 与 next_retry_at 决定是否 claim，同一 Job 不产生并发执行

#### Scenario: 重试耗尽
- **WHEN** 瞬时错误达到 Job 重试上限
- **THEN** Job 为 FAILED，持久化根因与 retry_exhausted，最多创建一次安全失败 Delivery

#### Scenario: 业务重试已提交
- **WHEN** Worker 保存重试事实并正常返回 consumer
- **THEN** consumer 确认原消息，不再基于 Broker delivery 增加重试

### Requirement: Agent Job consumer 必须隔离 poison message
Agent Job RabbitMQ consumer SHALL 在调用 Worker handler 前校验 UTF-8、JSON object 和必需的非空消息标识。Malformed envelope MUST 在不调用 Worker 的情况下进入 durable dead/quarantine queue；日志与指标只能记录有界错误分类和消息元数据，不得记录原始业务正文。

#### Scenario: 消息不是合法 JSON envelope
- **WHEN** 主队列收到无法解码、不是 JSON object、缺少 `event_id` 或缺少 `job_id` 的消息
- **THEN** consumer 将原 delivery 可靠隔离后 ack，不调用 Worker 且不 requeue 热循环

#### Scenario: 合法消息首次发生 handler 基础设施异常
- **WHEN** envelope 合法但 handler 抛出未被 Worker 业务状态机处理的异常且消息不是 redelivery
- **THEN** consumer 允许一次 broker requeue，不增加数据库 Job retry count

#### Scenario: Redelivery 仍发生 handler 异常
- **WHEN** 同一合法消息以 redelivered 状态再次进入 handler且仍抛出异常
- **THEN** consumer 将消息隔离后 ack，不再 requeue

### Requirement: 运维恢复必须显式、有限且不可改写 payload
系统 SHALL 提供只读状态/指标及按 event、job 或 delivery 精确定位的 CLI replay；MUST NOT 提供任意 payload replay、无限重试或任意 payload 编辑页面。

#### Scenario: 运维重放 DEAD delivery
- **WHEN** 授权运维人员使用 CLI 指定一个 DEAD delivery ID
- **THEN** 系统校验当前状态、记录审计并创建一次有次数上限的重放

#### Scenario: 运维提交自定义消息体
- **WHEN** CLI 请求用任意 payload 替换原事件内容
- **THEN** 系统必须拒绝该请求

**Runtime 合同与凭据边界**

### Requirement: Runtime 与 Worker 必须隔离执行职责
唯一生产 Runtime SHALL 通过 `FixedMcpClaudeSdkClient`/`ClaudeSdkClient` 使用 Python Claude Agent SDK；公共编排只依赖 `AgentRuntimeClient`。Worker MUST 独占 Job claim、授权与快照校验、重试/终态、结果和安全事件持久化、Delivery Outbox 与 RabbitMQ ack。Runtime 只执行单次 attempt，不消费 RabbitMQ、不写 Job/Delivery 业务状态。SDK/CLI 和模型明文凭据只存在所需 Runtime 边界，Worker 镜像不得包含 SDK/CLI；测试 stub 必须显式注入。

#### Scenario: Runtime 成功但本地提交失败
- **WHEN** Runtime 已 completed，而 Worker 的 Job/结果/Delivery 事务回滚
- **THEN** Worker 不错误 ack，并以相同 invocation/digest 恢复既有终态，不启动第二次模型执行

#### Scenario: Runtime 内部模块组装
- **WHEN** 系统装配请求边界、SDK、事件规范化、工具策略、文件桥与 Sandbox
- **THEN** 使用静态代码端口，不注册任意 Runtime/MCP URL、动态插件或 Worker 进程内 SDK

#### Scenario: 默认部署
- **WHEN** 当前 Compose 装配 Agent 执行链
- **THEN** Worker 通过同一 PostgreSQL 的 Job 和真实 RabbitMQ 调用固定 Python Runtime，不提供 TypeScript 或跨实现 fallback

### Requirement: Python Runtime必须实现版本化执行协议
当前 Runtime SHALL 为独立 `python-v1` 服务，新执行使用 protocol `1.5`；Worker 与 Runtime 同时接受代码已实现的 `1.4`、`1.5`，不得协商或投影 `1.0` 至 `1.3`。请求 MUST 固定 invocation、attempt、request digest、Job/Publication/model revision 与 hash、执行限制、MCP bindings、correlation 和 schema v5 文件上下文。协议 schema、limits、errors 与 fixtures MUST 位于仓库级 `contracts/agent-runtime/`，Runtime URL 只能来自平台静态装配。

#### Scenario: 新执行使用 1.5
- **WHEN** Worker 构造当前默认 invocation
- **THEN** 请求、Runtime 健康声明和工具观测以 1.5 为当前版本，并校验 v5 Manifest

#### Scenario: 已固定 1.4 执行
- **WHEN** Job 合法冻结 protocol 1.4
- **THEN** 继续使用其已支持合同，不伪造 1.5 完整审计或改写 Job 请求摘要

#### Scenario: 旧或非法合同
- **WHEN** 请求包含未知 Runtime、1.0 至 1.3、未知字段、超限内容、错误 digest 或非 v5 Manifest
- **THEN** Runtime/Worker 在模型和 MCP 调用前以稳定协议错误拒绝

#### Scenario: 流式事件
- **WHEN** 合法调用返回事件流
- **THEN** accepted 后的事件 sequence 连续且有界，最终只有一个 completed 或 failed 终态
- **AND** Worker 校验事件行数、字节、身份与唯一终态，拒绝超限或缺失终态

### Requirement: Runtime执行必须支持幂等终态恢复
Runtime MUST 以 `invocation_id + request_digest` 标识一次逻辑执行，并 SHALL 保存有界的安全终态与独立完整审计块以支持 Worker 断线或本地事务失败后的恢复。相同 invocation 与不同 digest 的请求 MUST 被拒绝，恢复不得启动第二次模型执行。

#### Scenario: Runtime完成后Worker提交失败
- **WHEN** Runtime 已产生 completed 终态但 Worker 的本地 Job 事务回滚
- **THEN** Worker 使用相同 invocation/digest 获取既有终态并重新提交本地事务
- **AND** Runtime 不再次调用模型

#### Scenario: 重复请求摘要冲突
- **WHEN** 相同 invocation ID 携带不同 request digest 到达 Runtime
- **THEN** Runtime 返回不可重试的 digest conflict 且不复用或覆盖旧终态

#### Scenario: Runtime在模型执行中重启
- **WHEN** 新 Runtime 进程收到相同 invocation/digest，且持久化 claim 表明旧进程已开始该 invocation 但尚未保存终态
- **THEN** Runtime 保存并返回 `runtime_orphaned_invocation` 不可自动重试终态，且不得再次调用模型
- **AND** 该失败只能由操作者创建新的 Job/invocation 显式重试，不得在原 Job attempt 内自动重放

### Requirement: Runtime取消与超时必须产生确定终态
Worker SHALL 能通过版本化协议取消运行中的 attempt；Runtime MUST 将取消、墙钟超时、最大轮次和最大 Tool Call 映射为稳定错误码和 retry class，并最终只产生一个终态。

#### Scenario: Worker取消运行中attempt
- **WHEN** Job 被取消、Worker shutdown 或 attempt 超过固定墙钟时间
- **THEN** Worker 向原 Runtime 发送取消请求
- **AND** Runtime 中止 SDK 会话并返回或保存一个规范取消/超时终态

#### Scenario: 取消与完成并发
- **WHEN** cancel 与 SDK completed 几乎同时发生
- **THEN** invocation ledger 只接受一个终态且后续读取返回同一结果

### Requirement: Runtime Grant必须绑定单次执行
Worker SHALL 为每个 attempt 签发短期 Runtime Grant，至少绑定 issuer、audience、authorized party、Job、invocation、Publication/hash、request digest、JTI 和 expiry。Runtime MUST 验证全部 claims 和重放状态，不得仅依赖私有网络位置。

#### Scenario: 有效Grant启动执行
- **WHEN** Grant 的 audience、Job、invocation、digest 和有效期与请求完全一致
- **THEN** Runtime 允许该 invocation 进入执行

#### Scenario: Grant被重放或篡改
- **WHEN** JTI 已被不同摘要使用、Grant 已过期或任一绑定不一致
- **THEN** Runtime 在读取 Secret、调用模型或连接 MCP 前拒绝请求

### Requirement: Runtime Grant与Principal JWT必须完全隔离
Worker→Runtime 的 Runtime Grant SHALL 继续只绑定执行、取消和终态恢复；Principal JWT SHALL 只表达平台用户对指定业务 MCP 的短期权限。两套私钥、公钥、Token、claims 和用途 MUST NOT 复用。

#### Scenario: Worker调用Runtime
- **WHEN** Worker 创建或取消一次 Runtime invocation
- **THEN** Runtime 校验绑定 Job、Publication、invocation 和 request digest 的 Runtime Grant

#### Scenario: Runtime调用ones-mcp
- **WHEN** Runtime 调用 ONES 查询
- **THEN** `Authorization` 只包含 `aud=ones-mcp` 的 Principal JWT，不包含 Runtime Grant

#### Scenario: Principal JWT缺失
- **WHEN** Job 包含 `ones-mcp` Tool 但 Worker 未提供 Principal JWT
- **THEN** Runtime 在连接 MCP 前失败关闭，且不回退到 `X-App-User-Id` 或模型参数冒充身份

### Requirement: Runtime必须使用固定模型连接和隔离凭据
Runtime MUST 从 Job 固定 Agent Publication 的模型连接 revision/config hash 解析 Base URL、模型映射、subagent model、effort 与 active credential binding，并校验连接状态、内容 hash 和 Provider host。不同 invocation MUST 使用隔离 SDK options/env，不得由全局模型 URL/Key 覆盖冻结连接。缺失连接、hash 不符、凭据不可用、SDK/CLI 缺失 MUST 返回安全配置/完整性错误，不能回退成隐式全局连接。

#### Scenario: 排队后模型连接重新发布
- **WHEN** 管理员发布新连接或 Agent Publication
- **THEN** 旧 Job 与重试保持原 revision/config hash，新 Job 才采用新发布

#### Scenario: 凭据轮换
- **WHEN** 固定 credential binding 的 active Secret 已轮换
- **THEN** Runtime 在 attempt 开始时解析当前 active 版本，不改变模型连接或 Publication

#### Scenario: 模型配置不完整
- **WHEN** revision、hash、allowed host 或 active credential 校验失败
- **THEN** Runtime 不调用模型，并且错误只含稳定安全分类

### Requirement: Runtime 按 MCP Server 隔离业务 Principal Secret
Control Plane SHALL根据当前Job已经验证并冻结的MCP bindings，为每个鉴权模式为`business-principal-jwt`的`server_code`调用一次统一业务签发器，并以`mcp_principal_tokens[server_code]`语义向Python Runtime传递恰好一个对应JWT。业务Principal MUST通过逐Server的受限Secret Header传递，不得进入Runtime请求JSON、request digest、Runtime Grant、Job payload、Invocation/terminal ledger、事件、日志、错误、审计payload或模型上下文；File Principal MUST继续通过独立Secret槽位和Header传递。

#### Scenario: 一个 Job 同时调用 ONES 和第二业务 MCP
- **WHEN** Job冻结的Runtime bindings同时包含`ones-mcp`和另一个代码固定业务MCP
- **THEN** Control Plane分别签发两个audience不同的JWT并以两个Server code键传给Runtime
- **AND** Runtime请求正文、摘要和持久化账本中不出现任一Token或Token映射

#### Scenario: 业务 Server 缺少对应 token
- **WHEN** Runtime请求包含某个业务MCP binding但Secret Header集合缺少该Server的token
- **THEN** Runtime在调用模型或连接任何MCP前以稳定不可重试身份错误失败

#### Scenario: 出现额外或未知 token
- **WHEN** Secret Header包含未出现在当前请求bindings中的Server、未知Server、重复Server、非法Header-safe名称、超长值或CR/LF
- **THEN** Runtime在读取或持久化Invocation状态之外的业务Secret前拒绝整个请求
- **AND** 错误和审计不得回显Header或Token值

#### Scenario: File token 与业务 token 同时存在
- **WHEN** Job同时冻结业务MCP Tool和File Tool
- **THEN** Runtime分别构建`mcp_principal_tokens`和`file_principal_token`
- **AND** 任何一侧缺失时不得从另一侧fallback

#### Scenario: Secret 安全投影
- **WHEN** Runtime Secret Context被repr、记录异常、生成事件或进入诊断投影
- **THEN** 输出只表明受保护凭据存在或被隐藏，不包含Server对应JWT原文

### Requirement: Python Runtime 按冻结 binding 精确选择业务 Principal
Python Runtime SHALL只针对已通过Runtime协议验证且代码固定的业务MCP binding，从`mcp_principal_tokens`按完全相同的`server_code`取Bearer Token，并为每个SDK MCP Server创建独立Header集合。Runtime MUST拒绝缺失、空值、额外或跨Servertoken，不得尝试单一默认`principal_token`、首个token、File Principal或其它Server token；`tool-mcp`继续不携带Authorization，`file-service`继续走进程内File bridge和独立File Principal。

#### Scenario: 两个业务 MCP 并发调用
- **WHEN** 模型在同一Invocation中并发调用两个已冻结业务MCP Server的Tool
- **THEN** 每个SDK MCP连接只携带自身Server code对应的Bearer Token
- **AND** Tool事件、结果和审计继续按各自Server、Tool、call id和Job关联

#### Scenario: ONES token 被错误放入另一 Server 键
- **WHEN** 映射键是第二业务Server但JWT audience实际为`ones-mcp`
- **THEN** 第二业务MCP的固定audience验证失败且Runtime不得使用ONES连接作为fallback

#### Scenario: 模型尝试提供 token 或 Server 地址
- **WHEN** Prompt、Tool参数或模型输出包含Principal Token、Authorization、Server URL或自定义MCP配置
- **THEN** Runtime工具策略和固定MCP装配拒绝这些字段且不改变Secret Context

#### Scenario: File bridge 行为保持不变
- **WHEN** Job执行冻结的File Tool
- **THEN** Python Runtime继续使用独立File Principal、当前Job Sandbox和进程内File MCP bridge
- **AND** 业务Principal映射不进入文件传输上下文

### Requirement: Runtime必须提供无副作用健康与模型探针
Runtime SHALL 提供 health、ready、version 和受服务授权保护的模型 probe。健康检查 MUST NOT 调用模型或业务 MCP；模型 probe MUST 固定连接 revision/config hash、禁止 Tool、单轮、短超时且只返回脱敏结果。

#### Scenario: Readiness检查
- **WHEN** 编排系统调用 Runtime readiness
- **THEN** Runtime 报告协议、SDK、配置、Secret/DB 依赖的脱敏状态且不产生模型费用

#### Scenario: 模型连接Probe
- **WHEN** Python 服务提交通过 RBAC/SSRF 校验的固定模型连接 probe
- **THEN** Runtime 使用 active Secret 完成无 Tool 探测并只返回版本、脱敏 host/model、耗时和稳定错误码

### Requirement: Execution is bounded by turns and wall-clock time
系统 SHALL 使用 Job 固定的有效执行策略限制真实 Claude Agent 执行的 SDK 最大轮次、单次 attempt 墙钟时间和内部工具调用次数；有效范围为 max_turns 1–100、timeout_seconds 10–3600、max_tool_calls 0–500。所有进入 Worker 的 Job MUST 具有合法的当前 Execution Policy 快照；Worker MUST NOT 对缺失或不支持的策略使用 `AGENT_MAX_TURNS`、`AGENT_TIMEOUT_SECONDS` 或 Agent Publication 进行运行时 fallback。Runtime MUST 将工具调用次数与墙钟耗尽作为当前 attempt 的强制终止边界，而不是仅向模型返回可继续执行的普通拒绝或把本地预算耗尽误分类为瞬时传输故障。

#### Scenario: Execution exceeds configured timeout
- **WHEN** Runtime 自身的墙钟监视器确认 SDK session 超过 Job 有效 `timeout_seconds`
- **THEN** Runtime 取消当前 session，保留已有安全工具事件并返回稳定的 `runtime_timeout` 安全错误
- **AND** Worker 不为该错误安排自动重试，把 Job 转为 `TIMEOUT`

#### Scenario: Execution reaches maximum turns
- **WHEN** SDK session 达到 Job 有效 `max_turns` 且没有有效最终结果
- **THEN** 运行时按最大轮次耗尽分类结束执行
- **AND** 不把该错误仅作为普通 transport transient 立即重试

#### Scenario: Execution reaches maximum tool calls
- **WHEN** 当前 Agent attempt 的统一权限守卫已经接收 Job 有效 `max_tool_calls` 次内部工具请求，并收到下一次工具请求
- **THEN** Runtime 在该请求进入受治理工具实现 或产生文件工具副作用前以硬中断拒绝该请求
- **AND** 当前 attempt 以稳定、非瞬时的 `execution_policy_max_tool_calls_exhausted` 结束，不再执行后续模型轮次或工具请求
- **AND** Runtime 保留终止前已有的安全工具事件，执行策略证据记录 `exhausted=true`

#### Scenario: Zero tool-call budget rejects the first request
- **WHEN** Job 有效 `max_tool_calls` 为 `0` 且模型发起首次内部工具请求
- **THEN** Runtime 在调用受治理工具实现 或文件工具副作用路径前以 `execution_policy_max_tool_calls_exhausted` 终止当前 attempt

#### Scenario: Job缺少执行策略
- **WHEN** Job 没有 Execution Policy 快照、schema version 不受支持或有效字段不完整
- **THEN** Worker 在调用 Claude SDK 前以不可重试的完整性错误停止
- **AND** 不调用模型或任何内部工具

### Requirement: SDK failures are classified for retry policy
系统 SHALL 根据结构化语义分类 Claude Agent SDK/CLI 故障：网络、429/5xx、transport、CLI JSON decode 和可确认的瞬时 provider 故障映射为可重试；缺少凭据、CLI 不存在、明确无效模型配置、工具策略拒绝和 Runtime 自身 Job 墙钟预算耗尽映射为不可重试；矛盾的 error result MUST 使用独立错误码并只允许受最大次数约束的有限重试。错误分类 MUST 使用稳定错误码和协议 retry class，不得依赖用户可见消息文本。

#### Scenario: Transient process error triggers retry
- **WHEN** SDK 返回网络、rate limit、overloaded、transport 或 CLI JSON decode 瞬时错误
- **THEN** runtime 抛出带稳定错误码的 `RetryableExecutionError`，由 Job retry service 延迟调度

#### Scenario: Local runtime timeout does not retry
- **WHEN** Runtime 自身 Job 墙钟监视器达到冻结的 `timeout_seconds`
- **THEN** Runtime 使用 `runtime_timeout` 和非瞬时 retry class 返回失败，Worker 不创建 retry dispatch
- **AND** Job 进入 `TIMEOUT`，已有安全工具事件和执行证据继续持久化

#### Scenario: SDK reports contradictory success error
- **WHEN** SDK/CLI 返回 `is_error=true`，但 errors 为空且 subtype 为 `success`，或抛出等价的 `Claude Code returned an error result: success`
- **THEN** runtime 不把该结果作为最终答案，映射为 `claude_inconsistent_result`，生成用户可理解的安全消息，并在最大重试次数内有限重试

#### Scenario: Contradictory result exhausts retries
- **WHEN** 同一 Job 持续收到 `claude_inconsistent_result` 并达到最大重试次数
- **THEN** Job 进入终态失败，不再调用模型，并通过原 reply route 发送一次安全失败通知

#### Scenario: Configuration failure does not retry
- **WHEN** runtime 确认缺少凭据、CLI runtime 不存在或模型配置明确无效
- **THEN** runtime 返回不可重试配置错误，不进入延迟 retry queue

#### Scenario: Policy violation does not retry as transport error
- **WHEN** 工具调用因为 SQL policy、只读边界、权限拒绝或 `max_tool_calls` 耗尽而停止
- **THEN** runtime 将安全拒绝结果返回模型或终止本次执行，不将其误分类为 SDK transport retry

**工具能力与模型上下文**

### Requirement: Runtime 工具能力必须来自冻结集合与精确派生
Runtime MUST 只注册 Job 冻结 MCP 工具和代码允许的派生工具；只读资源走固定 `tool-mcp`，业务操作走对应固定业务 MCP，文件工具走 `file-service` bridge。业务 mutation 只准备受治理 Action Intent，须通过本规范逐次确认链才能产生 Provider 副作用。文件 Job 可使用受限 Read/Glob/Grep/Write/Edit；只冻结 ONES 集合查询而无文件写能力的 Job 仅派生 Read/Glob/Grep 读取结果文件。`select_sandbox_output` 依赖冻结提交能力，`scan_log_evidence` 依赖冻结物化能力与 Sandbox。Bash、Shell、NotebookEdit、WebFetch、WebSearch、任意部署、数据库写入和沙盒外操作 MUST 被拒绝。

#### Scenario: 只读查询结果文件
- **WHEN** Job 只有 ONES 集合查询工具
- **THEN** 可读取本 Job 临时只读 Markdown 结果，不获得 Write/Edit、文件提交或跨 Job 访问

#### Scenario: 派生日志扫描
- **WHEN** Job 冻结 file_prepare_materialization 且有效 Sandbox 已存在
- **THEN** 可注册 scan_log_evidence，它只扫描已物化 LOG，不新增文件来源、对象存储或网络权限

#### Scenario: 未冻结工具或任意 Server
- **WHEN** 模型尝试通过名称、URL、Header、Token 或输出数据注册另一工具
- **THEN** 精确工具策略和服务端复核在副作用前拒绝

### Requirement: Runtime必须隔离SDK配置和工具权限
每次SDK调用 MUST 使用独立options、env和Job Sandbox，显式设置`settingSources: []`，仅注册请求固定的资源MCP、业务MCP和/或File MCP Server，并以精确的SDK `tools`可用集合、空`allowedTools`/`allowed_tools`、SDK `default` permission mode和deny-by-default `canUseTool`限制Tool。不得使用会在空自动批准集合下先行拒绝并跳过回调的`dontAsk`。Bash、NotebookEdit、WebFetch、WebSearch、Shell和开放文件修改能力 MUST 被禁用；文件Job的`Read`、`Glob`、`Grep`、`Write`与`Edit`必须经过当前沙盒路径守卫。

#### Scenario: 模型调用允许的只读Tool
- **WHEN** Job 请求固定了合法只读 MCP Server、Tool、schema hash 和工具授权集合
- **THEN** Runtime 只允许对应 `mcp__<server>__<tool>` 调用，并由 MCP 服务再次复核 Job、当前授权和本次调用目标

#### Scenario: 模型调用允许的文件Tool
- **WHEN** Job 请求固定了合法 File MCP Tool，且 Principal JWT、schema hash 和 Job/Workspace 文件授权匹配
- **THEN** Runtime只连接部署固定File Service并把本地文件工具限制到当前Job Sandbox

#### Scenario: 模型尝试调用未授权工具
- **WHEN** 模型请求Bash、Web工具、沙盒外文件操作或不在精确集合中的MCP Tool
- **THEN** Runtime拒绝调用且不向任何Tool backend发出请求

### Requirement: 每次Runtime调用必须形成不可变工具契约观测
系统 SHALL 对每个 Runtime protocol 1.4 或 1.5 invocation 在首次模型请求前形成并保存一个与 `job_id`、`invocation_id`、`request_digest` 和既有 Job MCP Tool Snapshot hash 绑定的 `tool_contract_observed` 安全事件。该事件 MUST 分别记录 Job frozen、File MCP live、Runtime effective 和 Prompt declaration 四层事实及其 hash、来源和确定性对账状态；Runtime effective 还 MUST 记录传给 SDK 的精确可调用名称。事件不得保存完整 Tool Schema、Tool 描述、完整 Prompt、业务正文、URL、Header、Token、凭据或原始 MCP/SDK payload。

相同 invocation 与 request digest 的重放 MUST 复用同一 observation hash；相同 invocation 携带不同 digest 或不同观测内容 MUST 失败关闭。Worker SHALL 以既有 Runtime event 唯一约束幂等保存该事实，不得用后续 invocation 覆盖或改写既有观测。

#### Scenario: 模型调用前完成四层观测
- **WHEN** Runtime准备执行一个包含File Service冻结工具的protocol 1.4 或 1.5 invocation
- **THEN** Runtime在首次模型请求前完成File MCP live、Runtime effective和Prompt declaration对账并发出`tool_contract_observed`
- **AND** Worker保存的事件能够关联到该Job既有MCP Tool Snapshot而不复制或改写Snapshot

#### Scenario: Runtime恢复相同invocation
- **WHEN** Worker以相同`invocation_id + request_digest`恢复已经保存观测或终态的调用
- **THEN** Runtime和Worker复用相同observation hash且不产生第二套工具事实
- **AND** 不再次询问模型来判断工具是否可用

#### Scenario: 安全事件不泄漏工具或业务载荷
- **WHEN** 操作者、审计测试或运行记录API读取工具契约观测
- **THEN** 只可见有界标识、来源、平台、版本、hash和稳定状态
- **AND** 不存在完整Schema、描述、Prompt正文、MCP原始响应、Principal JWT或业务文件内容

### Requirement: File MCP必须在模型调用前校验实时工具声明
只要Job冻结了`file-service`工具，Python Runtime File bridge MUST 使用当前Job File Principal和部署固定地址建立受控MCP Session，在`initialize`之后、构造Runtime effective工具集之前完整调用一次分页`tools/list`。远端输入Schema hash MUST使用与Job Snapshot相同的规范化算法计算。冻结工具在live声明中缺失、同名输入Schema hash不一致、重复或非法Tool声明、分页不完整或需要观测但无法取得结果时，Runtime MUST 先保存安全漂移观测，再以稳定错误在模型调用前失败关闭。

File MCP live中额外但未冻结的工具 MUST 标记为`EXTRA_REMOTE_IGNORED`且不得进入bridge或SDK；`allowed_tools`、Prompt文字和本地manifest均不得替代该次live观测来证明远端工具存在。

#### Scenario: 冻结提交工具未被远端声明
- **WHEN** Job Snapshot包含`file_create_commit_intent`但同一MCP Session的完整`tools/list`不包含它
- **THEN** observation将该工具标记为`MISSING_REMOTE`并把invocation判为`DRIFT`
- **AND** Runtime不启动模型、不向SDK暴露该工具且返回稳定合同错误

#### Scenario: 同名工具Schema已经变化
- **WHEN** File MCP live声明同名工具但规范化输入Schema hash与Job Snapshot不同
- **THEN** observation将该工具标记为`SCHEMA_MISMATCH`并失败关闭
- **AND** 系统要求通过新Publication和新Job采用新合同，不在旧Job中动态替换hash

#### Scenario: 远端暴露额外工具
- **WHEN** File MCP live比Job Snapshot多声明一个工具
- **THEN** Runtime记录`EXTRA_REMOTE_IGNORED`但不把该工具加入Runtime effective或Prompt declaration
- **AND** 其存在本身不使已冻结且匹配的工具失败

#### Scenario: File MCP连接时无法完成观测
- **WHEN** Job需要File Service工具但MCP初始化、分页或Schema规范化无法安全完成
- **THEN** invocation以`DRIFT`和稳定可重试分类或合同分类失败关闭
- **AND** 不把缺失观测显示为`MATCH`

### Requirement: Runtime有效工具和Prompt声明必须来自同一注册表
Python Runtime SHALL 在File MCP校验和代码内工具注册完成后构造唯一Runtime effective registry，并由该registry同时生成SDK Tool Schema、审批边界和Prompt中的当前可调用工具声明。每项 MUST 标记为`frozen_mcp`、`runtime_derived`或`sdk_builtin`，并包含逻辑Tool名、SDK精确可调用名、输入Schema hash和授权结果。

`select_sandbox_output` MUST仅在Job冻结`file_create_commit_intent`且文件格式策略允许时注册为`runtime_derived`；它不需要出现在Job MCP Snapshot或File MCP `tools/list`中。未获冻结或策略授权的工具进入Runtime effective时 MUST标记`UNAUTHORIZED_EFFECTIVE`并失败关闭；Prompt当前可调用声明包含Runtime effective中不存在的工具时 MUST标记`PROMPT_OVERCLAIM`并在模型调用前失败关闭。静态Prompt不得人工维护第二份当前可调用工具名单。

File MCP输入Schema MUST使用当前固定Claude Agent SDK及其bundled CLI能够完整注册的受支持子集。无法由该子集表达的跨字段业务不变量 MUST由File Service在创建Intent或其它副作用前重新校验，不得为了兼容CLI而取消业务约束。发布合同测试 MUST启动真实bundled CLI，使用生产File Tool名称、描述和输入Schema，并证明`file_create_commit_intent`同时出现在CLI初始化工具清单和实际ToolUse路由中；仅直接调用进程内MCP Session不构成该事实的验收证据。

#### Scenario: Runtime派生输出选择器
- **WHEN** Job冻结且live校验通过`file_create_commit_intent`并允许TXT或Markdown输出
- **THEN** Runtime effective包含来源为`runtime_derived`的`select_sandbox_output`及其SDK精确名称
- **AND** 该工具不因未出现在File MCP live或Job Snapshot而被判为缺失

#### Scenario: Prompt仍声明旧提交工具
- **WHEN** Runtime effective不包含`file_create_commit_intent`但Prompt contract把它声明为当前可调用工具
- **THEN** invocation记录`PROMPT_OVERCLAIM`并以`DRIFT`失败关闭
- **AND** 模型不会收到互相冲突的Prompt和函数Schema

#### Scenario: allowed_tools引用不存在的工具
- **WHEN** SDK审批配置引用一个未进入Runtime effective的工具
- **THEN** 系统不得据此把该工具判为存在或`MATCH`
- **AND** 未授权或陈旧审批引用按安全合同错误处理并记录来源

#### Scenario: CLI无法注册提交工具Schema
- **WHEN** File MCP live与Job Snapshot匹配，但当前SDK或bundled CLI会因提交工具输入Schema而把`file_create_commit_intent`从初始化工具清单移除
- **THEN** 真实CLI发布合同测试失败且对应Runtime镜像不得晋级
- **AND** 系统不得用`allowed_tools`、Prompt声明或直接内存Session调用把该工具判为CLI可调用

### Requirement: 运行记录必须展示确定的工具契约对账
授权用户读取运行记录时，列表 SHALL 展示Job工具契约汇总状态`MATCH`、`DRIFT`或`NOT_OBSERVED`，详情 SHALL 按invocation展示组件构建身份、Job frozen、File MCP live、Runtime effective、Prompt模板版本与contract hash以及逐工具状态矩阵。状态 MUST由保存的Snapshot和Runtime事件确定计算，不得采用模型文字回答、当前MCP状态回填历史或客户端自行推断。

Job汇总状态 MUST按`DRIFT`高于`MATCH`高于`NOT_OBSERVED`计算：任一invocation曾漂移则保持`DRIFT`；否则存在且全部当前受支持协议观测匹配时为`MATCH`；尚无工具契约观测或历史1.3 Job为`NOT_OBSERVED`。详情必须明确区分远端MCP工具和Runtime派生工具。

#### Scenario: 重试后匹配不掩盖先前漂移
- **WHEN** 同一Job的第一次invocation为`DRIFT`而显式重试的新invocation为`MATCH`
- **THEN** 列表汇总仍显示`DRIFT`
- **AND** 详情分别展示两次不可变观测及其原因

#### Scenario: 历史protocol 1.3 Job
- **WHEN** 用户查看升级前没有`tool_contract_observed`事件的终态Job
- **THEN** 列表和详情显示`NOT_OBSERVED`并说明该状态不等于健康
- **AND** 系统不使用当前File MCP live结果伪造历史观测

#### Scenario: 未授权用户读取运行记录
- **WHEN** 调用方无权读取目标Job、Application或Session运行记录
- **THEN** API继续按既有资源授权拒绝
- **AND** 不泄漏Tool名称、构建身份、hash或漂移原因

### Requirement: Worker与Runtime提示词版本必须使用共享事实源
Worker 默认执行上下文与 Python Runtime 工具契约观测 MUST 从共享模块引用同一 Prompt template version。Worker MUST 继续严格验证观测 hash、Job snapshot hash、提示词版本与组件构建身份，不得因版本升级移除校验或静默改写请求版本。

#### Scenario: 默认上下文进入Runtime
- **WHEN** 同一版本组件以默认上下文构造请求并生成真实工具契约观测
- **THEN** 观测通过 Worker 事件校验且可继续接收终态

#### Scenario: 混用不同版本组件
- **WHEN** 观测提示词版本与请求不一致
- **THEN** Worker 以 runtime_protocol_error 失败关闭，不持久化被拒绝事件为已验证事实

### Requirement: Runtime协议失败必须展示安全字段差异
Runtime 协议失败 MUST 经既有错误步骤及执行摘要返回代码固定的中文拒绝原因。工具契约不匹配 MUST 包含事件序号、字段和安全期望/实际值；只允许固定格式 Prompt 版本及 SHA-256，其他值只显示缺失、不匹配或无效格式，不包含被拒绝事件正文、Prompt、凭据或堆栈。运行记录 MUST 显示已有 failure_summary 与 failure_code，初始化失败不得伪造 Tool Call。

#### Scenario: 提示词版本不匹配
- **WHEN** Worker 请求 v6、Runtime 观测 v5
- **THEN** 失败步骤及运行记录显示 prompt.template_version、两个版本和 runtime_protocol_error

#### Scenario: 字段包含非规范正文
- **WHEN** Runtime 版本字段携带任意业务正文、敏感链接或认证材料
- **THEN** 只显示无效格式或固定校验原因，不回显该值

### Requirement: 不可用业务MCP Tool使用独立安全提示通道
运行时 MUST 将受治理业务 MCP Tool 的调用资格与模型解释事实分离：不满足当前发送者 Provider 身份或 Credential 前置条件的 Tool MUST 保持未注册、未批准，同时 MAY 仅在该 Tool 已属于精确 Agent/Application 发布交集时，以固定白名单文案向模型说明当前 Job 的不可用状态。提示 MUST NOT 复用原始异常，不得包含用户、Team、Credential、Principal 或认证材料，也不得被模型视为可调用 Tool。

#### Scenario: 当前发送者缺少ONES前置条件
- **WHEN** 当前应用已发布 ONES Tool，但 Job 没有可用外部主体或当前 Credential 复核失败
- **THEN** 系统提示模型说明“该能力对当前发送者暂不可用”并给出安全的本人重新验证提示
- **AND** 不得声称平台全局未注册 ONES Tool

#### Scenario: 安全提示不扩大Tool权限
- **WHEN** 系统提示中存在某个 Tool 的 `unavailable` 事实
- **THEN** 该 Tool 不进入 MCP Server、`allowed_tools` 或 Tool 自动批准集合
- **AND** 模型不得声称已经调用或验证其连通性

### Requirement: 模型可见会话与上下文清单必须去除确定性重复
Runtime SHALL 从 Job 固定配置构造平台安全规则、业务指令、已发布 Skills、当前问题、检索元数据与有界历史。当前输入 MUST 在构造滚动摘要和最近历史窗口前按 `input_message_id` 排除，且只通过 User Prompt 进入一次；不同消息 ID 的同文历史仍保留。摘要与最近消息只渲染一份模型可见正文，retrieved_context 不复制该正文，审计每个来源只存一份 canonical content。Worker 与 Runtime MUST 从共享事实源使用当前 `agent-system-prompt-v7` 和对应 contract hash，历史观测不得回写。

#### Scenario: 输入已存在 Session
- **WHEN** 当前输入消息已持久化且出现在最近历史候选中
- **THEN** 按 ID 排除当前输入而不按文本误删更早真实消息，当前问题只作为 User Prompt 出现一次

#### Scenario: 上下文审计
- **WHEN** context source 是字符串、数组或对象
- **THEN** 保存完整 canonical content、字符数、估算 token 和截断事实，不另存可确定生成的 rendered_text

#### Scenario: 业务内容带指令样式
- **WHEN** Tool、OCR、日志或业务正文要求忽略权限、修改系统规则或注册工具
- **THEN** 内容保持不可信数据，不能改变平台安全规则、工具集合或凭据边界

### Requirement: 诊断上下文必须包含目标 schema 目录
系统 SHALL 通过 `tool-mcp` 的 `get_schema_directory` Tool 为明确目标提供当前可访问的 schema 目录，或明确说明目标无法唯一解析。目录 MUST 来自当前唯一 Published Database Resource Revision，只包含按当前权限和资源范围过滤后的表、列和非密钥元数据。
#### Scenario: 单一目标问题获取 schema
- **WHEN** Agent 已明确 environment/base/workshop 并调用 `get_schema_directory`
- **THEN** Tool Call 返回该目标当前可访问的 schema 目录摘要，供模型生成 SQL 前检查可用表和字段
#### Scenario: 目标不明确时不猜 schema
- **WHEN** 用户问题不能唯一确定 environment/base/workshop
- **THEN** Agent 必须先澄清或通过允许的上下文工具解析目标，不得猜测目标代码、Resource 或表名

### Requirement: 诊断运行时必须停止缺证据试错
系统 SHALL 指示真实模型在 schema 不足、表不存在、字段不存在、连续策略拒绝、空结果无法支撑结论或关键业务字段缺失时停止扩散式工具试错，并输出“不具备诊断证据”的报告。最终报告 MUST 明确列出已经验证的限制条件和安全下一步。

#### Scenario: schema 中没有订单表或订单字段
- **WHEN** schema 目录不包含可用于按订单号查询的表或字段
- **THEN** Agent 不得继续猜测 `mo`、`order`、`production_order` 等未列出的表名，并必须报告当前数据结构不足以诊断该订单

#### Scenario: 工具连续返回结构化拒绝
- **WHEN** 数据库工具连续返回表不存在、字段不存在、跨 workshop、非 SELECT 或 schema 不可用等结构化拒绝
- **THEN** Agent 必须停止新的相邻表名尝试，并产出证据不足报告

#### Scenario: 缺证据报告仍遵循只读诊断格式
- **WHEN** Agent 因缺少可用证据而停止
- **THEN** 最终报告包含结论、已验证证据、限制/不确定性和非变更类下一步，不建议 Agent 执行写操作或自动修复

### Requirement: Final reports are evidence based
The system SHALL require Agent final answers to include a conclusion, evidence summary, uncertainty or limitations when applicable, and suggested safe next actions. Real runtime prompts SHALL instruct the model to follow this report structure using tool evidence gathered during the job. 当报告使用日志证据扫描器时，Agent MUST区分精确扫描覆盖事实、通用规则选择的启发式候选和模型诊断推断；用户行为不是固定报告章节，只有证据支持且与现场问题相关时才记录。`coverage_complete=true`只证明所选输入全部字节已扫描，不证明所有日志语义已经理解；`evidence_limit_reached=true`时报告 MUST明确说明证据包是有界选择。

#### Scenario: Agent completes order diagnosis
- **WHEN** the Agent finishes investigating a business question such as an order stuck in a status
- **THEN** the final report includes the likely cause, relevant log/database/Redis/ER/business-flow evidence, uncertainty if evidence is incomplete, and non-mutating recommendations

#### Scenario: 异构日志扫描完整但证据达到上限
- **WHEN** 日志扫描返回所有选中输入`coverage_complete=true`且`evidence_limit_reached=true`
- **THEN** 最终报告可以引用保留证据进行诊断，但必须列出扫描字节/行覆盖和省略候选数量
- **AND** 不得声称已经逐条理解全部日志或完整还原所有用户行为

#### Scenario: 日志扫描没有完整覆盖
- **WHEN** 日志扫描因取消、容量、完整性或读取错误未返回完整覆盖
- **THEN** Agent不得生成“已完成全量日志分析”的结论
- **AND** 最终回复必须说明稳定失败分类、已验证范围和安全下一步

#### Scenario: 日志证据包含指令样式内容
- **WHEN** 临时证据包中的原文包含Tool名、系统指令样式文本、Markdown或HTML
- **THEN** Runtime提示要求模型把它仅作为不可信诊断数据引用
- **AND** 该内容不得覆盖系统规则、扩大Tool权限或替代当前用户请求

### Requirement: 完整明细输出必须包含平台级模型约束
系统 SHALL 在统一 Runtime 系统 Prompt 中注入明细输出规则，不依赖业务 Skill。规则 MUST 要求模型在用户请求记录清单或完整明细时列出授权且已获取的符合条件记录，保留所需标识和完整标题，不能用省略号、其余略或样例替代；用户明确要求汇总、前 N 条或样例时遵守其范围。此 Requirement 约束 Prompt 的内容与作用范围，不将模型自检等同于程序级完整性保证。

#### Scenario: 无业务 Skill 的明细请求
- **WHEN** Runtime 为没有启用业务 Skill 的 Job 构造系统 Prompt
- **THEN** Prompt 仍包含完整列出、禁止人为省略、数量与稳定 ID 自检以及部分结果说明规则

#### Scenario: 获取数量与筛选数量不同
- **WHEN** 工具获取 29 条，用户条件筛选后为 20 条
- **THEN** Prompt 要求模型核对并列出筛选后的 20 条唯一记录，区分获取数和展示数，不把“工具无截断”当成“回复已完整”的证明

#### Scenario: 上游或输出限制导致不完整
- **WHEN** 结果有截断、工具返回只读结果文件尚未完整读取，或预算不足以完整回答
- **THEN** Prompt 要求在既有授权和预算内继续读取；仍无法完成时报告已获取/已展示数量及原因，不称为完整明细，不补造记录

#### Scenario: 长标题和原文中的省略号
- **WHEN** 记录标题很长或本身含省略号
- **THEN** Prompt 要求优先用编号列表保留完整原文；不新增基于省略号的正则拒绝或删改，支持分片的渠道继续使用既有长报告投递机制

### Requirement: 明细输出约束必须可识别验证边界
系统 SHALL 对新的输出约束使用新 Prompt template version，并用合成数据验证无 Skill/跨工具注入及明细文本经过现有分片时无损。测试结果 MUST 区分 Prompt/分片回归与真实 Provider/模型验收，MUST NOT 回写历史 Job 的 Prompt 观测版本。

#### Scenario: 新版本 Prompt
- **WHEN** 新构建准备新 invocation
- **THEN** 当前 Prompt template version 为 v7，Worker 请求和 Runtime 观测保持一致；MCP Schema 和 Runtime 协议保持原值

#### Scenario: 长清单投递回归
- **WHEN** 包含 20 条唯一编号和长标题的合成清单超过单片长度
- **THEN** 分片按序重组后与原清单完全一致，不遗漏、替换或重复任何记录；该测试不冒充真实模型已遵循规则的证据

### Requirement: 日志证据扫描器必须作为可审计Runtime派生Tool进入合同
Python Runtime SHALL以代码固定Tool名、描述、严格Input Schema和schema hash注册`scan_log_evidence`，并在有效Tool合同中把它标记为`runtime_derived`、记录对`file_prepare_materialization`的依赖和Runtime build identity。它不得作为新的远端File Service Manifest Tool、Business Application可选Tool、通用`tool-mcp`资源Tool或模型提供的动态Tool；现有Job冻结的只读物化权限只是派生条件，不得被解释为新的文件正文授权。

#### Scenario: Runtime观察到匹配的派生Tool合同
- **WHEN** 当前Job满足扫描器派生条件且Runtime本地schema与代码固定hash一致
- **THEN** Tool合同证据列出`scan_log_evidence`、`runtime_derived`来源、依赖项、schema hash和Runtime build identity
- **AND** 模型可调用名称稳定为`mcp__file_service__scan_log_evidence`

#### Scenario: 扫描器schema发生漂移
- **WHEN** Runtime装配、权限回调或合同观察到的`scan_log_evidence`schema hash与代码固定值不一致
- **THEN** Runtime在模型调用该工具前以不可重试Tool合同完整性错误失败关闭
- **AND** 不回退到`Grep`循环、旧schema或远端同名Tool

#### Scenario: 远端File Service报告同名Tool
- **WHEN** 部署固定File Service的`tools/list`意外返回`scan_log_evidence`
- **THEN** Runtime将其视为远端合同漂移并失败关闭
- **AND** 不把远端Tool替换或覆盖本地派生实现

### Requirement: 日志扫描服从Job执行预算与合作式取消
每次`scan_log_evidence`请求 SHALL按一次内部Tool调用计入当前attempt的Job固定`max_tool_calls`，并 MUST在进入扫描副作用前经过统一Tool预算、Input Schema和Sandbox授权。扫描循环和证据写入 MUST定期检查当前Runtime取消信号与Job剩余墙钟预算；Tool预算耗尽不得开始扫描，本地墙钟耗尽仍按稳定`runtime_timeout`终结且不自动重试整个Job。

#### Scenario: 扫描请求超过Tool调用预算
- **WHEN** 模型发起日志扫描时当前attempt已经执行Job允许的全部Tool调用
- **THEN** Runtime在读取日志或预留证据包前硬终止当前attempt
- **AND** 返回既有`execution_policy_max_tool_calls_exhausted`语义且不调用扫描器

#### Scenario: 扫描期间达到Job墙钟上限
- **WHEN** 扫描循环尚未完成而当前attempt达到冻结`timeout_seconds`
- **THEN** Runtime合作式取消扫描、保留此前安全Tool事件并清理未完成证据包
- **AND** Worker将稳定`runtime_timeout`映射为不自动重试的Job `TIMEOUT`

#### Scenario: 扫描完成后模型继续生成报告
- **WHEN** 扫描器在剩余墙钟预算内成功返回证据包元数据
- **THEN** 模型只使用剩余轮次、Tool调用和墙钟预算读取证据并生成报告
- **AND** 扫描成功不重置或扩大任一执行预算

### Requirement: 日志扫描失败必须保留安全可行动的错误事实
Runtime SHALL 将已知日志扫描错误码、固定中文提示及重试分类传递至既有工具事件和控制面安全摘要；参数/路径等确定性错误 MUST 为 `NEVER`，不得被通用瞬时失败覆盖。普通事件 MUST NOT 因此保存实际路径、关键词、日志正文或动态异常文本。未知错误码 MUST 保持安全通用回退；其他工具和 Job 终态语义保持不变。

#### Scenario: 输入与路径错误可定位
- **WHEN** File bridge 返回 `log_evidence_input_invalid` 或 `log_evidence_path_invalid`
- **THEN** SDK 事件至控制面工具失败摘要保留对应码和固定中文纠正提示，retry class 为 `NEVER`，不再只显示 `runtime_tool_failed`

#### Scenario: 伪造错误载荷不进入普通审计
- **WHEN** 扫描结果载荷带有未知错误码或伪造的动态错误文本
- **THEN** Runtime 不将其原样传播到普通工具事件，已知码只使用固定提示，未知码使用通用失败

#### Scenario: 工具失败与 Job 完成分离
- **WHEN** 扫描失败后 Agent 使用已授权的 Grep/Read 完成有界分析
- **THEN** 保留扫描工具失败事实，但不因此改写 Job 已有成功终态规则，成功状态不得被解释为扫描成功或全量语义覆盖

**执行审计与完整正文**

### Requirement: Runtime正文审计与普通安全记录必须隔离
普通 Job provenance、Runtime 事件、Tool Call、错误、日志、RabbitMQ 和列表 SHALL 只保存有界安全事实，不保存完整 Prompt、原始 SDK/Provider 正文或私有推理。专用 `agent_run_audit` 链 SHALL 原样保存 Runtime/Provider 实际暴露的完整响应、模型可见上下文与 Tool I/O，不执行应用层脱敏或长度截断；其内容只经 1.5 audit_chunk、同 invocation 恢复账本和授权详情字段接口流转。上游隐藏或删减的 reasoning 不可恢复、不得推断或伪造。Credential、认证 Header、Cookie、Principal/Grant、对象位置与平台 Secret MUST 使用独立受保护对象，系统不得主动复制到审计正文；完整业务正文不是自动脱敏数据，不能复制进普通查询/日志。

#### Scenario: SDK 响应进入审计
- **WHEN** SDK 暴露消息或 Provider body
- **THEN** 完整审计保存实际内容，普通事件只投影安全元数据，缺失的上游内容明确不可用

#### Scenario: 错误包含认证材料
- **WHEN** 错误进入普通步骤、日志、Tool Call 或渠道通知
- **THEN** 仅返回固定安全码、受限分类及脱敏摘要，不回显凭据、原始响应或堆栈

#### Scenario: 完整审计查询
- **WHEN** 用户未通过 jobs.read 与目标 Job 业务范围检查
- **THEN** 不读取或返回任何完整正文；通过授权后仍按固定字段分页

### Requirement: Agent Tool Call 必须按真实来源分类
系统 SHALL 使用 `agent_tool_call` 保存 Runtime 观察到的每次逻辑 Tool Call，并以 `tool_origin` 明确区分 `mcp`、`sdk_builtin`、`sdk_custom` 与 `unknown`。只有与当前 Job 冻结 MCP Binding 精确匹配的调用才能保存非空 `server_code` 和 `mcp_call_id`；系统 MUST NOT 将未知或 SDK 原生 Tool 默认归类为 `tool-mcp`、`ones-mcp` 或其它 MCP Server。

#### Scenario: Python Runtime 捕获未知 SDK Tool
- **WHEN** Python Runtime 从 SDK 消息中捕获到无法匹配 MCP Binding、SDK 内置目录或平台注册目录的 Tool Use
- **THEN** Runtime 以 `tool_origin=unknown`、空 `server_code` 产生有界 Tool Event，并由 Worker 保存一条 `agent_tool_call`
- **AND** 系统不得为该事件创建 `mcp_operation_audit`

#### Scenario: SDK 内置工具被 Runtime 拒绝
- **WHEN** Python Runtime 拒绝一个未获 Job 授权的 SDK 内置 Tool
- **THEN** Runtime 保存 `tool_origin=sdk_builtin`、`status=DENIED` 和稳定拒绝码，且 `server_code` 与 `mcp_call_id` 为空

#### Scenario: MCP Tool 与冻结 Binding 精确匹配
- **WHEN** Runtime Tool 名称、Server alias 与当前 Job 冻结的 MCP Tool Binding 精确匹配
- **THEN** Tool Event 使用 `tool_origin=mcp` 并保存该 Binding 的真实 `server_code`

### Requirement: 一个 SDK Tool Use 只能形成一条 Agent Tool Call
系统 SHALL 使用 `invocation_id + runtime_tool_call_id` 聚合 `STARTED` 与终态 Tool Event，并为一次逻辑 SDK Tool Use 只保留一条 `agent_tool_call`。重复事件、Runtime 重连、终态恢复或 Worker 重试 MUST 幂等更新同一行，不得按状态、请求摘要或工具名称创建重复事实。

#### Scenario: STARTED 后收到成功终态
- **WHEN** 相同 invocation 和 SDK Tool Use ID 先产生 `STARTED`，随后产生 `SUCCEEDED`
- **THEN** 系统将同一 `agent_tool_call` 更新为成功、最终耗时和有界响应摘要

#### Scenario: Runtime 在终态前失败
- **WHEN** Runtime 已产生 `STARTED` Tool Event 后超时、断连或失败
- **THEN** 系统保留该 Tool Call，并以稳定失败状态结束或标记为未完成证据，不得丢失或复制该调用

### Requirement: MCP 执行审计必须与 Agent Tool Call 精确关联
每次进入平台 MCP Server 的有效 Job-bound Tool Call SHALL 由 MCP Server 分配唯一 `mcp_call_id`，并将对应的 `agent_tool_call.id` 与所有 `mcp_operation_audit` 事件精确关联。MCP Server MUST 通过标准 MCP `CallToolResult._meta` 返回非敏感关联标识，Runtime SHALL 将其与真实 SDK Tool Use ID 一并回传，Worker MUST 幂等补全关联。

#### Scenario: 相同 Job 连续调用同一工具
- **WHEN** 一个 Job 多次调用同一个 MCP Tool
- **THEN** 每次调用具有不同 `mcp_call_id`，且各自的 Agent Tool Call 只关联本次 MCP 审计事件

#### Scenario: 同一工具并发调用
- **WHEN** Runtime 并发发起名称相同但参数不同的 MCP Tool Call
- **THEN** 系统通过 `mcp_call_id` 与 SDK Tool Use ID 精确关联，不按 `job_id + tool_name`、时间顺序或载荷相似度猜测

#### Scenario: MCP 元数据未能传播
- **WHEN** 固定版本的 Agent SDK 未把 MCP `CallToolResult._meta` 传播到 Runtime Tool Result
- **THEN** 兼容性验收失败，系统不得退回按工具名称批量关联或把未知调用伪装成已精确关联

### Requirement: Tool Call响应摘要必须先结构化投影再限制长度
MCP 根 Tool Call 新写入及受授权的管理/Debug 读取 MUST 输出有界元数据摘要，不将集合、文件正文或业务对象复制到时间线。历史 JSON、payload、MCP text 和 runtime_file_bridge 包装 MUST 在有限大小与深度内解析后按固定字段投影；不得先截断 JSON 或在解析失败后直接回显原字符串。不可恢复摘要 MUST 明确标记不可用，传输包装截断不得冒充业务查询截断。

#### Scenario: 大结果的计数字段位于正文之后
- **WHEN** 合法历史响应正文超过2000字符且 returned 等字段位于集合之后
- **THEN** 管理详情返回完整的计数/完整性小对象，不返回任何集合正文

#### Scenario: 历史摘要已损坏
- **WHEN** 历史 JSON 已截断或超过读取预算
- **THEN** 返回摘要不可用标记，不展示原字符串或推测总量

### Requirement: Tool Call时间线必须显示安全失败原因
系统 MUST 在失败 Tool Call 中保存并展示服务端安全 error 和 error_code，支持对象和 JSON 字符串摘要。不得用通用占位文案遮蔽已存在的安全原因；不得展示原始 Provider body、认证秘密或堆栈。成功计数 MUST 优先使用 returned，不能把 total 误述为实际返回条数。

#### Scenario: ONES查询失败
- **WHEN** ones_query_work_items 返回 ones_provider_schema_invalid 或分页错误
- **THEN** 运行记录显示 FAILED、对应中文原因和错误码

#### Scenario: 上游提供敏感错误正文
- **WHEN** Provider 返回含认证信息的非规范错误正文
- **THEN** 记录和展示平台映射的安全错误，不保存或显示原始正文

### Requirement: 文件工具时间线必须区分操作阶段
时间线 MUST 根据实际 Tool 名称、调用状态与可用元数据展示文件读取、沙盒写入、提交意图和输出选择。文件正文、认证材料和不透明提交凭证 MUST NOT 展示；提交意图/选择输出 MUST NOT 声称文件已正式提交，不得根据缺失的历史元数据生成大小或路径。

#### Scenario: 沙盒写入成功
- **WHEN** Write 调用成功并有安全内容字节数
- **THEN** 显示沙盒写入完成及字节数，并说明尚未提交

#### Scenario: 创建提交意图或选择输出
- **WHEN** file_create_commit_intent 或 select_sandbox_output 成功
- **THEN** 显示对应阶段，不用通用占位文案，也不声称文件已提交

### Requirement: MCP操作审计必须关联完整平台Principal
系统 SHALL 为每次 `ones-mcp` Tool 与 Provider 尝试记录 correlation ID、Job、session、JWT `jti`、系统用户、外部身份、Team、server、Tool、operation、credential revision、attempt、status、error code、duration 和时间。

#### Scenario: 查询一次成功
- **WHEN** ONES 查询首次请求成功
- **THEN** 审计可从 Agent Tool Call 关联到唯一 MCP 操作和 Provider attempt

#### Scenario: 401刷新后成功
- **WHEN** 首次 Provider attempt 返回401、登录刷新成功且第二次查询成功
- **THEN** 审计记录各阶段的安全状态、attempt 和最终结果，并使用同一 correlation/Job/principal 链接

### Requirement: MCP审计必须原样保存完整有界业务载荷
受治理业务 MCP 的专用完整审计 SHALL 原样保存每次查询的 Tool Input、固定 Provider GraphQL document 与 variables、Provider 业务响应和规范化 Tool Output，并记录载荷 schema version；不得对 keyword、ONES 邮箱/User ID、工作项字段或其它业务字段做 hash、掩码、摘要或字段裁剪。载荷 MUST 先通过 Tool/Provider 的 JSON schema、响应大小和数量上限，非法或超限正文不属于可持久化业务载荷。

#### Scenario: 查询成功
- **WHEN** ONES 查询在已配置大小上限内返回合法业务响应
- **THEN** 审计保存完整 Tool Input、GraphQL document/variables、Provider 业务响应和 Tool Output，可重建该次业务查询证据

#### Scenario: 业务字段包含邮箱和工作项内容
- **WHEN** 合法请求或响应包含 ONES 邮箱/User ID、keyword、工作项编号、名称、类型或其它 schema 内业务字段
- **THEN** 审计按原值保存这些字段，不做脱敏、摘要或 hash

### Requirement: 认证秘密必须在审计结构之外
密码、ONES Token、Principal JWT、Authorization/Cookie、私钥、密文和 nonce MUST NOT 进入 `audit_event`、`agent_tool_call`、`mcp_operation_audit` 或其请求/响应 JSON。Provider 认证 Header、登录请求/响应和 challenge/credential 密文 SHALL 使用独立内部对象，不得传给业务审计序列化器；登录与刷新审计只保存邮箱/User ID、identity/credential ID、revision、状态、时间和错误码。

#### Scenario: Provider业务响应意外包含认证字段
- **WHEN** Provider 业务响应包含 Token、Authorization、Cookie、password、ciphertext 或 nonce 字段
- **THEN** 系统拒绝把该正文认定为合法业务响应，记录稳定 schema/secret violation 错误且不持久化该正文

#### Scenario: Provider错误正文回显认证材料
- **WHEN** Provider 错误正文回显认证材料
- **THEN** 审计保存稳定错误码和非认证业务错误字段，但不保存可重放认证材料

### Requirement: 审计写入失败必须失败关闭
当系统无法持久化要求的 MCP 操作审计时，MCP SHALL 返回安全失败，且不得把未审计的 Provider 成功结果交给 Agent。

#### Scenario: 审计数据库不可用
- **WHEN** ONES Provider 已返回结果但 MCP 操作审计提交失败
- **THEN** Tool 返回 `mcp_audit_unavailable` 安全错误且日志不包含原始结果或凭据

### Requirement: 完整业务审计必须受读取权限和保留期约束
完整 MCP 业务审计详情 SHALL 只允许已认证且通过 `resource_type=audit, resource_code=*, action=read` 授权的调用方读取，并 SHALL 审计读取行为。部署 MUST 配置 `MCP_OPERATION_AUDIT_RETENTION_DAYS`；系统 MUST 定期删除超过保留期的 MCP 操作记录及其业务载荷，缺少或非法配置时 `ones-mcp` readiness MUST 失败。

#### Scenario: 无审计读取权限
- **WHEN** 已认证用户没有 `audit:*:read` 权限并请求 MCP 审计详情
- **THEN** 系统拒绝访问且不返回任何业务载荷

#### Scenario: 审计超过保留期
- **WHEN** MCP 操作记录早于配置的保留期截止时间
- **THEN** 保留期任务删除该操作记录及完整业务载荷，并记录清理计数审计

### Requirement: Agent Tool Call 与 MCP 详细审计具有不同保留周期
`agent_tool_call` SHALL 跟随 Job 审计生命周期保留安全摘要；`mcp_operation_audit` SHALL 按配置保留详细 MCP 执行证据。清理 MCP 详细审计 MUST NOT 删除或破坏 Agent Tool Call、Job 历史和 SDK 原生 Tool 事实。

#### Scenario: MCP 审计超过保留期
- **WHEN** `mcp_operation_audit` 事件超过配置保留天数
- **THEN** 系统可删除该详细事件，但关联的 `agent_tool_call` 与其安全摘要保持可查询

### Requirement: Agent Job 生命周期事实与执行审计投影必须分离
系统 MUST 保持 `agent_job` 为 Job 身份、冻结来源、路由和生命周期状态的事实源，并 MUST 将可重算的模型轮次、Token、耗时、估算成本和执行失败诊断保存到独立执行审计投影。系统 MUST 为每个 Job 最多维护一条执行汇总，运行统计不得反向覆盖 `agent_job` 生命周期事实。

#### Scenario: Worker 首次执行 Job
- **WHEN** Worker 开始执行一个尚无执行汇总的 Job
- **THEN** 系统在独立执行汇总事实中创建或更新该 Job 的记录，而不改变 `agent_job` 的事实边界

#### Scenario: 查询没有执行统计的历史 Job
- **WHEN** 授权用户查询一个在本能力上线前已结束且没有执行投影的 Job
- **THEN** 系统将统计可用性返回为 `UNAVAILABLE`，不得把未知 Token、耗时或成本展示为零

### Requirement: 模型轮次必须按 SDK 观测语义记录
系统 MUST 为 SDK 消息流中可唯一识别的每个模型响应轮次保存一条 `agent_model_call` 事实，并 MUST 以 Job、invocation 和 Runtime 单调 sequence 或等价稳定身份保证幂等。模型轮次仅能记录模型标识、安全 request/message 标识、状态、时间、SDK 可见 Token、停止原因和有界错误；逐轮耗时 MUST 明确标记为 `SDK_OBSERVED` 或 `UNAVAILABLE`，不得表述为 Provider HTTP 精确耗时。

#### Scenario: 模型轮次具有可关联的起止边界
- **WHEN** Runtime 能将一次模型响应与 invocation 内的模型请求起点安全关联
- **THEN** 系统保存该轮次的 SDK 观测耗时并在 API 和页面中显示“SDK 观测”语义

#### Scenario: 模型轮次缺少可靠起点
- **WHEN** SDK 只提供模型响应完成消息而没有可关联的请求起点
- **THEN** 系统仍保存该模型轮次，但将其耗时和耗时来源记录为不可用，不得用 Job 总耗时或工具耗时推算

#### Scenario: 同一模型轮次被重放
- **WHEN** Runtime 恢复或 MQ 重复消费再次提交相同 invocation 和 sequence 的模型轮次
- **THEN** 系统只保留一条模型轮次事实且不重复累计任何 Token

#### Scenario: 逐轮成本不可得
- **WHEN** SDK 只在 ResultMessage 中提供整个 query 的估算成本
- **THEN** 系统只在 Job 执行汇总显示该估算成本，不得按 Token 比例伪造逐轮成本

### Requirement: ResultMessage 使用量必须形成幂等的 Job 级汇总
系统 MUST 以 SDK ResultMessage 为单次 invocation 的汇总证据，并 MUST 从 Job 下具有唯一终态身份的 invocation 重算 Job 级总耗时、API 总耗时、输入 Token、输出 Token、cache creation Token、cache read Token、按模型 usage 和估算成本。系统 MUST 优先使用覆盖完整 query 的 `modelUsage`；只有主循环 `usage` 可用时 MUST 将统计标记为 `PARTIAL`。汇总 MUST 区分 `COMPLETE`、`PARTIAL` 和 `UNAVAILABLE`，并 MUST 将 SDK 报告的成本标记为估算值。

#### Scenario: Job 首次成功完成
- **WHEN** Worker 保存一个通过合同校验的成功 ResultMessage 终态
- **THEN** 系统从唯一终态证据计算 Job 执行汇总，并返回四类 Token、总耗时、API 总耗时和估算成本

#### Scenario: Job 经历多次 Runtime invocation
- **WHEN** Job 因可重试错误产生多个具有不同 invocation 身份的终态证据
- **THEN** Job 汇总包含所有唯一 invocation 已实际消耗的可用 Token、耗时和估算成本，并保留是否重试耗尽的独立标记

#### Scenario: 终态或消息被重复投递
- **WHEN** 相同 `invocation_id + request_digest` 的终态事件被恢复或重复消费
- **THEN** 系统通过重算或幂等 upsert 得到相同汇总，不得对已有合计执行盲目累加

#### Scenario: ResultMessage 缺少完整核算字段
- **WHEN** ResultMessage 未提供 `modelUsage`、成本或某一类 Token
- **THEN** 系统将对应字段保留为未知并降低统计可用性，不得把缺失值记为零

### Requirement: 执行失败位置必须稳定、可关联且不覆盖根因
系统 MUST 使用稳定枚举和安全错误码定位 Runtime 启动、Runtime 协议、MCP 连接、模型 API、工具权限、工具执行和未知执行阶段的失败。Job retry 是否耗尽 MUST 作为独立结果保存，不得覆盖首次可行动的根因阶段。错误摘要 MUST 有界、脱敏，并能关联 Job、invocation 以及已有工具或 MCP 审计事实。

#### Scenario: 模型 API 错误后重试耗尽
- **WHEN** 模型 API 错误触发 Job retry 且最终耗尽允许次数
- **THEN** 系统返回失败阶段 `MODEL_API` 和 `retry_exhausted=true`，不得只返回笼统的 Job 失败

#### Scenario: 工具被权限策略拒绝
- **WHEN** SDK 或现有工具治理链拒绝一次工具调用
- **THEN** 系统返回失败阶段 `TOOL_PERMISSION`，并关联现有 `agent_tool_call` 或 ResultMessage permission denial 安全证据

#### Scenario: 工具或 MCP 执行失败
- **WHEN** 已允许的工具在执行阶段失败
- **THEN** 系统返回 `TOOL_EXECUTION` 根因并复用 `agent_tool_call` 与 `mcp_operation_audit`，不得复制原始请求或响应载荷

#### Scenario: 无法确定执行失败阶段
- **WHEN** 安全错误码不能确定性映射到受支持阶段
- **THEN** 系统返回 `UNKNOWN` 和可关联诊断码，不得根据错误文本猜测阶段

### Requirement: 每个 Runtime invocation 必须保存完整上下文审计
系统 MUST 为 protocol 1.5 中每个已完成上下文构建的 Agent Runtime invocation 保存不可变审计，包含完整应用 System/User Prompt、实际进入模型的上下文来源、SDK 原始消息、模型可见工具输入输出、Messages API 原始 request/response、usage、状态和时间。系统 MUST NOT 对这些正文执行应用层脱敏或长度截断；系统 MUST NOT 主动复制 Runtime Credential 或认证 Header。

#### Scenario: 成功 invocation
- **WHEN** Python Runtime 完成模型循环
- **THEN** Worker 持久化与 Runtime 实际装配和返回一致的完整审计
- **AND** 现有 Tool/MCP 主账继续保存安全摘要

#### Scenario: 失败或超时 invocation
- **WHEN** Runtime 在产生部分 SDK 消息或工具结果后失败或超时
- **THEN** 系统在失败或重试处理前保存已经产生的完整审计

#### Scenario: Provider 隐藏 reasoning
- **WHEN** SDK/Provider 未返回 hidden reasoning 正文
- **THEN** 系统原样保存实际暴露内容并标记限制，不构造缺失内容

### Requirement: 完整审计必须通过 Runtime v1.5 可验证分块传输
Runtime MUST 将审计 JSON 以带连续索引、总块数、编码和 SHA-256 的 `audit_chunk` 事件传输，并在 terminal 重复声明完整性元数据。Worker MUST 在持久化前验证块序、总数、摘要和 JSON 类型；不完整或冲突的审计 MUST fail closed。1.5 审计块原始编码每块最多 40 KiB、最多 1600 块；超出传输边界必须失败，不得截断后声称完整。受支持的 1.4 合同仍独立校验。

#### Scenario: 相同 invocation 恢复重放
- **WHEN** Worker 在收到部分 stream 后使用相同 invocation/request digest 恢复
- **THEN** Runtime 重放同一组审计块与 terminal
- **AND** Worker 只持久化一份内容一致的 invocation 审计

#### Scenario: 审计块缺失
- **WHEN** terminal 声明的块数或摘要与已收集内容不一致
- **THEN** Worker 以 Runtime 协议错误终止，不保存伪完整审计

#### Scenario: 审计块位于安全事件与终态之间
- **WHEN** Runtime v1.5 在安全事件之后、terminal 之前发送一个或多个 `audit_chunk`
- **THEN** Worker 按 Runtime 原始 sequence 保存不含 Base64 `content` 的审计块结构元数据与 terminal
- **AND** `agent_runtime_event` 序列保持连续，完整审计在校验重组后仍只保存一份

### Requirement: 调优摘要必须区分实际 usage 和构成估算
系统 SHALL 保存每轮/Result usage、请求次数、峰值上下文、Token/cache/cost、注册工具、单次最大加载工具、无需确认工具、调用次数和不同工具数。`allowed_tools` 仅计入无需确认工具，不得冒充注册或加载工具总数。峰值上下文按 `input_tokens + cache_creation_input_tokens + cache_read_input_tokens` 计算；字符估算 MUST 标明估算方法，不得冒充 Provider 计费事实。

#### Scenario: 多轮 Tool Loop
- **WHEN** 一个 invocation 产生多次模型 request 和重复工具调用
- **THEN** 页面分别展示请求次数、峰值上下文、累计 usage、注册/加载/调用/不同工具口径

### Requirement: 完整正文查询必须先通过现有 Job 授权并保持有界
完整审计 MUST 只通过要求 `jobs.read` 且命中现有业务范围的管理 Job 详情读取。初始 Job 详情 MUST 只返回 invocation 身份、状态、时间和调优摘要，不得查询或返回完整正文；完整正文 MUST 由详情下代码固定的审计字段接口在展开后按服务端固定每段 64 Ki 字符上限和游标分页读取。系统 MUST 在每次读取正文前完成 scope 判断，并 MUST 按 `job_id`、`audit_id` 和固定字段共同定位内容；Debug evidence、Tool Call 与普通 MCP 时间线 MUST 继续返回安全摘要，专用 MCP 完整业务审计按其独立授权读取。

#### Scenario: 范围外 Job
- **WHEN** 当前用户缺少 `jobs.read` 或目标 Job 不在其业务范围
- **THEN** API 返回拒绝或 404，且不查询或返回完整审计摘要或正文

#### Scenario: 展开一个完整审计字段
- **WHEN** 已授权管理员在 Job 详情展开一个代码固定的审计字段
- **THEN** API 只返回该 Job、该 invocation、该字段的当前有界正文分段和下一游标
- **AND** 客户端不得通过参数扩大服务端单段上限

#### Scenario: 请求非法字段、游标或其它 Job 的审计
- **WHEN** 客户端提交非允许字段、非法游标，或 audit ID 不属于路径中的 Job
- **THEN** API 失败关闭且不返回任何审计正文

### Requirement: 运行详情必须摘要优先并按需折叠长正文
Agent 运行详情 SHALL 保留现有执行、工具合同、文件和 Delivery 证据，并增加调优摘要。每个 attempt 的上下文/Prompt、模型 request/response、工具 I/O、usage/元数据 MUST 默认折叠；折叠关闭时 MUST NOT 请求、序列化或挂载完整正文。展开后 MUST 只渲染当前有界分段，支持换行、固定最大高度、滚动和上一段/下一段导航，不得累计挂载已经离开的分段。

#### Scenario: 超长上下文
- **WHEN** 管理员打开包含超长 Prompt 和工具结果的 Job
- **THEN** 初始页面不加载完整正文并保持可响应
- **AND** 管理员可逐组展开，通过有界分段查看完整内容而不阻塞页面主线程

#### Scenario: 工具契约证据较长
- **WHEN** 管理员打开包含工具快照、多个 invocation 观测和逐工具状态矩阵的 Job
- **THEN** 工具契约卡片的标题、说明、状态和总体摘要保持可见
- **AND** Job 快照及每个 invocation 内的长证据分组默认折叠
- **AND** 管理员可逐组独立展开或收起内部证据

#### Scenario: 工具契约摘要包含长标识
- **WHEN** Invocation ID 或其他摘要值超过单个网格列宽
- **THEN** 长标识在所属指标单元内断行
- **AND** 不得覆盖相邻指标的标题或内容

#### Scenario: 历史 Job
- **WHEN** Job 创建于完整审计启用前
- **THEN** 页面说明审计不可用，不按当前配置回填历史上下文

### Requirement: 运行记录查询和页面必须受授权且默认安全
运行记录 SHALL 在服务端按当前登录用户、租户、应用/运维范围过滤，并展示人员显示名/用户名、应用名称/编码、Agent、执行与投递状态、统计可用性、总/API耗时、模型轮次、四类 Token、估算成本、工具安全摘要与失败位置。显示名不得参与替代稳定身份的授权。默认查询条件为开始时间、结束时间、用户名和应用名；名称搜索同时匹配对应显示名或编码。普通列表、搜索、Debug evidence、Tool Call 主账不得查询完整 Runtime 审计正文；专用 MCP 审计详情与完整 invocation 正文分别使用其专用授权边界。

#### Scenario: 受权运维按名称查询
- **WHEN** 用户输入部分用户名、显示名、应用名或应用编码
- **THEN** 服务端只返回授权且匹配的 Job，客户端参数不能扩大范围

#### Scenario: 未授权应用
- **WHEN** 当前用户请求范围外 Job 或模型轮次
- **THEN** 请求被拒绝且不返回统计或正文

#### Scenario: 统计未采集
- **WHEN** 历史 Job 缺少执行或完整审计事实
- **THEN** 显示 UNAVAILABLE/未采集，不以零或当前配置填补历史

**结果与文件投递**

### Requirement: Agent results are delivered through reply routes
系统 SHALL 在 Agent 结果或安全失败通知持久化的同一事务内创建 Delivery Outbox event，并由独立 Delivery Dispatcher 按 Job 固化的 reply route 执行；Agent runtime 不得直接调用特定平台 client。

#### Scenario: Successful job has DingTalk delivery
- **WHEN** Agent Job 成功且固化 route 为受支持 DingTalk binding
- **THEN** 系统将 Job 标为 SUCCEEDED 并创建 Delivery Outbox，随后由 Dispatcher 发送并记录结果

#### Scenario: Failed job has failure delivery
- **WHEN** Agent Job 最终失败且配置了授权 Delivery binding
- **THEN** 系统创建安全失败通知的 Delivery Outbox，不在 Job 失败事务中调用外部 adapter

### Requirement: Delivery supports explicit none route
系统 SHALL 支持 `delivery.type=none`，用于 Debug API 或只需要查询接口读取结果的任务。

#### Scenario: None delivery route is used
- **WHEN** Agent job 完成且 `reply_route.type` 为 `none`
- **THEN** 系统不调用外部投递 adapter，但记录 delivery skipped 状态供审计和查询

### Requirement: Long reports are delivered in chunks
系统 SHALL 在最终报告超过目标平台单条消息限制时，将报告分片发送并持久化每个分片状态。

#### Scenario: Report exceeds DingTalk chunk limit
- **WHEN** DingTalk delivery 的报告长度超过配置的单片字符限制
- **THEN** 系统按顺序发送多个分片，每片包含 `part x/y` 标识，并记录每个 delivery chunk

#### Scenario: Report fits in one chunk
- **WHEN** 报告长度未超过目标平台单片字符限制
- **THEN** 系统发送一个分片并将 delivery attempt 标记为成功

### Requirement: Delivery failures do not re-execute Agent jobs
系统 SHALL 将 Delivery 状态机与 Agent Job 分离；Delivery 瞬时失败进入有限 RETRY_WAIT，耗尽后进入 DEAD，均不得重新执行 Agent 或把 SUCCEEDED Job 改为 FAILED。

#### Scenario: Delivery adapter returns transient failure
- **WHEN** Agent Job 已 SUCCEEDED 但 adapter 超时或返回瞬时错误
- **THEN** Delivery 进入 RETRY_WAIT，Job 保持 SUCCEEDED

#### Scenario: Duplicate Delivery event after successful result
- **WHEN** 已 SUCCEEDED 的 Delivery event 被重复消费
- **THEN** 幂等状态阻止重复发送已成功 attempt/chunk

#### Scenario: Delivery reaches DEAD
- **WHEN** Delivery 耗尽最大重试次数
- **THEN** Delivery 状态为 DEAD 并可被精确 CLI replay，Job 状态不变

### Requirement: Delivery attempts are auditable
系统 SHALL 持久化每次 delivery attempt 的目标类型、connector、目标安全摘要、状态、错误摘要、开始和结束时间。

#### Scenario: Delivery attempt completes
- **WHEN** 任一 delivery adapter 完成投递
- **THEN** 系统保存 delivery attempt 和 chunk 记录，并关联到 Agent job

#### Scenario: Delivery attempt fails
- **WHEN** 任一 delivery adapter 投递失败
- **THEN** 系统保存安全错误摘要，不记录 token、webhook secret 或敏感目标地址

### Requirement: DingTalk enterprise App delivery sends final reports directly
系统 SHALL 支持 `reply_route.type=dingtalk_enterprise_robot`，通过钉钉企业 App 凭据获取访问令牌并把 Agent 最终报告或安全失败通知直接发送到钉钉目标。

#### Scenario: Enterprise App delivery succeeds
- **WHEN** Agent job 完成且 `reply_route.type` 为 `dingtalk_enterprise_robot`
- **THEN** 系统使用该 route 的 delivery connector 获取 access token、发送钉钉消息，并记录成功的 delivery attempt 和 chunk

#### Scenario: Enterprise App token request fails
- **WHEN** 钉钉企业 App access token 获取失败
- **THEN** 系统将 delivery attempt 标记为失败、保存安全错误摘要，并保持 Agent job 原有执行状态不变

### Requirement: DingTalk webhook robot delivery sends group messages only
系统 SHALL 支持 `reply_route.type=dingtalk_webhook_robot`，按钉钉群机器人 webhook 协议把 Agent 报告发送到群，且该 route MUST NOT 创建 Agent job 或处理用户入口消息。

#### Scenario: Webhook robot delivery succeeds
- **WHEN** Agent job 完成且 `reply_route.type` 为 `dingtalk_webhook_robot`
- **THEN** 系统向 connector 配置的 webhook endpoint 发送群消息，并记录 delivery attempt 和 chunk 状态

#### Scenario: Webhook robot is used as ingress
- **WHEN** 外部请求尝试使用 webhook 群机器人 connector 作为 `from.connector_id`
- **THEN** 系统拒绝该入口请求，不创建 Agent job，也不发布 RabbitMQ 消息

### Requirement: 终态失败通知必须安全且幂等
系统 SHALL 对每个 Job 的终态失败通知实施持久化幂等；通知内容 MUST 不包含堆栈、API key、认证 token、完整 provider URL、完整 session webhook、内部原始 payload 或私有推理。

#### Scenario: 同一终态失败被处理两次
- **WHEN** 重复 dead-letter、Worker 重启或恢复操作再次处理已经成功发送失败通知的 Job
- **THEN** 系统检测已完成 delivery attempt，不再次发送相同终态通知

#### Scenario: 安全失败原因被构建
- **WHEN** Claude runtime 因 `claude_inconsistent_result` 最终失败
- **THEN** 用户通知说明模型运行暂时失败并附 Job 追踪标识，不直接输出矛盾的 `error result: success`、CLI stderr 或内部异常堆栈

### Requirement: 受管 Webhook 的结果路由由 Trigger publication 固定
系统 SHALL 使用 Webhook event 固定的 Trigger publication 构造 reply route，MUST NOT 接受外部 payload 提供任意 Delivery type、Connector、endpoint、token 或目标会话。

#### Scenario: Grafana 告警完成诊断
- **WHEN** Webhook Agent job 成功并生成最终报告
- **THEN** ResultDeliveryService 使用 Trigger publication 固定的钉钉 Connector 和安全目标分片投递结果

#### Scenario: payload 包含钉钉 Webhook URL
- **WHEN** 外部 payload 包含自定义 Webhook URL 或 delivery target
- **THEN** 系统不把该值写入 reply route、job 或外部请求

### Requirement: 业务应用约束钉钉回复原会话投递
系统 MUST 在业务应用路由命中后要求存在唯一、启用且与 ingress source connector 一致的 `reply_original` Delivery Binding，并 SHALL 使用事件生成的受信临时 reply route 完成实际投递。

#### Scenario: 有效回复原会话Binding
- **WHEN** 应用包含唯一 `reply_original` Binding，connector 与钉钉 Stream 来源一致，事件包含有效 session webhook
- **THEN** 系统将受信 reply route 固定到 Job
- **AND** Delivery Worker 将结果回复到原私聊或群聊

#### Scenario: 缺少回复原会话Binding
- **WHEN** 钉钉 Trigger 命中应用但没有启用的 `reply_original` Binding
- **THEN** 运行时将 route 标记为 `blocked/missing_delivery_binding`
- **AND** 不改用全局固定群或其他 Delivery 类型

#### Scenario: Binding connector不一致
- **WHEN** `reply_original` Binding 的 connector ID 与 ingress source connector ID 不同
- **THEN** 激活预检或运行时校验拒绝该配置
- **AND** 不把临时 session webhook 发送给不匹配的 Connector

### Requirement: 应用Delivery Binding不得持久化临时凭据
系统 MUST 将 Business Application Delivery Binding 作为投递授权和策略，不得在草稿、Publication、runtime status 或审计中保存 session webhook、访问 Token 或完整敏感 URL。

#### Scenario: 发布回复原会话配置
- **WHEN** 管理员发布包含 `reply_original` 的应用
- **THEN** Publication 只保存 delivery type、connector ID 和非敏感策略
- **AND** 临时投递目标只从每次受信钉钉事件进入受保护 Job reply route

#### Scenario: 管理端查看Delivery状态
- **WHEN** 管理员查看应用或 Job 的 Delivery 摘要
- **THEN** 页面显示类型、connector、状态和安全目标摘要
- **AND** 不显示可直接调用的 session webhook

### Requirement: 业务结果投递前重新校验当前应用权限
系统 SHALL 在发送可能包含业务数据的最终结果前，使用 job 持久化的用户、业务应用和路由上下文重新校验当前应用访问权限。权限已撤销、成员已到期、用户已停用或命中高级拒绝时 MUST 阻止业务结果投递。

#### Scenario: 投递前权限仍有效
- **WHEN** Agent job 已生成结果且请求者仍有目标业务应用权限
- **THEN** 系统按原 reply route 投递结果并记录投递前授权成功

#### Scenario: 投递前权限已撤销
- **WHEN** Agent job 已生成结果但请求者的目标业务应用权限已撤销
- **THEN** 系统不得发送业务结果，只向支持的原会话发送“权限已发生变化，本次结果未投递，请联系管理员”的中文安全通知，并记录“执行完成但投递被权限拦截”

#### Scenario: 安全通知也无法投递
- **WHEN** 权限拦截后原 reply route 已不可用
- **THEN** 系统记录安全通知投递失败，不回退到其它未授权目标，也不重新执行 Agent job

### Requirement: Delivery 查询必须展示独立生命周期
管理 API 和 Job 详情 MUST 展示 Delivery event、attempt、chunk、重试次数、下次重试时间、终态和安全错误，不得把“已请求投递”显示为“已送达”。

#### Scenario: Delivery 尚未被 Dispatcher 领取
- **WHEN** Job 已完成但 Delivery Outbox 为 PENDING
- **THEN** 页面显示 Agent 已完成、投递待处理

### Requirement: Delivery replay 必须使用原始持久化意图
授权 CLI replay MUST 复用原 Job 固化的 binding、目标安全摘要和结果 artifact，不允许输入任意目标或消息体。

#### Scenario: 运维尝试改变 DingTalk 目标
- **WHEN** replay 请求提交不同 Connector 或 recipient
- **THEN** 系统必须拒绝并记录审计

### Requirement: 钉钉文件结果按精确版本创建独立交付
钉钉用户明确要求修改或生成TXT/Markdown时，成功提交的精确File Version SHALL默认创建回当前reply route的文件交付意图，用户明确要求只保存到工作区时除外。用户明确要求发送当前Manifest中获授权的既有TXT/LOG/Markdown时，系统 MAY创建该精确版本的交付意图但 MUST NOT修改内容或创建新版本。文件交付 MUST创建新的钉盘文件并记录新外部引用、精确Version ID和输入来源血缘，不得覆盖输入原件、交付冲突候选或跨会话发送。

当原reply route为钉钉Stream `sessionWebhook`时，普通文字回复 SHALL继续使用该Webhook；精确文件版本交付 MUST使用入站冻结的会话类型和来源Stream Connector应用凭据调用钉钉机器人OpenAPI，私聊目标为冻结的实际发送人，群聊目标为冻结的`openConversationId`。该专用途径 MUST只处理与原Job、原会话、原Connector绑定的`FILE_VERSION` Delivery，不得授予Stream Connector通用结果投递能力。

`file_deliver_version` SHALL接受当前Manifest中具有`DELIVER`动作的精确版本，或当前RUNNING Job自身`COMMITTED`提交意图产生的精确TXT/Markdown版本。对后者，File Service MUST复核Commit、Job、Workspace、Version、format、文件归属和内容可用性；不得要求把新输出补写进不可变输入Manifest，也不得仅凭模型提供的File/Version ID授权。
#### Scenario: 群聊生成TXT结果
- **WHEN** 群聊Job按用户请求成功提交一个新TXT版本
- **THEN** 系统为当前群reply route创建该精确版本的新钉盘文件交付
- **AND** 原输入钉盘文件保持不变
#### Scenario: 用户要求只保存
- **WHEN** 用户明确要求TXT或Markdown结果只保存在任务工作区
- **THEN** 系统提交版本但不创建文件交付意图
#### Scenario: 私聊Stream文件与文字使用不同受控通道
- **WHEN** 私聊Job正常回复文字并成功提交默认交付的新Markdown版本
- **THEN** 文字结果通过冻结的`sessionWebhook`发送
- **AND** 文件版本通过来源Stream应用的私聊机器人OpenAPI发送给冻结的实际发送人
#### Scenario: 当前Job显式交付刚提交的新版本
- **WHEN** Agent对当前Job刚成功提交且不在输入Manifest中的精确TXT或Markdown版本调用`file_deliver_version`
- **THEN** File Service以提交意图来源证明授权并幂等返回同一Delivery状态
- **AND** 不返回“文件操作尚未就绪”或扩大Manifest
#### Scenario: 群聊生成Markdown结果
- **WHEN** 群聊Job按用户请求成功提交一个新Markdown版本
- **THEN** 系统为当前群reply route创建该精确版本的新钉盘文件交付
- **AND** 原输入钉盘文件保持不变且平台不渲染Markdown
#### Scenario: 私聊原样发送LOG
- **WHEN** 私聊Job按用户要求交付Manifest中具有`DELIVER`动作的既有LOG精确版本
- **THEN** 系统通过冻结reply route交付完全相同的版本和哈希
- **AND** 不创建Commit Intent、新文件版本或修改日志内容

### Requirement: 文件版本提交与文件交付使用独立状态机
文件版本通过校验并提交后 MUST 保持当前版本，即使随后钉钉文件交付失败。Delivery重试 MUST 固定同一个File Version和交付意图，不得重跑Agent、生成另一份内容、回滚版本或改变已`SUCCEEDED`的Job。工作区到期时存在非终态交付 SHALL 只暂缓该精确内容清理；成功交付使该版本成为Retained File，最终失败后若工作区已到期则立即清理临时内容。

#### Scenario: 文件交付暂时失败
- **WHEN** File Version已提交但钉钉上传超时
- **THEN** Delivery进入自身重试状态且Job与当前版本保持不变
- **AND** 重试仍发送同一内容哈希的精确版本

#### Scenario: 文件交付已排队但尚未完成
- **WHEN** Commit 或显式交付回执的 `delivery_status` 为 `PENDING`
- **THEN** Agent 只能说明精确文件交付已排队，不得宣称文件已经发送或到达
- **AND** 文件实际到达作为成功信号，不额外发送成功通知

#### Scenario: 文件交付最终失败
- **WHEN** `FILE_VERSION` Delivery 因非重试错误进入 `FAILED` 或重试耗尽进入 `DEAD`
- **THEN** 系统沿原 Job 冻结 reply route 幂等创建最多一次安全文字通知，说明文件仍保存于工作区但回发失败
- **AND** 不回滚版本、不重跑 Agent、不改变 Job 终态，且通知自身失败不递归创建新通知

#### Scenario: 终态与通知创建之间发生崩溃
- **WHEN** 文件 Delivery 已持久化为 `FAILED/DEAD` 但进程在创建通知前退出
- **THEN** 后续 Dispatcher 扫描补建同一个确定身份的通知 Delivery
- **AND** 并发或重复扫描不会创建多条用户通知

### Requirement: 原件交付与表示阅读使用独立身份
系统 SHALL 使用Job冻结或当前授权的原始File Version完成文件下载、保留和Delivery，并只使用冻结Markdown Representation完成Agent阅读。Processing run、representation失败或Agent对Markdown的本地读取不得改变原始File Version、Delivery状态或Agent Job终态；交付原件失败也不得重新执行Docling或Agent。
#### Scenario: 总结后转发原件
- **WHEN** Agent使用Markdown representation完成总结且用户要求转发原PDF
- **THEN** Delivery按精确原始Version创建独立文件交付
- **AND** 不交付representation或重新运行处理任务
#### Scenario: 原件交付失败
- **WHEN** Agent Job已成功但原件Delivery出现可重试错误
- **THEN** 只重试Delivery状态机
- **AND** 不重新执行Agent Job或processing run

**外部操作确认与执行**

### Requirement: 外部 mutation 必须先创建不可变操作意图
任何代码注册为 `mutation` 的业务 MCP Tool SHALL 在有效 Job 内只创建持久 `Action Intent` 和确认卡投放 Outbox，不得在首次 Tool Call 中访问写入型 Provider endpoint。意图 MUST 冻结 Job、Session、actor、Application/Agent Publication、Server、Tool/schema、确认策略、来源 Connector、规范化参数及其 hash。

#### Scenario: Agent 提议创建待办
- **WHEN** RUNNING Job 调用已授权的 `dingtalk_create_todo`
- **THEN** 系统原子创建 `PENDING_CONFIRMATION` 意图与卡片 Outbox，返回 `confirmation_required`
- **AND** 不调用钉钉待办创建接口

#### Scenario: 同一 Tool Call 重试
- **WHEN** 同一 Job、Tool、规范化参数 hash 与代码固定 fingerprint 再次进入准备阶段
- **THEN** 系统返回原意图且不创建第二张卡或第二个执行记录

### Requirement: 确认回调必须绑定原始 actor 和当前 revision
系统 MUST 仅接受来源 Connector、企业、`outTrackId`、点击用户、opaque intent token、action 和 revision 与当前意图全部一致的卡片回调。卡片禁止转发 MUST NOT 替代服务端 actor 校验。

#### Scenario: 原始用户同意当前版本
- **WHEN** 原始 actor 在原 Connector 的卡片上提交 `agree` 且 revision 匹配
- **THEN** 系统只把意图从 `PENDING_CONFIRMATION` 转为 `APPROVED` 并返回快速 ACK

#### Scenario: 其他用户点击转发卡
- **WHEN** 回调 `userId` 不等于意图目标外部用户
- **THEN** 系统拒绝且不改变意图、不创建执行、不泄露参数

#### Scenario: 重复或过期点击
- **WHEN** 回调针对终态、过期或 revision 不匹配的意图
- **THEN** 系统返回幂等或安全拒绝结果且不重复执行

### Requirement: 拒绝不得产生 Provider 副作用
合法 `reject` SHALL 把当前待确认意图转为 `REJECTED`，并 MUST NOT 创建、claim 或执行任何 Provider mutation。

#### Scenario: 用户拒绝创建待办
- **WHEN** 原始 actor 对当前意图提交合法 `reject`
- **THEN** 卡片更新为已拒绝且 Provider 调用次数为零

### Requirement: 已批准意图必须异步、可恢复且执行前重新授权
外部操作 worker SHALL 以数据库 claim/lease 获取 `APPROVED` 意图，在 Provider I/O 前重新复核当前用户、身份、Connector、企业、Application、Tool/schema 和角色授权。worker MUST 在事务外执行外部 I/O，并把结果写为 `SUCCEEDED`、`FAILED` 或不确定失败终态。

#### Scenario: 批准后权限仍有效
- **WHEN** worker claim 已批准意图且所有当前事实仍有效
- **THEN** worker 只执行一次固定 Provider operation 并持久化有界结果

#### Scenario: 批准后 Tool 被撤权
- **WHEN** 用户点击同意后角色或 Application 已撤销该 Tool
- **THEN** worker 在 Provider I/O 前失败关闭并记录授权拒绝

#### Scenario: worker 在 claim 后重启
- **WHEN** 执行租约超时且没有已确认 Provider 成功事实
- **THEN** 恢复器按意图的幂等策略重新 claim 或转为不确定失败，不得无条件重复创建

### Requirement: 卡片投放和结果更新必须使用有界 Outbox
确认卡创建、投放和结果更新 SHALL 由持久 Outbox 驱动，`outTrackId` MUST 等于 Action Intent ID，`callbackType` MUST 为 `STREAM`，`supportForward` MUST 为 false。卡片参数 MUST 只包含安全业务摘要、revision 和 opaque token。

#### Scenario: 投放本人确认卡
- **WHEN** 卡片 worker 处理新意图 Outbox
- **THEN** 系统使用原 Connector 应用和指定模板向原始钉钉用户投放一张不可转发卡

#### Scenario: Secret 出现在卡片参数
- **WHEN** 待投放字段包含 Token、密码、Principal JWT、Cookie 或平台 Secret
- **THEN** 系统拒绝整个投放且不持久化或发送该值

### Requirement: 外部操作必须由独立 Worker 领取并执行
系统 SHALL 使用独立 external-action-worker，按持久 Card Outbox、过期执行对账、APPROVED 意图顺序处理工作；单进程 run_once 串行执行。数据库 MUST 通过条件更新让同一 APPROVED 意图仅被一个 Worker 转为 EXECUTING；不得把进程数量或同意图互斥宣称为跨所有意图的全局并发上限。中断后只允许 Provider 固定只读对账，不能确认结果时进入 FAILED_UNCERTAIN 并禁止自动重放。

#### Scenario: 两个 Worker 同时扫描同一意图
- **WHEN** 两个实例竞争同一 APPROVED 行
- **THEN** 只有一个条件更新成功并执行该意图，其余不执行该意图

#### Scenario: Worker 中断后结果不确定
- **WHEN** 执行 lease 过期且固定 Provider 对账不能确认成功
- **THEN** 意图进入 FAILED_UNCERTAIN，卡片提示人工核对，不自动重复 mutation

### Requirement: 确认、Provider 与卡片结果必须形成同一审计链
系统 SHALL 以 Action Intent ID、MCP call、Agent Tool Call、Job、Session、actor、Connector、Tool/schema 和 Provider attempt 串联准备、投放、点击、授权复核、执行与结果更新；不得保存 Secret 或原始无界回调。

#### Scenario: 创建待办成功
- **WHEN** 用户确认且 Provider 执行成功
- **THEN** 审计可从 Agent Tool Call 追溯到卡片点击和唯一 Provider attempt

### Requirement: 修订动作不得原地改写已冻结意图
确认卡 `revise` SHALL 只记录修订请求并提示用户回原会话说明修改字段；回调不得修改规范化参数、创建 Agent Job 或执行 Provider。支持提案替代的业务工具 MUST 在后续合法 Job 中创建新的完整不可变意图，通过 `proposal_chain_id` 与 `supersedes_intent_id` 关联，将旧待确认意图标为 `SUPERSEDED`，并要求用户确认新意图；不得把旧同意复用于新参数。

#### Scenario: 用户点击修订
- **WHEN** 合法原 actor 对当前意图回传 revise
- **THEN** 保持意图状态并返回固定回原会话修改提示，不直接执行原意图或新 Provider 请求

#### Scenario: 新提案替代旧提案
- **WHEN** 支持替代的业务工具在相同受权提案边界生成新完整参数
- **THEN** 保存独立新意图与同一提案链，旧意图失去可批准资格，新意图重新等待确认

## 实现依据与验证边界

实现依据：`backend/app/modules/job/application/create_agent_job_service.py`、`job_retry_service.py`、`debug_job_access_service.py`、`backend/app/modules/job/domain/{agent_job,execution_policy,job_status}.py`；`backend/app/modules/mcp_tool_runtime/job_snapshot.py`、`services/ones_mcp_server/auth/principal.py`、`services/external_action_worker/ones_adapter.py`；`backend/app/modules/agent/application/agent_executor.py`、`backend/app/modules/agent/infrastructure/runtime_protocol.py`、`runtime_http_client.py`；`backend/app/python_runtime/{executor,mcp_config,tool_contract,tool_policy,run_audit,invocations}.py`；`backend/app/shared/agent_run_audit_codec.py`；`contracts/agent-runtime/v1.4/` 与 `v1.5/`；`backend/app/modules/job/infrastructure/repositories.py`、`backend/app/modules/admin/api/controller.py`；`backend/app/modules/delivery/application/`；`backend/app/modules/external_action/`、`services/external_action_worker/runtime.py`、`services/dingtalk_mcp_server/worker.py`。

对应测试包括 `backend/tests/test_agent_retry_and_failure_delivery.py`、`test_agent_job_debug_authorization.py`、`test_mcp_tool_runtime.py`、`test_ones_mcp_runtime.py`、`test_ones_task_update.py`、`test_job_dispatch_fault_integration.py`、`test_python_runtime_run_audit.py`、`test_agent_run_audit_repository.py`、`test_delivery_outbox_chunk_idempotency.py`、`test_delivery_outbox_atomic_terminal.py`、`test_log_evidence_scanner.py` 和 `frontend/src/contexts/operations/presentation/runtime-records.test.tsx`。这些代码与测试定义是当前实现依据；本次仅做文档对账与规格验证，未执行真实模型、MCP、钉钉、RabbitMQ 或生产数据库验收。Prompt 自检不构成程序级明细完整性保证；外部 mutation 的真实 Provider 幂等、卡片与恢复能力仍须对应环境验收。

实现差异：外部操作 Worker 当前只有单进程串行与单意图数据库互斥，没有代码实现的全局并发槽位/可配置上限；Compose 健康检查只判断 heartbeat 文件存在，不能证明心跳新鲜度或 Provider 可用。以上不计为已实现的全局并发/严格 readiness 能力。
