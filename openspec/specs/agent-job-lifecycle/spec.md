# agent-job-lifecycle Specification

## Purpose
TBD - created by archiving change add-readonly-diagnostic-agent-mvp. Update Purpose after archive.
## Requirements
### Requirement: Agent sessions and jobs are persisted
The system SHALL persist Agent sessions, Agent jobs, user messages, assistant messages, retry metadata, result summaries, failure reasons, source channel metadata, requester identity, routing context, reply route, and an immutable Tool Execution Snapshot before dispatch. The Snapshot MUST include the exact Agent/Application Publication, Tool Releases, Handler Versions, Implementation Digests, Business Target Path, permitted placements, Resource Revisions, Partition/Loki Policy IDs/revisions/hashes and authorization-fact summary required by the Job.

#### Scenario: New diagnostic request is accepted
- **WHEN** a verified Channel request passes connector, publication, identity, permission, target and resource-composition checks
- **THEN** the system persists the session, Job, user message, routing facts and complete Tool Execution Snapshot before publishing the Job to the message bus

#### Scenario: Agent result is produced
- **WHEN** Agent execution completes with a final answer
- **THEN** the system persists the assistant message, result summary, Job completion timestamp, delivery-ready result artifact and exact Tool Call fact references

#### Scenario: Legacy DingTalk request is accepted during cutover
- **WHEN** an existing DingTalk endpoint creates a new Job after exact-snapshot cutover
- **THEN** the system persists equivalent generic channel fields and a complete exact Tool Execution Snapshot; it MUST NOT create a new `legacy-v1` tool binding

#### Scenario: Snapshot cannot be constructed uniquely
- **WHEN** the active Publication produces zero or multiple Tool/Resource/Policy candidates for the requested target
- **THEN** Job creation fails before queue dispatch and records a safe non-retryable composition error

### Requirement: Agent job status transitions are controlled
系统 SHALL 通过 job application service 控制 Agent job 状态转换，并至少支持 PENDING、RUNNING、SUCCEEDED、FAILED 和 TIMEOUT。Worker 在把 PENDING job 转为 RUNNING 前 MUST 使用 job 固定的业务应用上下文和当前用户授权重新校验；授权已撤销、角色已到期或应用访问不再成立时 MUST 以非重试权限失败终止，不得调用模型或业务能力。

#### Scenario: Worker claims pending job
- **WHEN** Agent worker 接收一个 PENDING job 且执行前授权仍有效
- **THEN** 系统把 job 转为 RUNNING、记录开始时间和授权决策

#### Scenario: Permission changed before worker claim
- **WHEN** job 排队期间用户的应用授权被撤销或成员关系到期
- **THEN** Worker 不调用模型或工具，把 job 标记为 FAILED 并记录非重试的中文安全原因

#### Scenario: Worker completes job
- **WHEN** Agent worker 产生有效最终报告
- **THEN** 系统把 job 从 RUNNING 转为 SUCCEEDED 并记录完成时间

#### Scenario: Worker hits timeout
- **WHEN** Agent worker 超过配置的执行超时时间
- **THEN** 系统把 job 转为 TIMEOUT 并记录安全超时原因

### Requirement: Message bus is independent from Agent execution
The system SHALL keep RabbitMQ behind Outbox Dispatcher publisher and consumer interfaces so API transaction logic and Agent execution do not depend on RabbitMQ classes, channels, exchanges, or queue names.

#### Scenario: API server accepts a job
- **WHEN** the API server commits a new Agent Job
- **THEN** it commits a Job Dispatch Outbox event and does not publish RabbitMQ directly in the request transaction

#### Scenario: Dispatcher publishes a job
- **WHEN** a due Job Dispatch Outbox event is claimed
- **THEN** the Dispatcher publishes only event/job/correlation identifiers through the message publisher interface

#### Scenario: Worker receives a job
- **WHEN** RabbitMQ delivers a job message
- **THEN** the message bus consumer passes the persisted job identifier to the handler without exposing RabbitMQ delivery details to AgentExecutor

### Requirement: RabbitMQ queues support retry and dead letter handling
系统 SHALL 定义普通执行、版本化延迟重试和 dead-letter 队列；可重试消息 MUST 在配置延迟后自动回到普通执行队列，重试耗尽或不可重试错误 MUST 进入 dead-letter 路径。

#### Scenario: Retryable failure occurs
- **WHEN** Agent 执行因可重试 Internal API、Loki、Claude、RabbitMQ、数据库 timeout 或瞬时连接错误失败
- **THEN** 系统将 Job 置为 `RETRY_WAIT`，增加 retry metadata，并调度仅包含 `job_id` 与 `correlation_id` 的延迟 retry 消息

#### Scenario: Retry delay expires
- **WHEN** retry 消息的 expiration 到期
- **THEN** RabbitMQ 将同一最小消息 dead-letter 到主队列，Worker 根据数据库 `RETRY_WAIT` 状态和 `next_retry_at` 决定是否 claim

#### Scenario: Retry limit is exceeded
- **WHEN** 可重试 Job 已使用全部配置重试次数
- **THEN** 系统将 Job 标记为 `FAILED`，路由 dead-letter，不再调度 Agent execution retry

#### Scenario: Non-retryable failure occurs
- **WHEN** Agent 执行因权限拒绝、未知数据源、SQL policy 拒绝、无效工具参数、明确配置错误或不支持请求失败
- **THEN** 系统将 Job 标记为 `FAILED`，不调度 retry，并路由 dead-letter

### Requirement: Worker execution is idempotent
系统 SHALL 防止初次消息、retry 回流消息、重复 RabbitMQ delivery 和恢复操作并发执行同一 Job，或产生重复成功结果/终态失败通知。

#### Scenario: Same pending job is delivered twice
- **WHEN** 两个 Worker 收到同一个 `PENDING` Job 标识
- **THEN** 只有一个 Worker 能原子 claim，另一个消息按持久化状态被 ack 或忽略

#### Scenario: Same retry job is delivered twice
- **WHEN** 两个 Worker 收到同一个已到期 `RETRY_WAIT` Job 标识
- **THEN** 只有一个 Worker 能将其转为 `RUNNING`，retry count 不重复增加且模型不被重复调用

#### Scenario: Completed job is delivered again
- **WHEN** 已达到 `SUCCEEDED`、`FAILED` 或 `TIMEOUT` 的 Job 再次收到主队列或 retry 消息
- **THEN** 系统不重新执行 Agent，也不重复发送已经成功完成的结果或失败通知

### Requirement: Message bus payload remains channel agnostic
The system SHALL keep RabbitMQ job messages limited to internal execution identifiers such as `job_id` and `correlation_id`; external Channel payloads MUST be persisted before queue dispatch instead of embedded in the queue message.

#### Scenario: Channel request dispatches job
- **WHEN** a Channel request creates an Agent job
- **THEN** the message publisher sends only the job identifier and correlation identifier to the Agent job queue

### Requirement: 附件任务与Agent任务只使用内部标识
系统 SHALL 让附件任务只携带attachment ID，让Agent任务继续只携带job ID和correlation ID；外部payload、媒体凭证和二进制 MUST 留在受控边界内。

#### Scenario: Attachment task is dispatched
- **WHEN** 入口发布附件处理任务
- **THEN** 消息只包含内部attachment ID和追踪标识

#### Scenario: Agent job is released
- **WHEN** WAITING_INPUT job被释放到Agent队列
- **THEN** 队列仍只包含job ID和correlation ID，worker从仓储构建输入

### Requirement: Job retries preserve identity and Agent publication
The system SHALL preserve the internal requester, external identity reference, Agent publication ID, revision and config hash across queue retries and duplicate deliveries.

#### Scenario: Agent publication changes before retry
- **WHEN** a retryable job is waiting and an administrator publishes a new Agent version
- **THEN** the retry uses the original fixed publication

#### Scenario: Duplicate job delivery occurs
- **WHEN** RabbitMQ redelivers the same job
- **THEN** idempotent claim and execution use the same persisted internal requester and Agent publication

### Requirement: Job retries preserve identity, Agent publication and reply route
系统 SHALL 在所有 retry、重复 delivery 和显式恢复中保持原内部请求人、外部身份引用、Agent publication ID/revision/hash、会话和 reply route，不得在重试时重新选择当前用户映射或最新 Agent 发布版本。

#### Scenario: Agent publication changes during retry wait
- **WHEN** Job 等待重试期间管理员发布新的 Agent revision
- **THEN** retry 仍使用原 Job 固定的 publication snapshot、工具集合和模型策略

#### Scenario: DingTalk identity or role changes during retry wait
- **WHEN** 原用户的钉钉绑定或角色在 Job 等待重试期间发生变化
- **THEN** 系统保留历史 Job 的身份引用和审计事实，同时在实际工具访问处继续执行适用的当前安全授权检查

### Requirement: Webhook job 保存可复现的 Trigger 来源
系统 SHALL 为 Webhook 创建的 Agent job 保存 `webhook_event_id`、Trigger definition/publication、服务账号和固定 Agent publication 引用，并 MUST 保持历史 job 在配置变化后仍可追溯。

#### Scenario: Webhook dispatcher 创建 job
- **WHEN** dispatcher 处理一个 `DISPATCH_PENDING` event
- **THEN** job 事务保存 Webhook 来源引用、服务账号、routing、reply route 和固定 Agent revision/hash

#### Scenario: 普通钉钉或 Debug job
- **WHEN** job 不是由受管 Webhook 创建
- **THEN** 新增 Webhook 来源字段保持为空且不改变现有生命周期

### Requirement: Webhook 队列载荷保持最小且可幂等恢复
系统 SHALL 只向 Webhook dispatch 队列发布 event ID 和 correlation ID，并继续只向 Agent job 队列发布 job ID 和 correlation ID；消费者 MUST 通过数据库状态恢复上下文。

#### Scenario: Webhook dispatch 消息重复投递
- **WHEN** 同一个 event ID 被 RabbitMQ 至少一次投递多次
- **THEN** 消费者复用已经关联的 job并确认消息，不重复创建 job

#### Scenario: Agent job 消息重复投递
- **WHEN** Webhook job 已成功或处于不可重复执行状态后再次收到相同 job ID
- **THEN** 现有 job 幂等状态机阻止再次执行 Agent 和重复成功 Delivery

### Requirement: Agent Job持久化业务应用运行来源
系统 MUST 为命中业务应用创建的 Agent Job 持久化 application ID/code、Application Publication ID、Deployment ID、route ID、应用 config hash 和运行时状态，并 MUST 在发布队列消息前完成持久化。

#### Scenario: 命中应用创建Job
- **WHEN** Channel event 成功解析到活动 Business Application
- **THEN** Job 与其消息、会话和路由信息一起保存完整应用 provenance
- **AND** 管理 API 能回答该 Job 由哪个应用版本处理

#### Scenario: 未命中应用不创建Job
- **WHEN** 钉钉 Channel event 未命中活动业务应用
- **THEN** 系统不创建 Agent Job 或 MQ 消息
- **AND** 既有迁移前 Job 的空 provenance 仍可只读显示为 `legacy_unattributed`

#### Scenario: 读取历史Job
- **WHEN** 管理端读取迁移前创建且没有应用 provenance 的 Job
- **THEN** API 返回 `legacy_unattributed` 或等效状态
- **AND** 不根据当前 Deployment 回填历史归属

### Requirement: Job固定的应用版本贯穿执行生命周期
系统 SHALL 让 Worker、重试和最终 Delivery 使用 Job 已固定的 Agent Publication 与应用 provenance，MUST NOT 在消费、重试或投递时重新解析当前 Business Application Deployment。

#### Scenario: Worker消费后应用已升级
- **WHEN** Job 入队后 Deployment 切换到新 Publication
- **THEN** Worker 仍使用 Job 固定的旧 Agent Publication
- **AND** Job 历史显示旧应用 Publication

#### Scenario: Agent执行重试
- **WHEN** 可重试执行错误触发 Agent Job 重试
- **THEN** 重试继续使用相同应用和 Agent Publication provenance
- **AND** 不因重新解析产生版本漂移

#### Scenario: Delivery单独重试
- **WHEN** Agent 已成功而结果投递失败
- **THEN** 系统只重试固定 reply route 的 Delivery
- **AND** 不重新执行 Agent 或重新解析业务应用

### Requirement: 应用会话策略在Job创建时冻结
系统 MUST 将本阶段已支持的 Session Policy 有效值传入会话和上下文构建流程，并 SHALL 在 Job 或安全运行摘要中记录策略版本来源。

#### Scenario: 应用启用连续对话
- **WHEN** 命中应用的 Publication 启用连续对话并设置最近消息上限
- **THEN** Job 使用应用隔离的 Session 并按该上限加载历史消息

#### Scenario: 应用禁用附件
- **WHEN** 命中应用的 Publication 将附件设为禁用
- **THEN** 系统按既有安全契约拒绝或忽略该事件附件
- **AND** 不使用全局默认重新启用附件

### Requirement: MQ载荷保持最小且不复制应用快照
系统 MUST 保持 RabbitMQ Agent Job 消息只携带 Job ID、correlation ID 和现有最小路由字段，MUST NOT 将 Business Application snapshot、session webhook、Secret 或消息原文复制到队列。

#### Scenario: 发布应用Job
- **WHEN** 命中应用的 Job 已在数据库事务中保存
- **THEN** Publisher 只发布可用于 Worker 回读 Job 的最小消息
- **AND** Worker 从持久化 Job 和固定 Publication 引用恢复运行配置

### Requirement: 运行中的业务能力调用重新校验当前授权
系统 SHALL 在运行中每次业务能力调用前重新校验当前角色成员状态、业务应用能力和数据范围。权限变化导致的拒绝 MUST NOT 重试，也不得访问目标数据源。

#### Scenario: 执行中撤销数据范围
- **WHEN** job 运行期间管理员撤销目标基地范围，随后 Agent 请求该基地能力
- **THEN** 系统在调用 Internal API Platform 前拒绝请求并记录授权变化

### Requirement: Job 必须保存创建时的授权与资源事实
Job MUST 保存内部用户、业务应用发布、Handler 版本、Resource Revision binding、Execution Scope 和 Session 策略快照；后续配置变化不得扩大该 Job 权限。

#### Scenario: Job 排队期间用户权限被撤销
- **WHEN** Worker 开始执行前发现当前严格 RBAC 已撤销
- **THEN** Worker 必须拒绝执行并记录安全授权失败

#### Scenario: 资源发布新 revision
- **WHEN** Job 创建后同一 Resource Identity 发布新版本
- **THEN** 原 Job 仍只能使用创建时固化的 revision

### Requirement: Job 状态与 Delivery 状态必须分别查询
Job 查询 MUST 分别返回 Agent 执行终态和 Delivery 汇总状态，不得把“Job SUCCEEDED”解释成“外部消息已送达”。

#### Scenario: Job 成功但 Delivery 重试中
- **WHEN** Agent Job 已 SUCCEEDED 且 Delivery 为 RETRY_WAIT
- **THEN** 查询结果必须同时展示两个状态及其独立时间线

### Requirement: External Execution Subject Snapshot 不随绑定变化漂移
Job 创建后 MUST 保持外部 User ID 和 default Team ID 快照不可变；每次外部 Tool调用仍 MUST 对当前启用绑定、最新 Team 集合和当前个人 Token实施实时撤权校验。系统 MUST NOT 因用户换绑、切换 Team 或解绑而改写旧 Job。

#### Scenario: 用户在排队期间切换 Team
- **WHEN** Job 已入队且用户随后更改 default Team
- **THEN** Job 保留原 Team快照，并在原 Team不再有效时失败关闭

#### Scenario: 用户轮换同一主体的 Token
- **WHEN** Job快照User/Team仍有效且只有个人Token更新
- **THEN** 执行时可以解析新Token而不修改Job快照

### Requirement: 规范化 Capability 结果沿用既有持久化生命周期
通过 Output Schema 和大小限制的 Capability Tool结果以及最终回复 SHALL 按现有 Job、Tool Call、会话与制品模型正常持久化；系统 MUST 保留用户、Application Publication、Capability Release和数据分级来源，且本变更 MUST NOT 新增定时清理执行。

#### Scenario: INTERNAL 查询完成
- **WHEN** 受治理Capability返回合法规范化结果并由Agent形成最终回复
- **THEN** 系统按既有成功生命周期保存结果与来源，不保存原始HTTP响应

#### Scenario: retention_days 已配置
- **WHEN** 会话策略含有 `retention_days`
- **THEN** 本变更继续只保存该值而不据此删除Capability结果

### Requirement: Job Tool Execution Snapshot must be immutable
系统 MUST 在 Job 创建后禁止修改其 Tool Release、Handler Version、Implementation Digest、Business Target Path、placement 集合、Resource Revision、Partition Policy 或 Loki Scope Policy；任何配置新版本都只能影响显式使用新 Application Publication 创建的新 Job。

#### Scenario: Resource rotates after job creation
- **WHEN** Job 已创建后 Resource Identity 发布了新 Revision
- **THEN** 原 Job、重试和 replay 继续引用冻结 Revision

#### Scenario: Operator attempts to edit snapshot
- **WHEN** 管理 API、恢复命令或数据库 repository 请求替换已有 Job 的精确绑定
- **THEN** 系统拒绝修改并记录审计，不提供普通 CRUD 覆盖路径

### Requirement: Retry and replay must use the original snapshot
所有自动重试、Outbox replay 和授权的显式恢复 MUST 使用原 Job Tool Execution Snapshot，并 MUST 重新检查冻结 Release 的当前可调用生命周期和精确实现可用性；不得解析 latest、replacement 或当前活动 Application Publication。

#### Scenario: Retry after application upgrade
- **WHEN** 原 Job 失败后应用切换到新的 Application Publication
- **THEN** 重试仍使用原 Publication 和全部冻结资源策略事实

#### Scenario: Frozen release is disabled
- **WHEN** 重试时冻结 Tool Release 已为 DISABLED
- **THEN** Job 以安全的非重试或隔离状态失败，不自动替换 Release

#### Scenario: Frozen implementation is missing
- **WHEN** 当前 Worker 缺少 Snapshot 中精确 Handler Version 或 Implementation Digest
- **THEN** Worker 不执行相似名称工具，并报告 MISSING/DRIFTED 运行错误

### Requirement: Tool Call must record the actual resolved placement and scope
每次 Tool Call SHALL 持久化实际选择的 placement、Resource Revision、Partition/Loki Policy revision、有效 selector 或 namespace 的安全 hash、授权判定和 correlation id，并 MUST NOT 保存 Secret 或无界业务响应。

#### Scenario: Cloud resource is selected
- **WHEN** Job 允许 cloud 和 edge，某次 Tool Call 明确解析到 cloud
- **THEN** Tool Call 记录 `cloud` 和其精确 Resource Revision，后续同 Job 的其它调用仍可独立解析允许的 placement

#### Scenario: No-placement resource is selected
- **WHEN** Job 使用没有 placement 维度的 Redis Resource
- **THEN** Tool Call 记录 placement 缺省而不是 `none` 或 `standalone`

### Requirement: Legacy recoverable jobs must be materialized or isolated before removal
在删除 `legacy-v1` 兼容读取前，系统 MUST 对所有非终态、待重试、可 replay 或可显式恢复的旧 Job 生成幂等迁移报告，并只在候选唯一且证据充分时物化精确 Tool Execution Snapshot；其它 Job MUST 被隔离。

#### Scenario: Legacy job can be uniquely resolved
- **WHEN** 原 Publication、代码 digest、资源绑定和策略能唯一确定精确事实
- **THEN** 迁移事务写入 Snapshot、内容 hash、迁移版本和证据摘要

#### Scenario: Legacy job is ambiguous
- **WHEN** 旧名称可对应多个 Release 或资源范围无法唯一还原
- **THEN** 迁移不猜测候选，将 Job 标记为不可重试/不可恢复并列入人工报告

#### Scenario: Historical terminal job remains
- **WHEN** 已终态且不可恢复的 Job 只包含 `legacy-v1` 历史字段
- **THEN** 系统保留其只读审计记录，但不得从该记录创建新执行

