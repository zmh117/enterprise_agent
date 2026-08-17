# execution-delivery Specification

## Purpose
定义 Agent Job、Runtime、队列、Outbox、重试、审计和结果投递的可靠执行契约，确保状态事实、幂等恢复与执行和投递分离保持一致。
## Requirements

<!-- Reconciled from mcp_new capability: `agent-job-debug-api` -->

### Requirement: 调试 API 必须能创建 Agent Job
系统 SHALL 提供受登录态保护的调试 Job 创建 API，用于在不依赖外部 Channel 的情况下创建只读诊断 Job，并复用业务应用发布、严格 RBAC、审计、持久化和 Outbox 链路。API MUST 使用当前登录用户，且只接受该用户有权使用的已发布业务应用、Execution Scope、消息和幂等键。

#### Scenario: 当前用户提交调试问题
- **WHEN** 已登录用户具备 `agent.debug.execute`，并选择有权访问的业务应用发布和 Execution Scope
- **THEN** 系统以当前用户身份创建隔离 Session、Agent Job、用户消息、授权快照、审计和 Job Dispatch Outbox，并返回 `job_id`

#### Scenario: 请求试图覆盖运行身份或资源
- **WHEN** 调试请求提交任意 `user_id`、Agent ID、Resource Revision、Connector 或自定义 reply route
- **THEN** 系统必须拒绝这些越权字段，且不得创建 Job 或 Outbox event

#### Scenario: 调试 API 使用幂等键
- **WHEN** 同一用户在同一发布版本和 Execution Scope 下两次提交相同 `idempotency_key`
- **THEN** 系统返回同一个 `job_id`，且不重复创建 Job 或 Outbox event

### Requirement: 调试 API 必须执行权限校验
系统 SHALL 在创建调试 Job 前校验登录态、`agent.debug.execute`、业务应用角色、应用发布可用性和 Execution Scope；任一授权缺失都必须 fail closed。

#### Scenario: 授权用户创建任务
- **WHEN** 当前用户拥有调试权限、目标应用角色和目标 Execution Scope
- **THEN** 系统创建并通过 Outbox 调度 Agent Job

#### Scenario: 未授权用户被拒绝
- **WHEN** 当前用户缺少任一所需权限或范围
- **THEN** 系统返回安全拒绝，且不创建 Session、Job、消息或 Outbox event

### Requirement: Job 查询 API 必须返回任务详情
系统 SHALL 提供 `GET /api/agent/jobs/{job_id}`，返回 Agent job 的可审计详情。

#### Scenario: 查询已存在任务
- **WHEN** 调用 `GET /api/agent/jobs/{job_id}` 查询已存在 job
- **THEN** 系统返回 job id、session id、user id、project code、source、user message、status、retry count、result、error message 和时间戳

#### Scenario: 查询不存在任务
- **WHEN** 调用 `GET /api/agent/jobs/{job_id}` 查询不存在 job
- **THEN** 系统返回 404 或等价的 not found 响应

### Requirement: Step 查询 API 必须返回执行步骤
系统 SHALL 提供 `GET /api/agent/jobs/{job_id}/steps`，按创建顺序返回该 job 的可审计执行步骤。

#### Scenario: 查询任务步骤
- **WHEN** job 已经被 worker 执行并产生 `agent_step`
- **THEN** 系统返回步骤列表，包含 step type、title、content 和 created at

### Requirement: Tool Call 查询 API 必须返回安全摘要
系统 SHALL 提供 `GET /api/agent/jobs/{job_id}/tool-calls`，返回工具调用的脱敏请求摘要、响应摘要、状态、耗时、风险等级和审计关联。

#### Scenario: 查询工具调用
- **WHEN** job 执行过程中产生 `agent_tool_call`
- **THEN** 系统返回工具调用列表，且响应 MUST 不包含未脱敏 raw payload

### Requirement: 调试 API 必须支持本地 curl 验证
系统 SHALL 在 README 或等价文档中提供本地 curl 验证步骤，覆盖创建 job、轮询 job 状态、查询 steps 和查询 tool calls。

#### Scenario: 文档化 curl 验证
- **WHEN** 开发者按文档启动 Docker Compose 并执行 curl 命令
- **THEN** 开发者可以观察到 job 从 `PENDING` / `RUNNING` 变为 `SUCCEEDED`，并看到最终报告、步骤和工具调用摘要

### Requirement: 失败 job 的 tool-calls 必须包含真实运行时已发生工具调用
系统 SHALL 在真实 Claude runtime 失败、timeout、最大轮次耗尽或被 retry service 重新入队后，仍通过 `GET /api/agent/jobs/{job_id}/tool-calls` 返回失败前已经发生并被持久化的工具调用安全摘要。

#### Scenario: 最大轮次耗尽后查询工具调用
- **WHEN** 一个真实 Claude job 因最大轮次耗尽失败并进入 FAILED 或 retry-pending 状态
- **THEN** 调试 API 返回该次执行中已经发生的数据库、Redis、Loki 或 schema directory 工具调用摘要

#### Scenario: retry-pending 状态保留上次失败证据
- **WHEN** job 被 retry service 重新置为 `PENDING` 且保留上次 `error_message`
- **THEN** `GET /tool-calls` 仍返回上次执行失败前的工具调用摘要，便于开发者判断是否应继续重试

#### Scenario: 失败工具调用摘要仍然脱敏
- **WHEN** 失败路径持久化工具调用
- **THEN** 调试 API 返回的请求和响应摘要不得包含密钥、完整 raw payload、私有推理或未受限上游错误正文

### Requirement: Debug API documentation shall cover real-tools verification
系统 SHALL 在调试 API 文档中提供 real-tools 验证流程，覆盖创建 job、轮询状态、查询 steps、查询 tool-calls，并说明如何确认工具调用来自 `internal-api-platform`。

#### Scenario: 查询 real-tools tool calls
- **WHEN** 开发者按 real-tools 文档提交 debug job
- **THEN** `GET /api/agent/jobs/{job_id}/tool-calls` SHALL 返回工具名称、状态、耗时、风险等级、脱敏请求摘要、响应摘要和 metadata source

#### Scenario: 工具链失败排查
- **WHEN** debug job 失败
- **THEN** 文档 SHALL 指引开发者检查 job 状态、worker 日志、tool-calls、Internal API Platform health 和 Loki 诊断 endpoint

### Requirement: Debug jobs shall support safe real-model smoke testing
系统 SHALL 支持使用 debug API 提交真实模型 smoke test，但测试流程 MUST 明确要求使用合成问题、合成日志或脱敏证据。

#### Scenario: 提交安全真实模型测试任务
- **WHEN** 开发者启用 `FEATURE_REAL_CLAUDE=true` 并提交 debug job
- **THEN** 文档化流程 SHALL 使用合成或已脱敏测试问题
- **AND** job steps/tool-calls 可用于确认模型调用了 real-tools 工具链

### Requirement: Debug API shall prove smoke job execution
系统 SHALL 在 compose smoke 流程中使用 Debug API 创建 Agent job，并通过 job detail、steps 和 tool-calls 查询证明 worker 已消费并完成任务。

#### Scenario: Smoke creates and polls job
- **WHEN** 开发者调用 `POST /api/agent/jobs` 提交合成诊断问题
- **THEN** API SHALL 返回 `job_id`，并且文档 SHALL 指引开发者轮询 `GET /api/agent/jobs/{job_id}` 直到 `SUCCEEDED` 或明确失败状态

#### Scenario: Smoke inspects steps and tool calls
- **WHEN** job 进入终态
- **THEN** 开发者 SHALL 能调用 `GET /api/agent/jobs/{job_id}/steps` 和 `GET /api/agent/jobs/{job_id}/tool-calls` 查看可审计摘要

### Requirement: Debug smoke documentation shall include failure triage
系统 SHALL 在 smoke 文档中记录失败排查顺序，覆盖 job detail、worker logs、RabbitMQ 消费、runtime config degraded、secret 状态和 Internal API Platform 健康状态。

#### Scenario: Smoke job fails
- **WHEN** smoke job 返回 `FAILED`、`TIMEOUT` 或长时间停留在 `PENDING`
- **THEN** 文档 SHALL 提供 curl/docker compose 命令定位失败发生在 API 接收、RabbitMQ、worker、Claude runtime、secret resolver 或 internal tools 哪一段

### Requirement: 调试查询必须受当前用户授权
Job、Step 和 Tool Call 查询 MUST 要求登录，并仅允许 Job 创建人、具备该业务应用运维权限的用户或平台管理员访问；响应必须继续脱敏。

#### Scenario: 用户查询其他应用的调试 Job
- **WHEN** 当前用户不是创建人且没有目标应用运维权限
- **THEN** 系统必须拒绝查询，并且不得泄露 Job 是否存在的敏感细节

### Requirement: 运行中心必须提供受限调试入口
前端 SHALL 提供“运行中心 → 发起调试”，只列出当前用户可用的已发布业务应用与 Execution Scope；默认 Delivery 为 none，可选 Delivery 必须来自现有已授权 binding。

#### Scenario: 用户成功发起调试
- **WHEN** 用户选择允许的应用、范围并提交消息
- **THEN** 页面创建 Job 后导航到受保护的 Job 详情页

#### Scenario: 用户选择可选投递
- **WHEN** 用户选择当前应用发布已有的授权 Delivery binding
- **THEN** 系统固化该 binding；页面不得允许填写任意 Connector 或目标地址

<!-- Reconciled from mcp_new capability: `agent-job-lifecycle` -->

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

<!-- Reconciled from mcp_new capability: `claude-agent-runtime-integration` -->

### Requirement: Real runtime is implemented with the Claude Agent SDK
系统 SHALL 在独立 TypeScript `agent-runtime` 服务中使用官方 `@anthropic-ai/claude-agent-sdk` 执行 `typescript-v1` Agent loop，并 SHALL 长期保留现有 Python Claude Agent SDK 作为 `python-v1` 执行路径。公共编排层 SHALL 只依赖语言无关的 `AgentRunResult`/Runtime client 契约；每条 Runtime 的 SDK 类型不得泄漏到公共 Job 编排逻辑。

#### Scenario: TypeScript Runtime驱动Agent loop
- **WHEN** `AgentExecutor` 执行一个固定为 `typescript-v1` 且配置有效的 Job
- **THEN** Python Runtime client 调用 TypeScript Runtime，由 Runtime 消费 SDK message stream 并返回规范最终结果

#### Scenario: SDK类型不泄漏到Python应用层
- **WHEN** Python `AgentExecutor` 调用路由 Runtime client
- **THEN** 公共编排逻辑只处理 Runtime client 契约和 `AgentRunResult`，不直接处理 TypeScript SDK 类型或 Python `claude_agent_sdk` 消息类型

#### Scenario: Python Runtime长期保留
- **WHEN** 新 Job 未命中任何显式 TypeScript 环境或 Application Publication 门禁
- **THEN** Job 固定为 `python-v1` 并由现有 Python Claude Agent SDK 路径执行
- **AND** TypeScript 灰度或 E2E 完成不得自动删除、禁用或降级 Python Runtime

### Requirement: Real runtime is selectable via feature flag
系统 SHALL 通过显式环境/Application 门禁与不可变 Job Runtime 快照选择 `python-v1` 或 `typescript-v1`。未命中 TypeScript 门禁时 MUST 默认选择 `python-v1`；同一 attempt 和 retry MUST 使用冻结 Runtime，且在 Runtime 故障时 MUST NOT 自动跨实现 fallback。测试容器默认继续使用 stub，除非测试显式注入 Runtime client。

#### Scenario: 默认选择Python Runtime
- **WHEN** 新 Job 没有命中显式 TypeScript 门禁
- **THEN** 系统把 `python-v1` 和协议版本固定到 Job

#### Scenario: 指定Application使用TypeScript Runtime
- **WHEN** 测试 Application 的已发布配置固定 `typescript-v1`
- **THEN** 新 Job 和其所有 retry 均调用 TypeScript Runtime

#### Scenario: TypeScript Runtime不可用
- **WHEN** 固定为 `typescript-v1` 的 attempt 无法连接 Runtime
- **THEN** 系统按稳定错误分类进入本地 retry/终态流程，不自动改用 Python SDK

#### Scenario: 本地测试保持Stub
- **WHEN** 单元测试构建测试 Container 且未覆盖客户端
- **THEN** `AgentExecutor` 使用 stub，不需要模型凭据、Node 服务或外部网络

### Requirement: Anthropic credentials and CLI runtime are validated before execution
系统 SHALL 在所选 Runtime 内按 Job 固定模型连接解析 Anthropic 兼容凭据，并验证该 Runtime 所需 SDK/CLI；`agent-worker` MUST 不持有 provider 明文凭据或 Claude Code CLI。缺少凭据、SDK 或 CLI MUST 返回安全、不可重试的配置错误。

#### Scenario: 缺少API key
- **WHEN** 所选 Runtime 无法解析 Job 固定 Credential binding 的 active Secret
- **THEN** 执行在调用模型前以不可重试配置错误失败且安全通知不包含 Secret

#### Scenario: Python Runtime缺少CLI
- **WHEN** Python Claude Agent SDK 无法定位其所需 CLI runtime
- **THEN** Python Runtime 返回不可重试依赖错误而不无限重试

#### Scenario: Worker镜像检查
- **WHEN** 部署检查纯 Worker 镜像
- **THEN** 其中不存在 provider 明文凭据注入、任一 Agent SDK 或 Claude Code CLI

### Requirement: Read-only tools are exposed only through the deployment-fixed standard MCP server
系统 SHALL 让两个独立Runtime通过部署固定的标准`tool-mcp`访问Job冻结的只读MCP Tool，并通过部署固定的`file-service` File MCP接口访问Job冻结的任务文件工具。Runtime MUST NOT注册旧Capability Tool、接受任意Server URL、在Tool不可用时fallback或把文件工具路由到`tool-mcp`。`tool-mcp`继续使用非认证Job绑定传输；File MCP MUST使用平台短时Principal JWT并在服务端复核主体、Job、Publication、scope和任务工作区。

#### Scenario: Python Runtime调用允许的只读Tool
- **WHEN** Python SDK调用Job精确允许的只读MCP Tool
- **THEN** 调用通过标准MCP SDK进入部署固定`tool-mcp`并返回安全结果

#### Scenario: TypeScript Runtime调用允许的文件Tool
- **WHEN** TypeScript SDK调用Job精确允许的File MCP Tool
- **THEN** 调用只进入部署固定`file-service`且携带不含下游Secret的Principal JWT

#### Scenario: Tool上下文按Job隔离
- **WHEN** 两个Runtime并发调用相同只读或文件Tool
- **THEN** 每次调用使用各自Job、Publication和scope且不共享模型或MinIO凭据

#### Scenario: 模型提供任意MCP地址
- **WHEN** 请求内容或模型输出尝试注册未冻结MCP Server URL或Tool
- **THEN** Runtime与服务端失败关闭

#### Scenario: 旧平台对象被配置
- **WHEN** 启动或执行配置包含旧Capability、Handler、Resource Mapping、Internal API Token、`RUNTIME_TOOL_MCP_*`或HS256 signing key
- **THEN** 部署预检失败且不启动兼容模式

### Requirement: Built-in mutating tools are disabled
系统 SHALL 继续禁止SDK的Bash、NotebookEdit、WebFetch、WebSearch、Shell、部署、数据库写入和其它开放执行工具。只有启用任务文件工作区且Job冻结精确File MCP Tool时，Runtime MAY向Claude Code开放`Read`、`Glob`、`Grep`、`Write`和`Edit`，并 MUST 把目标限制到当前Job Sandbox、拒绝路径穿越与符号链接逃逸。`Glob`只能使用沙盒内相对TXT pattern，且必须拒绝绝对路径、`..`、符号链接、非TXT pattern和未知字段。文件系统修改只改变本地副本，必须经File Service显式提交才能形成文件版本。

模型可见路径和模型提交的路径 MUST 保持为安全相对路径。若Claude Code CLI在进入`canUseTool`前把该相对路径解析为基于`cwd`的绝对路径，Runtime MAY 只在该绝对路径词法上属于本次随机Job Sandbox根、规范化后仍位于允许顶层且通过符号链接与常规文件检查时，把它还原为相对路径继续授权；沙盒外绝对路径、相邻前缀路径和模型可见绝对路径能力 MUST 继续拒绝。

#### Scenario: Model attempts Bash or Web tool
- **WHEN** SDK尝试调用Bash、WebFetch、WebSearch或NotebookEdit
- **THEN** 该工具不可用或调用被拒绝

#### Scenario: Model edits inside the Job Sandbox
- **WHEN** 已授权文件Job调用`Write`或`Edit`且规范化目标位于当前Job Sandbox
- **THEN** Runtime允许本地文件操作并保留有界工具结果
- **AND** 不直接写MinIO或创建文件版本

#### Scenario: SDK在权限回调前解析相对路径
- **WHEN** 模型调用`Write`使用安全相对TXT路径且Claude Code CLI向`canUseTool`提供基于当前`cwd`解析的绝对路径
- **THEN** Runtime验证该路径精确属于本次Job Sandbox并将其还原为允许顶层下的相对路径后批准
- **AND** 真实CLI测试证明`canUseTool`被调用且文件实际写入本次沙盒

#### Scenario: Model edits outside the Job Sandbox
- **WHEN** `Write`或`Edit`目标离开当前Job Sandbox或Job未冻结文件工具
- **THEN** Runtime在副作用前拒绝

#### Scenario: Only current MCP and sandbox set is exposed
- **WHEN** Application Publication只选择一个MCP Tool
- **THEN** 只有该Tool可进入MCP可调用集合，且只有文件Job所需的五个受限本地文件工具可进入SDK `tools`可用集合
- **AND** `allowedTools`/`allowed_tools`保持为空，所有调用仍经过`canUseTool`逐次校验

#### Scenario: Application has no Tool
- **WHEN** Application MCP Tool子集为空
- **THEN** 不注册或批准任何平台Tool或本地文件修改工具

### Requirement: Execution is bounded by turns and wall-clock time
系统 SHALL 使用 Job 固定的有效执行策略限制真实 Claude Agent 执行的 SDK 最大轮次、单次 attempt 墙钟时间和内部工具调用次数。所有进入 Worker 的 Job MUST 具有合法的当前 Execution Policy 快照；Worker MUST NOT 对缺失或不支持的策略使用 `AGENT_MAX_TURNS`、`AGENT_TIMEOUT_SECONDS` 或 Agent Publication 进行运行时 fallback。

#### Scenario: Execution exceeds configured timeout
- **WHEN** SDK session 超过 Job 有效 `timeout_seconds`
- **THEN** 运行时取消当前 session，保留已有安全工具事件并抛出安全 timeout 错误

#### Scenario: Execution reaches maximum turns
- **WHEN** SDK session 达到 Job 有效 `max_turns` 且没有有效最终结果
- **THEN** 运行时按最大轮次耗尽分类结束执行
- **AND** 不把该错误仅作为普通 transport transient 立即重试

#### Scenario: Execution reaches maximum tool calls
- **WHEN** 当前 Agent attempt 已经执行 Job 有效 `max_tool_calls` 次内部工具调用
- **THEN** 内部 MCP 工具桥拒绝下一次调用且不进入 ToolRegistry
- **AND** 运行时返回稳定、非瞬时的策略耗尽错误并保留此前工具事件

#### Scenario: Job缺少执行策略
- **WHEN** Job 没有 Execution Policy 快照、schema version 不受支持或有效字段不完整
- **THEN** Worker 在调用 Claude SDK 前以不可重试的完整性错误停止
- **AND** 不调用模型或任何内部工具

### Requirement: SDK failures are classified for retry policy
系统 SHALL 根据结构化语义分类 Claude Agent SDK/CLI 故障：网络、429/5xx、transport、CLI JSON decode 和可确认的瞬时 provider 故障映射为可重试；缺少凭据、CLI 不存在、明确无效模型配置和工具策略拒绝映射为不可重试；矛盾的 error result MUST 使用独立错误码并只允许受最大次数约束的有限重试。

#### Scenario: Transient process error triggers retry
- **WHEN** SDK 返回网络、rate limit、overloaded、transport 或 CLI JSON decode 瞬时错误
- **THEN** runtime 抛出带稳定错误码的 `RetryableExecutionError`，由 Job retry service 延迟调度

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
- **WHEN** 工具调用因为 SQL policy、只读边界或权限被拒绝
- **THEN** runtime 将安全拒绝结果返回模型或终止本次执行，不将其误分类为 SDK transport retry

### Requirement: Tool events are returned without private reasoning
The system SHALL populate `AgentRunResult.tool_events` with safe summaries of each internal or governed Tool invocation, attempt outcome, result size and applicable Capability Release/classification provenance, excluding raw secrets, authentication material, raw HTTP bodies, full unbounded payloads and private model chain-of-thought including SDK thinking blocks.

#### Scenario: Successful tool loop produces events
- **WHEN** the real runtime completes after one or more internal or governed Tool calls
- **THEN** `AgentRunResult` includes ordered safe Tool event summaries suitable for persistence in `agent_tool_call`

#### Scenario: Governed call fails after HTTP attempts
- **WHEN** a QUERY Capability exhausts its allowed attempts
- **THEN** the event summary includes safe classification and attempt count without including external body, Token or authentication Header

### Requirement: Health endpoints report runtime mode without invoking Claude
系统 SHALL 聚合所选 Runtime 模式、TypeScript Runtime readiness、协议/SDK 版本和必要依赖的脱敏状态。健康与就绪检查 MUST NOT 调用 Claude、模型 Provider 或业务 MCP Tool。

#### Scenario: Python默认模式
- **WHEN** `/api/ready` 在默认双 Runtime 配置下被调用
- **THEN** 响应报告默认 Runtime 为 `python-v1` 及 TypeScript Runtime 可用性，但不调用模型

#### Scenario: TypeScript Runtime缺少配置
- **WHEN** TypeScript Runtime 被启用但 Grant、模型连接、Master Key 文件或依赖未就绪
- **THEN** readiness 失败关闭并返回脱敏原因

### Requirement: 失败路径必须保留真实运行时工具事件
系统 SHALL 在真实 Claude SDK 执行失败、超时或达到最大轮次时，保留失败前已经发生的工具调用安全摘要，并将这些摘要交给应用层持久化。工具事件 MUST 不包含私有推理、密钥、未脱敏 raw payload 或不受限响应正文。

#### Scenario: 最大轮次耗尽后保留工具轨迹
- **WHEN** `RealClaudeCodeAgentClient.run()` 在一个已经调用过内部工具的 job 中收到 `Reached maximum number of turns` 类错误
- **THEN** 系统持久化失败前已收集的工具调用摘要，并在 job step 中记录安全失败原因

#### Scenario: SDK timeout 后保留工具轨迹
- **WHEN** 真实 SDK 会话超时且超时前已经调用过内部工具
- **THEN** 系统持久化已完成或已失败的工具调用摘要，并继续按 timeout 错误分类处理 job

### Requirement: 最大轮次耗尽必须区别于瞬时传输故障
系统 SHALL 将明确的工具循环最大轮次耗尽识别为诊断循环收敛失败，而不是普通网络、CLI transport 或上游 5xx 瞬时故障。该错误 MUST 带有安全错误码或等价分类，供 retry 策略避免立即重复消耗同一无效工具循环。

#### Scenario: 最大轮次耗尽不作为普通 transient 重试
- **WHEN** Claude SDK 返回明确的 `Reached maximum number of turns` 错误
- **THEN** job 不得仅因为该错误被当作普通 transient transport failure 立即重复重试

#### Scenario: 网络错误仍可重试
- **WHEN** Claude SDK 返回网络超时、429、502、503、transport connection 或 CLI JSON decode transient 错误
- **THEN** 系统仍按现有 retryable 语义处理该故障

### Requirement: Claude runtime can load model settings from DB-backed runtime config
系统 SHALL 允许真实 Claude/DeepSeek runtime 从 DB-backed runtime config 加载 base URL、model、默认模型、effort level、max turns 和 timeout，并保留 env fallback。

#### Scenario: DB config selects DeepSeek model
- **WHEN** runtime config 配置 `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic` 和 `ANTHROPIC_MODEL=deepseek-v4-pro[1m]`
- **THEN** RealClaudeCodeAgentClient 使用 DB-backed 配置构造 SDK runtime

#### Scenario: DB config missing
- **WHEN** DB-backed Claude runtime config 不存在
- **THEN** runtime 使用现有 env/default 逻辑，并在 ready 输出中标记来源

### Requirement: Claude runtime API key can use Web-managed secret
系统 SHALL 允许 `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` 通过 Web-managed secret ref 配置，并且 ready/health 只能报告是否 configured，不能泄漏 key。

#### Scenario: API key is stored as secret ref
- **WHEN** runtime config 将 `ANTHROPIC_API_KEY` 指向 `secret://platform/deepseek_api_key`
- **THEN** RealClaudeCodeAgentClient 仅在调用 SDK 前解析 secret，日志和 ready 输出不包含明文 key

#### Scenario: API key secret is missing
- **WHEN** `FEATURE_REAL_CLAUDE=true` 但 API key secret 无法解析
- **THEN** ready 或执行前校验返回安全配置错误，不调用外部模型 API

### Requirement: Claude runtime DB-backed settings shall be smoke-verifiable
系统 SHALL 提供 smoke 流程，分别验证 Python 与 TypeScript Runtime 的 base URL、model、max turns 和 API key Secret ref 能从 Job 固定模型连接进入所选 Runtime，而不是进入 `agent-worker`。

#### Scenario: Fake Runtime验证配置投影
- **WHEN** 默认 smoke 使用 fake provider 且不启用真实外部调用
- **THEN** 流程仍能验证 Job 固定模型连接被正确投影到两个 Runtime 请求，并确认 Worker 不接收明文 Key

#### Scenario: 可选真实Runtime使用Secret ref
- **WHEN** 开发者显式选择一个 Runtime、提供有效 Secret ref 并启用真实 smoke
- **THEN** 对应 Runtime 在执行前解析 active Secret，ready/job/debug 输出不包含明文 Key

### Requirement: Real-model smoke shall fail safely when credentials are invalid
系统 SHALL 在真实 DeepSeek/Claude smoke 中，当 API key 缺失、禁用或仍为占位符时，返回安全配置错误并避免无限重试。

#### Scenario: API key secret is disabled before job execution
- **WHEN** `FEATURE_REAL_CLAUDE=true` 且 runtime config 指向 disabled secret
- **THEN** Agent job SHALL 失败为安全配置错误，且 debug API SHALL 提供可排查的 job/error 信息但不泄漏 key

### Requirement: Claude runtime consumes the job-fixed Agent publication
系统 SHALL 在执行 job 时读取 job 固定的不可变 Agent publication snapshot，并 MUST 使用其中的业务指令、模型策略、执行限制、Skill 和允许工具配置。runtime MUST NOT 读取活动草稿或执行时重新选择当前发布版本。

#### Scenario: Job executes published configuration
- **WHEN** worker 执行固定了默认诊断 Agent publication 的 job
- **THEN** AgentContextBuilder 和 RealClaudeCodeAgentClient 使用该 snapshot 构建运行上下文

#### Scenario: Publication changes during execution
- **WHEN** 管理员在 job 运行期间发布新版本
- **THEN** 当前 job 继续使用固定 snapshot，新版本不改变本次 prompt、工具或执行限制

### Requirement: 可编辑业务指令不能覆盖强制安全规则
系统 SHALL 把 publication 中的业务指令作为受控配置层，并 MUST 在其外层强制叠加平台安全规则、只读工具限制、数据权限和 SDK 内置写工具禁用。

#### Scenario: 业务指令包含越权文本
- **WHEN** 已发布业务指令要求忽略权限、执行 Bash、修改数据库或泄漏 secret
- **THEN** runtime 拒绝无效 publication 或保持平台安全规则优先，且不执行越权动作

### Requirement: Agent publication 只能引用已注册模型策略
系统 SHALL 允许 Agent publication 选择已注册且启用的模型策略与执行参数，但 MUST NOT 在 Agent snapshot 中保存 API key、认证 token、任意 secret 明文或不受管 provider URL。

#### Scenario: 默认 Agent 选择模型策略
- **WHEN** 管理员为默认 Agent 选择一个引用 DB-backed runtime config/secret 的模型策略
- **THEN** publication 保存非敏感策略引用，runtime 在基础设施层解析实际凭证

### Requirement: Claude 错误诊断元数据必须有界、脱敏且可关联
系统 SHALL 为真实 Claude/DeepSeek 失败记录可关联 Job 的安全诊断元数据，至少包括稳定错误码、异常类、SDK/CLI 版本、模型策略引用、provider host 安全摘要、脱敏 subtype/errors 和有界 stderr；系统 MUST NOT 持久化凭据、完整敏感 URL、完整 prompt、未受限工具结果或私有推理。

#### Scenario: Inconsistent SDK result is audited
- **WHEN** runtime 识别 `claude_inconsistent_result`
- **THEN** 审计记录 Job、correlation ID、SDK/CLI 版本、模型策略引用、脱敏错误标志和稳定错误码，不记录 API key、认证 token 或 chain-of-thought

#### Scenario: CLI stderr contains credentials
- **WHEN** CLI stderr 包含 API key、authorization header、token 或带 secret/query 的 URL
- **THEN** 系统在写入 Job step、error message 或审计前屏蔽凭据并截断到配置上限

### Requirement: 真实模型兼容性 smoke 必须显式启用且使用安全输入
系统 SHALL 提供显式 opt-in 的真实模型 smoke，用合成或已脱敏问题对照 provider/model/SDK 组合；常规单元测试、Compose 启动和 readiness MUST NOT 自动调用外部模型。

#### Scenario: 常规测试运行
- **WHEN** 开发者运行默认测试或启动 readiness
- **THEN** 系统使用 fake/stub 或仅报告配置状态，不产生外部模型请求和费用

#### Scenario: 开发者显式运行对照 smoke
- **WHEN** 开发者提供明确开关和凭据并选择当前 DeepSeek 配置与基线配置
- **THEN** smoke 使用 synthetic prompt，分别记录成功或安全错误分类，不输出凭据和完整 provider 响应

### Requirement: 真实Runtime必须使用Job固定的模型连接
系统 SHALL 让 `AgentExecutor` 和 `RealClaudeCodeAgentClient` 从 Job 固定的 Agent Publication 获取模型连接 revision、config hash、Base URL、模型映射、Subagent 模型、effort 和 Credential 绑定。Worker MUST NOT 为包含模型连接快照的新 Publication 重新读取 Agent 当前发布指针或用进程启动时的全局模型 URL、模型和 Key 覆盖该快照。

#### Scenario: Job排队后发布新模型连接
- **WHEN** Job 已固定 Agent Publication 后管理员发布使用不同 Base URL 或模型的新 Agent Publication
- **THEN** 已排队 Job 和其重试继续使用原固定模型连接 revision
- **AND** 新 Job 才使用新 Agent Publication 的模型连接

#### Scenario: Publication模型连接hash不匹配
- **WHEN** Worker 读取到的模型连接 revision 与 Agent Publication 固定的 config hash 不一致
- **THEN** Job 在调用 Claude Agent SDK 前以不可重试完整性错误失败
- **AND** 不解析 Key、不启动 CLI、不调用模型或工具

### Requirement: Runtime必须安全解析并隔离每次执行的模型环境
系统 MUST 在每次 Agent attempt 开始时解析固定模型连接绑定的 active Secret，并把规范化字段映射为 Claude Agent SDK/CLI 所需的 Anthropic Base URL、API Key/Auth Token、主模型、默认模型、Subagent 模型和 effort。不同 Job 的模型环境 MUST 隔离，MUST NOT 通过无保护的进程全局环境产生跨 Job URL、模型或 Key 串用。

#### Scenario: 两个Job使用不同模型连接
- **WHEN** 同一 Worker 先后或并发处理固定到不同模型连接的 Job
- **THEN** 每个 SDK session 只继承自己的 Base URL、模型映射、effort 和 Key
- **AND** 任一 Job 的配置不会残留到另一个 Job

#### Scenario: Active Key被轮换
- **WHEN** Job 已固定 Credential 绑定，但该 Credential 在 attempt 开始前完成安全轮换
- **THEN** Worker 使用新的 active Secret 版本
- **AND** Job 的 Base URL、模型映射和 Agent Publication provenance 保持不变

### Requirement: 旧Agent Publication保留受控兼容路径
系统 SHALL 允许迁移前没有模型连接 revision 的现有 Agent Publication 继续使用既有 DB-backed runtime config/env fallback，并 MUST 在管理 API 和 Web 将其标记为 legacy global connection。所有本变更实施后新建的 Agent Publication MUST 固定模型连接，不得继续创建新的隐式全局连接 Publication。

#### Scenario: 现有业务应用引用旧Publication
- **WHEN** 已激活 Business Application 仍引用迁移前 Agent Publication
- **THEN** Runtime 继续使用现有 DB-backed 全局模型配置执行该 Job
- **AND** 管理端提示需要重新发布 Agent 并在业务应用中显式切换

#### Scenario: 发布新Agent草稿
- **WHEN** 管理员在本变更上线后发布 Agent 草稿
- **THEN** 发布校验要求草稿引用有效模型连接 revision
- **AND** 缺失连接时不得退回全局配置创建新 Publication

### Requirement: 模型运行记录必须只展示安全Provenance
系统 SHALL 在 Agent Job、运行记录和安全诊断中保存 Agent Publication、模型连接 revision/config hash、模型、effort 和脱敏 Provider Host，并 MUST NOT 持久化 API Key、Auth Token、Secret ref、完整 Base URL 查询参数、Prompt 或模型原始响应。

#### Scenario: 查看成功Job
- **WHEN** 管理员查看由新 Agent Publication 执行成功的 Job
- **THEN** 运行记录展示模型、Provider Host、模型连接 revision 和 Agent Publication
- **AND** 不提供任何能够恢复 Credential 的字段

#### Scenario: Provider认证失败
- **WHEN** Claude Agent SDK 因 Key 无效返回认证错误
- **THEN** Job 记录稳定安全错误码和脱敏 Provider Host
- **AND** 日志、审计和原会话失败投递不包含 Key、请求头或上游响应正文

### Requirement: 模型可以组合公开的 Capability 输入输出
Claude Tool循环 SHALL 能读取一个受治理Capability的规范化公开输出，并依据后续Capability的公开Input Schema组织新的结构化调用；每次调用必须独立经过当前Job的Tool可见性与执行校验，运行时不得创建隐式服务端Handler流水线。

#### Scenario: 顺序调用两个测试 Capability
- **WHEN** 模型使用第一个Tool的规范化字段构造第二个Tool输入
- **THEN** SDK循环执行两个独立Tool调用并分别产生安全Tool事件

#### Scenario: 后续 Tool 不在当前目录
- **WHEN** 模型尝试根据文本调用未注册的 `cap__*` Tool
- **THEN** SDK权限策略拒绝该调用且不发起外部请求

### Requirement: 外部规范化文本不得提升为指令
运行时 MUST 将受治理 Capability 的字符串输出标记和封装为不可信业务数据，不得把它拼接进 system/developer/Tool定义或据此修改 `allowed_tools` 和权限策略。

#### Scenario: Tool 输出包含提示注入
- **WHEN** 外部字段内容声称自己是系统指令或要求调用被禁用Tool
- **THEN** 内容保持普通Tool数据，系统提示、Tool集合和权限不发生变化

### Requirement: 不可用 Capability 使用独立安全提示通道
运行时 MUST 将受治理 Capability 的调用资格与模型解释事实分离：不满足当前发送者 Provider 身份前置条件的 Capability MUST 保持未注册、未批准，同时 MAY 仅在该 Capability 已属于精确 Agent/Application 发布交集时，以固定白名单文案向模型说明当前 Job 的不可用状态。提示 MUST NOT 复用原始异常，不得包含用户、Team、Connection、Credential、Release 或认证材料，也不得被模型视为可调用 Tool。

#### Scenario: 当前发送者缺少 ONES 前置条件
- **WHEN** 当前应用已发布 ONES Capability，但 Job 没有可用外部主体快照或当前绑定复核失败
- **THEN** 系统提示模型说明“该能力对当前发送者暂不可用”并给出“我的外部身份”自助绑定、重新验证、选择 default Team 和重新发送请求的安全操作提示，且不得声称平台全局未注册 ONES Tool

#### Scenario: 安全提示不扩大 Tool 权限
- **WHEN** 系统提示中存在某个 Capability 的 `unavailable` 事实
- **THEN** 该 Capability 不进入 MCP Server、`allowed_tools` 或 Tool 自动批准集合，模型也不得声称已经调用或验证其连通性

<!-- Reconciled from mcp_new capability: `claude-diagnostic-runtime` -->

### Requirement: AgentExecutor runs persisted diagnostic jobs
The system SHALL provide an AgentExecutor that accepts an Agent job identifier, loads persisted job context, executes the read-only diagnostic workflow, records execution output, and updates job status.

#### Scenario: Worker executes pending job
- **WHEN** the worker passes a valid PENDING job identifier to AgentExecutor
- **THEN** AgentExecutor loads the job, marks it RUNNING, invokes the diagnostic runtime, records the final result, and marks the job SUCCEEDED or FAILED

### Requirement: Claude Code Agent SDK is wrapped behind a client
The system SHALL isolate Claude Agent SDK usage behind a ClaudeCodeAgentClient contract so domain and application services do not depend on concrete SDK APIs. When `FEATURE_REAL_CLAUDE=true`, the default injected implementation SHALL be `RealClaudeCodeAgentClient` backed by the Claude Agent SDK; otherwise the system SHALL use `StubClaudeCodeAgentClient`.

#### Scenario: AgentExecutor invokes Claude runtime
- **WHEN** AgentExecutor needs model execution
- **THEN** it calls ClaudeCodeAgentClient with structured prompt, context, skills, tool registry, and execution limits instead of using SDK APIs directly

#### Scenario: Real runtime uses the SDK internally
- **WHEN** `RealClaudeCodeAgentClient.run()` is invoked with a valid API key and CLI runtime
- **THEN** only the infrastructure client module calls Claude Agent SDK APIs and AgentExecutor remains unaware of SDK types

### Requirement: Agent context is constructed before model execution
The system SHALL construct an Agent execution context containing system role, safety rules, user question, source/project or service code, allowed tools, tool restrictions, skills, relevant retrieved context, and safe conversation summary.

#### Scenario: Diagnostic question is prepared
- **WHEN** AgentExecutor prepares a job for Claude execution
- **THEN** AgentContextBuilder returns a context that includes read-only safety rules and excludes unrelated full ER/business-flow exports

### Requirement: Skills are loaded as explicit diagnostic workflows
The system SHALL load only configured diagnostic Skills for MVP, including bug analysis, SQL diagnosis, Redis diagnosis, and Loki log analysis. The real runtime SHALL inject loaded skill guidance into the SDK system prompt (or equivalent settings) so the agent follows the configured diagnostic workflows.

#### Scenario: Skills are registered
- **WHEN** the Agent runtime starts a diagnostic job
- **THEN** it registers the configured Skills with ClaudeCodeAgentClient and makes their workflow guidance available to the Agent

### Requirement: Runtime exposes only read-only tools
系统 SHALL 默认只注册Job冻结的只读MCP Tool。仅当Business Application与Agent Publication都冻结支持的File MCP Tool且当前Job绑定有效任务工作区时，Runtime SHALL 额外注册部署固定File MCP Server及沙盒受限`Read`、`Glob`、`Grep`、`Write`和`Edit`；数据库更新、Redis删除、重启、部署、PR创建、任意Shell和沙盒外文件操作仍 MUST 被拒绝。

#### Scenario: Diagnostic Job asks for a mutating tool
- **WHEN** 普通诊断Job没有文件工具却请求代码修改、数据库更新、Redis删除、重启、部署或沙盒执行
- **THEN** 系统因工具未注册或被拒绝而阻止调用

#### Scenario: File Job uses registered sandbox tools
- **WHEN** 文件Job调用Job冻结的File MCP Tool和当前沙盒受限文件工具
- **THEN** 调用分别通过File Service与Runtime路径守卫执行
- **AND** 不经过旧`ToolRegistry`动态实现或任意Server

### Requirement: Final reports are evidence based
The system SHALL require Agent final answers to include a conclusion, evidence summary, uncertainty or limitations when applicable, and suggested safe next actions. Real runtime prompts SHALL instruct the model to follow this report structure using tool evidence gathered during the job.

#### Scenario: Agent completes order diagnosis
- **WHEN** the Agent finishes investigating a business question such as an order stuck in a status
- **THEN** the final report includes the likely cause, relevant log/database/Redis/ER/business-flow evidence, uncertainty if evidence is incomplete, and non-mutating recommendations

### Requirement: Private model reasoning is not persisted
The system SHALL persist user-visible execution steps and evidence summaries, not private model chain-of-thought. `AgentExecutor` SHALL persist tool call summaries from `AgentRunResult.tool_events` and SHALL NOT persist raw SDK thinking blocks or hidden reasoning content.

#### Scenario: Agent records progress
- **WHEN** the Agent reasons internally during diagnosis
- **THEN** the system persists only safe step summaries, tool calls, tool results, artifacts, and final answer content

#### Scenario: Tool events are persisted after real execution
- **WHEN** `RealClaudeCodeAgentClient` returns tool events for a completed job
- **THEN** `AgentExecutor` writes corresponding `agent_tool_call` rows with desensitized summaries

### Requirement: AgentExecutor records Claude tool loop progress
The system SHALL add execution steps when the real runtime starts, completes context preparation, and finishes model execution, so operators can inspect job progress through the debug API.

#### Scenario: Real runtime adds completion step
- **WHEN** the real runtime returns a final answer
- **THEN** AgentExecutor records a step indicating model execution completed before saving the result

### Requirement: 诊断上下文必须包含目标 schema 目录
系统 SHALL 在诊断上下文中提供目标 environment/base/workshop 可访问的 schema 目录或明确说明无法唯一解析目标。schema 目录 MUST 来自 Internal API Platform，只包含按权限和 topology 过滤后的表、列和非密钥元数据。

#### Scenario: 单一目标问题预取 schema
- **WHEN** 用户问题能从 addressing 目录唯一解析到一个 partitioned workshop
- **THEN** Agent context 包含该 workshop 的 schema 目录摘要，供模型生成 SQL 前检查可用表和字段

#### Scenario: 目标不明确时不猜 schema
- **WHEN** 用户问题不能唯一解析 environment/base/workshop
- **THEN** Agent context 要求模型先解析目标或报告目标不明确，不得猜测不存在于 addressing 目录的目标代码

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

<!-- Reconciled from mcp_new capability: `rabbitmq-agent-job-execution` -->

### Requirement: API 服务必须使用 RabbitMQ 投递 Agent Job
在 Docker Compose/runtime 装配中，API MUST 在创建 Job 的事务内写入 Job Dispatch Outbox；独立 Dispatcher SHALL 使用 RabbitMQPublisher 发布到当前 Agent Job exchange/queue。API 请求线程不得在数据库提交后直接发布。

#### Scenario: API 创建任务后提交 Outbox
- **WHEN** API 通过受支持入口创建 Agent Job
- **THEN** PostgreSQL 同一事务保存 Job 与唯一 PENDING Outbox event

#### Scenario: Dispatcher 发布 RabbitMQ 消息
- **WHEN** Dispatcher 领取到期 event
- **THEN** 它发布 event/job/correlation 标识并在 publisher confirm 后记录状态

#### Scenario: 测试使用内存适配器
- **WHEN** 单元测试显式选择测试装配
- **THEN** 可以使用内存 Publisher/Consumer，但仍必须验证 Outbox 领域行为

### Requirement: Worker 必须消费真实 RabbitMQ 队列
在 Docker Compose/runtime 装配中，`agent-worker` SHALL 使用 `RabbitMQConsumer` 持续消费 `agent.job.queue`，claim 固定 Job，并通过平台固定的 Runtime client registry 调用 Job Publication 决定的独立 Runtime。Worker MUST 不得进程内加载或执行任一 Claude Agent SDK。

#### Scenario: Worker消费Python Job
- **WHEN** `agent.job.queue` 中存在固定为 `python-v1` 的未消费 Job 消息
- **THEN** `agent-worker` 从 RabbitMQ 接收消息、claim Job，并调用 `python-agent-runtime`

#### Scenario: Worker消费TypeScript Job
- **WHEN** `agent.job.queue` 中存在固定为 `typescript-v1` 的未消费 Job 消息
- **THEN** `agent-worker` 从 RabbitMQ 接收消息、claim Job，并调用 `typescript-agent-runtime`

#### Scenario: Worker成功执行后确认消息
- **WHEN** Runtime 终态已验证且 Worker 成功将 Job、结果与 Delivery Outbox 提交到本地数据库
- **THEN** `agent-worker` ack 当前 RabbitMQ 消息，且不会再次执行同一模型 invocation

### Requirement: 跨进程 Job 执行必须落到同一个 PostgreSQL
系统 SHALL 确保 `api-server` 和 `agent-worker` 使用同一个 `DATABASE_DSN`，使 API 创建的 job 能被 worker 读取、claim、执行并更新结果。

#### Scenario: Worker 执行 API 创建的任务
- **WHEN** `api-server` 创建 job 并发布 RabbitMQ 消息
- **THEN** `agent-worker` 能从 PostgreSQL 读取该 job，claim 为 `RUNNING`，执行完成后更新为 `SUCCEEDED`

#### Scenario: 查询接口看到 worker 更新
- **WHEN** worker 将 job 更新为 `SUCCEEDED`
- **THEN** API 查询该 job 时返回 `SUCCEEDED` 状态和最终报告内容

### Requirement: 应用启动必须初始化数据库一次
系统 MUST 由独立 one-shot Migrator 初始化或升级数据库；业务应用启动只构建一次 Container 并只读验证 schema head，不得执行 migration 或在请求中重复初始化。

#### Scenario: Migrator 成功后 API 启动
- **WHEN** schema 已达到所需 head
- **THEN** API 复用生命周期 Container 并开始服务

#### Scenario: API 启动时 schema 落后
- **WHEN** Migrator 未运行或失败
- **THEN** API 必须拒绝就绪，不得自行迁移

#### Scenario: 请求复用启动时 container
- **WHEN** Debug 或 Channel 请求到达
- **THEN** handler 从应用状态读取已初始化 Container

### Requirement: 失败处理必须路由到 retry 或 dead-letter
Job 和 Outbox 失败 MUST 分别按照错误分类、到期时间和最大次数进入 RETRY_WAIT 或 DEAD；所有状态变更必须先持久化，再由 Outbox/Dispatcher 发布，不得依赖一次直接 publish。

#### Scenario: 可重试执行失败
- **WHEN** Job 执行出现可重试错误且未超过上限
- **THEN** 系统原子保存 retry metadata 和重试 dispatch event

#### Scenario: 不可重试执行失败
- **WHEN** Job 出现非重试错误或耗尽次数
- **THEN** 系统保存终态与 DEAD event/记录并审计安全原因

#### Scenario: RabbitMQ 暂时不可用
- **WHEN** Dispatcher publish 失败
- **THEN** Outbox 保持可恢复状态并有限退避，不丢失已提交 Job

### Requirement: Docker Compose 必须可验证完整闭环
系统 SHALL 提供 Docker Compose 级验证方式，证明 `api-server`、PostgreSQL 18、RabbitMQ 4 Management、纯编排 `agent-worker`、`python-agent-runtime`、`typescript-agent-runtime` 和 Delivery Dispatcher 能协同完成两种 Runtime 的成功 Job、真实延迟重试、dead-letter 和终态失败投递闭环。

#### Scenario: Python Runtime成功闭环
- **WHEN** 使用 Docker Compose 启动服务并通过受支持入口提交选择 Python Agent 的问题
- **THEN** Worker 经 RabbitMQ 消费后调用 Python Runtime，将 Job 更新为 `SUCCEEDED`，查询能看到结果且配置渠道收到一次投递

#### Scenario: TypeScript Runtime成功闭环
- **WHEN** 使用 Docker Compose 启动服务并通过受支持入口提交选择 TypeScript Agent 的问题
- **THEN** Worker 经 RabbitMQ 消费后调用 TypeScript Runtime，将 Job 更新为 `SUCCEEDED`，查询能看到结果且配置渠道收到一次投递

#### Scenario: 验证RabbitMQ 4延迟重试回流
- **WHEN** 任一 Runtime 的集成 smoke 首次触发可重试错误并配置短延迟
- **THEN** 测试观察 retry queue 入队、到期、dead-letter 回主队列、同一 Job 被再次 claim，并使用原冻结 Runtime 最终成功或进入终态

#### Scenario: 验证RabbitMQ 4最终失败路径
- **WHEN** 任一 Runtime 持续触发可重试错误直到次数耗尽或直接触发不可重试错误
- **THEN** Job 状态、retry count、dead-letter 消息、审计和一次安全失败 delivery attempt 保持一致

### Requirement: Agent Job retry queue 拓扑必须可延迟回流且可兼容升级
系统 SHALL 使用版本化 durable retry delay queue，并为其配置 dead-letter 到 Agent Job 主队列；系统 MUST NOT 使用不等价参数重新声明已经存在的无 DLX retry queue。

#### Scenario: 新部署声明 retry delay queue
- **WHEN** Publisher、Worker 或拓扑检查初始化 RabbitMQ 4 队列
- **THEN** 版本化 retry queue 带有指向主队列的 DLX/routing key，Publisher 按消息设置 expiration，且该延迟队列不需要消费者

#### Scenario: 旧无参数 retry queue 已存在
- **WHEN** 部署环境中已存在 durable `agent.job.retry.queue` 且没有 DLX 参数
- **THEN** 系统使用新版本队列名，不触发 `PRECONDITION_FAILED`，并在运维检查中报告旧队列消息数供对账

### Requirement: 滞留 retry Job 恢复必须显式、幂等且可审计
系统 SHALL 提供默认 dry-run 的恢复工具，识别旧实现遗留的等待任务；只有管理员显式应用后才能重新调度候选 Job，恢复过程 MUST 不默认 purge 旧队列。

#### Scenario: 管理员执行 dry-run
- **WHEN** 管理员运行滞留 Job 对账而未指定 apply
- **THEN** 系统只输出安全候选摘要和原因，不修改 Job、不发布消息、不删除队列消息

#### Scenario: 管理员显式恢复 Job
- **WHEN** 管理员确认候选并显式指定 Job 执行恢复
- **THEN** 系统幂等写入等待重试状态、发布到新拓扑并记录操作者、Job、前后状态和 publish 结果

#### Scenario: 同一 Job 被重复恢复
- **WHEN** 管理员或自动化重复提交已经恢复、运行或终态的 Job
- **THEN** 系统不重复调度可执行副本，并返回当前持久化状态和审计结果

### Requirement: 旧 RabbitMQ 拓扑不得长期兼容
Outbox 切换成功后，系统 MUST 确认旧消息已排空或隔离、无消费者，再按精确名称删除旧 queue、exchange、binding、配置和代码；不得长期双写。

#### Scenario: 旧队列仍有消息
- **WHEN** 切换核验发现旧队列仍有未转换消息
- **THEN** 删除必须停止，消息进入转换或隔离流程

### Requirement: Worker必须拥有跨Runtime执行的业务状态
`agent-worker` SHALL 独占 claim、授权复核、Publication/hash 校验、retry/终态决策、Tool 事件与结果持久化、Delivery Outbox 创建和 RabbitMQ ack。Python/TypeScript Runtime MUST NOT 直接改变这些业务事实。

#### Scenario: Runtime执行成功
- **WHEN** 固定 Runtime 返回合法 completed 终态
- **THEN** Worker 在本地事务中保存结果、将 Job 转为 SUCCEEDED 并创建唯一 Delivery Outbox 后再确认 RabbitMQ 消息

#### Scenario: Runtime执行失败
- **WHEN** 固定 Runtime 返回 failed 终态或协议客户端抛出分类错误
- **THEN** Worker 使用现有 Job policy 决定 RETRY_WAIT 或 FAILED/TIMEOUT，并仅在终态创建一次安全失败投递

#### Scenario: Runtime越权写业务状态
- **WHEN** 部署检查 Runtime 数据库授权和容器配置
- **THEN** 两个 Runtime 均不具备 Agent Job、授权、RabbitMQ Outbox 或 Delivery 写权限

### Requirement: RabbitMQ确认必须等待本地终态提交
Worker MUST 在 TypeScript Runtime 终态被验证且本地 Job/结果/Delivery 事务提交后才 ack 当前 RabbitMQ 消息。Runtime 已完成但本地提交失败时，Worker SHALL 通过相同 invocation/digest 恢复终态，不得直接启动新的模型执行。

#### Scenario: Runtime完成后数据库提交失败
- **WHEN** Runtime 已返回 completed 但 Python 本地事务回滚
- **THEN** RabbitMQ 消息不被错误确认，重试使用相同 invocation/digest 获取既有安全终态

#### Scenario: 重复RabbitMQ消息
- **WHEN** 相同 dispatch event 被重复投递
- **THEN** Job claim、Runtime invocation 幂等和本地终态共同阻止重复模型执行与重复 Delivery

### Requirement: Runtime选择必须来自Job固定的Agent Publication
Worker MUST 使用 Job 创建事务中从 Agent Publication 固定的 runtime kind 和协议版本选择 Runtime。环境变量、Application allowlist、Runtime 健康状态或错误不得覆盖该选择；未知或不一致的值 MUST 失败关闭。

#### Scenario: 固定Runtime发生瞬时故障
- **WHEN** `typescript-v1` Job 调用 TypeScript Runtime 发生可重试连接错误
- **THEN** Worker 仍以 `typescript-v1` 调度后续 retry，不自动改用 Python Runtime

#### Scenario: Job与Publication Runtime不一致
- **WHEN** 新 schema Job 的 runtime kind 与其 Agent Publication snapshot 不一致
- **THEN** Worker 在调用模型前以不可重试完整性错误停止并创建安全失败结果

#### Scenario: 旧迁移门禁仍有配置
- **WHEN** 环境中残留 TypeScript environment/Application allowlist 配置
- **THEN** 新 Job 创建与 Worker 执行不读取该配置，运维预检报告残留项供删除

### Requirement: Python Worker必须拥有跨语言执行的业务状态
系统 SHALL 继续由 Python `agent-worker` 消费 RabbitMQ、claim Job、复核授权、决定 retry/终态、持久化安全 Tool 事件、保存结果并创建 Delivery Outbox。TypeScript Runtime MUST NOT 直接消费业务队列、修改 Job 状态、发布 retry 消息或创建 Delivery。

#### Scenario: TypeScript执行成功
- **WHEN** Runtime 为一次 attempt 返回合法 completed 终态
- **THEN** Python Worker 在本地事务中保存结果、将 Job 转为 SUCCEEDED 并创建 Delivery Outbox 后再确认 RabbitMQ 消息

#### Scenario: TypeScript执行失败
- **WHEN** Runtime 返回稳定 failed 终态或协议客户端抛出分类错误
- **THEN** Python Worker 使用现有 retry policy 决定 RETRY_WAIT 或 FAILED/TIMEOUT，并在终态创建一次安全失败投递

#### Scenario: Runtime越权写业务状态
- **WHEN** 部署检查 Runtime 数据库授权和容器配置
- **THEN** Runtime 只具备模型连接/active Secret 所需最小读权限，不具备 Agent Job、授权或 Delivery 写权限

<!-- Reconciled from mcp_new capability: `result-delivery-routing` -->

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

### Requirement: DingTalk delivery chunks preserve ordering
系统 SHALL 对 DingTalk 企业 App 和 webhook 群机器人出口复用统一报告分片逻辑，按顺序发送并持久化每个分片状态。

#### Scenario: DingTalk report exceeds chunk limit
- **WHEN** DingTalk delivery 的报告超过配置的 `DELIVERY_CHUNK_MAX_CHARS`
- **THEN** 系统按顺序发送多个分片，每个分片包含 `part x/y` 标识，并记录每个 chunk 的状态

#### Scenario: One chunk fails
- **WHEN** DingTalk delivery 中任一分片发送失败
- **THEN** 系统记录失败分片和安全错误摘要，delivery attempt 标记为失败，Agent job 不重新执行

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

### Requirement: Trigger Delivery 失败不得重新执行 Agent
系统 SHALL 把受管 Webhook 的 Agent 执行状态与 Delivery attempt 分开；投递失败 MUST NOT 将 Webhook event重新分发或重跑 Agent。

#### Scenario: 钉钉临时不可用
- **WHEN** Agent job 已成功但固定钉钉 Delivery 返回临时错误
- **THEN** 系统保留 job 成功状态并按 Delivery 策略重试或标记投递失败，不创建新 job

### Requirement: Webhook 事件页关联 Delivery 证据
系统 SHALL 允许授权管理员从 Webhook event 查看关联 job、Delivery attempt 和 chunk 状态的安全摘要，而不复制完整目标凭证或报告正文。

#### Scenario: 查看分片投递结果
- **WHEN** 长报告被拆分为多个钉钉消息
- **THEN** 事件页展示分片总数、成功/失败状态和安全错误摘要

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

### Requirement: 应用投递失败不得改变Agent执行结果
系统 SHALL 延续 Delivery 与 Agent 执行分离的生命周期，MUST 在应用投递失败时记录并重试 Delivery，而不是创建新 Job、切换应用版本或重新执行 Agent。

#### Scenario: Agent成功但钉钉投递暂时失败
- **WHEN** Agent Job 已成功生成结果而 session webhook 投递发生可重试错误
- **THEN** 系统保留 Agent 成功状态并按现有策略重试 Delivery
- **AND** 重试使用原 Job 的应用 Publication 和 reply route

#### Scenario: session webhook已过期
- **WHEN** Delivery 检测到原 session webhook 永久过期
- **THEN** 系统将投递标记为不可重试失败并记录安全原因
- **AND** 不改发到应用未授权的钉钉群或用户

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

<!-- Reconciled from mcp_new capability: `runtime-session-isolation` -->

### Requirement: 新连续会话必须绑定发布版本和 Execution Scope
系统 MUST 以业务应用发布 ID、Connector、外部 conversation ID 和 Execution Scope hash 构造连续会话身份；发布或范围变化时必须创建新 Session。

#### Scenario: 同一群聊继续对话
- **WHEN** 同一 Connector、外部 conversation、业务应用发布和 Execution Scope 收到后续消息
- **THEN** 系统可以复用同一受控 Session

#### Scenario: 应用重新发布
- **WHEN** 同一外部 conversation 使用新的业务应用发布版本
- **THEN** 系统必须创建新 Session，不得附着旧上下文

### Requirement: 私聊会话必须额外绑定请求人
私聊 Session key MUST 包含已解析的内部 requester ID，不能仅依赖外部 conversation 或 Connector。

#### Scenario: 两个用户共享异常外部 conversation ID
- **WHEN** 两个内部用户被映射到相同外部 conversation 标识
- **THEN** 系统仍必须为其创建不同 Session

### Requirement: Webhook 和 Debug 默认使用隔离 Session
Webhook/Grafana 每个外部事件 MUST 默认创建独立 Session；Debug 每次运行 MUST 默认创建新 Session。

#### Scenario: Grafana 重复投递同一事件
- **WHEN** 同一幂等事件被重复接收
- **THEN** 系统返回原 Job/Session，不创建新的连续上下文

#### Scenario: Debug 显式继续 Session
- **WHEN** 当前用户请求继续自己可访问的 Debug Session
- **THEN** 只有业务应用发布和 Execution Scope 未变化时系统才可继续

### Requirement: application 和 actor 连续会话模式必须停用
新 Job MUST NOT 使用 `application` 或 `actor` 模式共享上下文；旧模式 Session 只可作为历史读取，不得再附着新 Job。

#### Scenario: 旧应用配置仍声明 application 模式
- **WHEN** 旧发布版本尝试创建新 Job
- **THEN** 系统必须阻止并要求重新发布为受支持的隔离策略

<!-- Reconciled from mcp_new capability: `transactional-runtime-outbox` -->

### Requirement: Job 创建与 dispatch event 必须原子持久化
系统 MUST 在同一个 Unit of Work 中持久化 Agent Job 与唯一的 Job Dispatch Outbox event，API 不得在数据库提交后直接依赖一次 RabbitMQ publish 保证投递。

#### Scenario: Job 事务提交成功
- **WHEN** 入口请求成功创建 Job
- **THEN** Job 与对应 PENDING Outbox event 必须同时可见

#### Scenario: Job 事务回滚
- **WHEN** Job 创建事务失败
- **THEN** Job 和 Outbox event 必须都不可见，且不得发布 RabbitMQ 消息

### Requirement: Outbox Dispatcher 必须提供 at-least-once 发布
Dispatcher SHALL 以多副本安全方式领取到期 event，并在 RabbitMQ publisher confirm 后记录发布结果；系统 MUST 允许重复消息但不得丢失已提交 event。

#### Scenario: 发布后确认前 Dispatcher 崩溃
- **WHEN** RabbitMQ 已接收消息但 Dispatcher 尚未提交 published 状态即崩溃
- **THEN** event 可以再次发布，消费者必须用持久化幂等键避免重复业务副作用

#### Scenario: 多个 Dispatcher 同时运行
- **WHEN** 多个 Dispatcher 轮询同一批到期 event
- **THEN** 数据库领取机制必须避免它们同时拥有同一次处理权

### Requirement: Agent 执行与 Delivery 必须使用独立状态机
Agent Job 的 `SUCCEEDED` MUST 只表示 Agent 已产生并持久化结果；外部投递必须由同事务创建的 Delivery Outbox 驱动，Delivery 失败不得改变 Job 成功状态或重跑 Agent。

#### Scenario: Agent 成功但 DingTalk 暂时不可用
- **WHEN** Job 已保存结果并进入 SUCCEEDED，Delivery adapter 返回瞬时错误
- **THEN** Delivery 必须进入自身的 RETRY_WAIT，Job 保持 SUCCEEDED

#### Scenario: Delivery 最终进入 DEAD
- **WHEN** Delivery 已耗尽最大重试次数
- **THEN** Delivery 必须进入 DEAD 并保留安全错误与审计，Agent Job 不得重新执行

### Requirement: Outbox 与 Delivery 消费必须端到端幂等
Job dispatch、Delivery attempt 和 Delivery chunk MUST 使用稳定唯一键及原子状态转换，重复 RabbitMQ 消息不得产生重复 Agent 成功结果或重复成功投递。

#### Scenario: 同一 Delivery event 被重复消费
- **WHEN** 两个消费者先后收到同一 Delivery event
- **THEN** 已成功的 attempt/chunk 不得再次发送，重复消息被安全确认

### Requirement: 运维恢复必须显式、有限且不可改写 payload
系统 SHALL 提供只读状态/指标及按 event、job 或 delivery 精确定位的 CLI replay；MUST NOT 提供任意 payload replay、无限重试或本次 Web 运维页面。

#### Scenario: 运维重放 DEAD delivery
- **WHEN** 授权运维人员使用 CLI 指定一个 DEAD delivery ID
- **THEN** 系统校验当前状态、记录审计并创建一次有次数上限的重放

#### Scenario: 运维提交自定义消息体
- **WHEN** CLI 请求用任意 payload 替换原事件内容
- **THEN** 系统必须拒绝该请求

### Requirement: Outbox 切换必须一次完成且删除精确旧拓扑
切换期间 MUST 停止相关 Worker/Dispatcher、排空或幂等转换待处理记录并隔离无法转换的记录；切换后不得长期双写旧新路径。

#### Scenario: 旧消息拓扑确认已排空
- **WHEN** 旧 queue/exchange/binding 无消息且无消费者
- **THEN** 维护操作可以按精确名称删除旧拓扑、配置和代码

#### Scenario: 存在无法转换的旧消息
- **WHEN** backfill 无法确定某条旧消息的幂等身份或目标
- **THEN** 该消息必须进入隔离清单并阻止宣告切换完成

<!-- Reconciled from mcp_new capability: `agent-runtime-service-contract` -->

### Requirement: Python与TypeScript Runtime必须是独立服务
系统 SHALL 提供 `python-v1` 与 `typescript-v1` 两个独立 Agent Runtime 服务；每个服务只执行一次 Agent attempt，不得消费 RabbitMQ、claim Job、决定 retry、写 Job/Delivery 业务状态或直接投递结果。

#### Scenario: Worker调用Python Runtime
- **WHEN** Job 固定的 runtime kind 为 `python-v1`
- **THEN** Worker 通过内部 Runtime client 调用 `python-agent-runtime`
- **AND** Python Runtime 使用 Python Claude Agent SDK 完成本次 attempt

#### Scenario: Worker调用TypeScript Runtime
- **WHEN** Job 固定的 runtime kind 为 `typescript-v1`
- **THEN** Worker 通过内部 Runtime client 调用 `typescript-agent-runtime`
- **AND** TypeScript Runtime 使用 TypeScript Claude Agent SDK 完成本次 attempt

#### Scenario: Runtime尝试拥有业务状态
- **WHEN** 检查任一 Runtime 的队列订阅、数据库角色和容器配置
- **THEN** Runtime 不具备 RabbitMQ consumer 或 Job/Delivery 写权限

### Requirement: 双Runtime必须实现同一版本化执行协议
两个 Runtime MUST 实现同一份版本化执行、事件、取消、终态恢复和错误 schema。协议 SHALL 固定 runtime kind、invocation、attempt、request digest、Publication/hash、模型连接、执行限制、Tool allowlist 和 correlation ID；Runtime URL 不得来自 Agent、Application、外部请求或模型输出。

#### Scenario: 相同合约用例运行于两个Runtime
- **WHEN** contract suite 对 Python 与 TypeScript Runtime 执行同一 accepted、tool、completed、failed 和 cancel fixture
- **THEN** 两端均返回 schema 合法、sequence 单调且唯一终态的结果

#### Scenario: Runtime协议版本不受支持
- **WHEN** Worker 或 Runtime 收到不受支持的协议版本、未知 runtime kind 或超限事件
- **THEN** 调用以稳定协议错误失败关闭且不执行模型

#### Scenario: 请求尝试指定任意Runtime地址
- **WHEN** Agent/Application 配置或外部 payload 包含自定义 Runtime URL
- **THEN** 系统忽略或拒绝该字段，只使用平台固定的 Runtime client registry

### Requirement: Runtime执行必须支持幂等终态恢复
Runtime MUST 以 `invocation_id + request_digest` 标识一次逻辑执行，并 SHALL 保存有界、脱敏的终态以支持 Worker 断线或本地事务失败后的恢复。相同 invocation 与不同 digest 的请求 MUST 被拒绝，恢复不得启动第二次模型执行。

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

### Requirement: Runtime健康与模型探测必须语言对等
两个 Runtime SHALL 提供 health、readiness、version 和无 Tool 模型连接 probe。health/readiness MUST NOT 调用模型或 MCP Tool；probe MUST 使用固定模型连接 revision/hash、单轮、安全合成输入和短超时，并返回脱敏结果。

#### Scenario: 平台聚合双Runtime readiness
- **WHEN** 管理员读取平台 readiness
- **THEN** 响应分别展示 `python-v1` 与 `typescript-v1` 的协议、SDK/CLI 和配置状态
- **AND** 检查不产生外部模型费用

#### Scenario: 显式测试模型连接
- **WHEN** 授权管理员对任一 Runtime 兼容的模型连接发起 probe
- **THEN** 对应 Runtime 禁用 Tool 并返回版本、脱敏 provider host、model、耗时和稳定错误码

### Requirement: Runtime镜像必须隔离SDK依赖
`agent-worker` 镜像 MUST 不包含 Python/TypeScript Agent SDK 或 Claude Code CLI。Python SDK 与其所需 CLI SHALL 只安装在 Python Runtime 镜像；TypeScript SDK SHALL 只安装在 TypeScript Runtime 镜像。

#### Scenario: 检查Worker镜像内容
- **WHEN** CI 对最终 `agent-worker` 镜像执行依赖和可执行文件检查
- **THEN** Python Claude Agent SDK、TypeScript Claude Agent SDK 和 Claude Code CLI 均不存在

#### Scenario: 检查Runtime镜像内容
- **WHEN** CI 分别检查两个 Runtime 镜像
- **THEN** 每个镜像只包含其实现所需的 SDK/CLI 和协议产物

### Requirement: 双Runtime必须共享无专用密钥的标准MCP工具服务
系统 SHALL 使用官方 MCP SDK 提供单一标准 MCP Tool Server，供 Python 与 TypeScript Runtime 调用。系统 MUST 删除 `runtime-tool-mcp`、其 HS256 signing key、access token issuer/verifier 和专用 claims；标准 MCP Tool Server MUST NOT 引入替代 Token、签名密钥、治理控制面或任意 Server URL。

#### Scenario: Python与TypeScript调用相同工具
- **WHEN** 两个 Runtime 分别执行包含同一冻结 Tool 的 Job
- **THEN** 两端通过同一标准 MCP Tool Server 和 Tool schema 获得等价安全结果

#### Scenario: MCP服务部署边界
- **WHEN** 检查 Compose、端口和网络配置
- **THEN** 标准 MCP Tool Server 只在固定私有网络可达且不映射宿主机端口
- **AND** 服务不挂载 Runtime Tool signing key 或要求 MCP Bearer Token

#### Scenario: 请求提供任意MCP地址
- **WHEN** Agent、Application、用户 payload 或模型输出包含自定义 MCP Server URL
- **THEN** 两个 Runtime 均拒绝该地址，只使用平台部署时固定的标准 MCP Tool Server

#### Scenario: 旧Runtime Tool配置残留
- **WHEN** 部署或代码扫描发现 `runtime-tool-mcp` 服务、`RUNTIME_TOOL_MCP_*` 配置、HS256 issuer/verifier 或 signing key secret
- **THEN** 发布检查失败，直到旧服务及密钥链路被完全删除

### Requirement: Runtime Grant不得扩展为MCP认证
Worker→Runtime 的 Runtime Grant SHALL 继续只绑定执行、取消和终态恢复请求。Runtime Grant 的私钥、公钥或 Bearer Token MUST NOT 传递给标准 MCP Tool Server，也不得作为替代的 MCP signing key。

#### Scenario: Runtime调用MCP工具
- **WHEN** Python 或 TypeScript Runtime 调用标准 MCP Tool Server
- **THEN** 请求不携带 Runtime Grant，MCP Tool Server 也不读取 Runtime Grant key pair

#### Scenario: Worker调用Runtime
- **WHEN** Worker 创建或取消一次 Runtime invocation
- **THEN** 对应 Runtime 仍校验绑定该 Job、Publication、invocation 和 request digest 的短期 Runtime Grant

### Requirement: Runtime 请求必须只冻结 MCP Tool 而不包含旧平台对象
Worker 发送给 Python/TypeScript Runtime 的执行请求 SHALL 只包含固定 `tool-mcp` Server code、精确 Tool identifier/schema hash 和 Job 标识；MUST NOT 包含 Capability Release、Handler Revision、API Connection、Resource Mapping、Resource Revision、Internal API Token 或任意 MCP URL。

#### Scenario: Worker 构造 Runtime 请求
- **WHEN** Job 冻结了两个 MCP Tool
- **THEN** Runtime 请求只携带这两个 Tool 的稳定标识和 schema hash，并由 Runtime 使用部署固定 URL

#### Scenario: 请求包含旧平台字段
- **WHEN** 请求包含 capability、handler、connection、resource_mapping 或 internal_api_token
- **THEN** Runtime 合约校验失败且不启动模型调用

<!-- Reconciled from mcp_new capability: `typescript-agent-runtime-service` -->

### Requirement: 系统必须提供独立TypeScript Agent Runtime
系统 SHALL 通过独立 TypeScript 服务执行官方 `@anthropic-ai/claude-agent-sdk`，并 MUST 精确锁定 SDK 和 Node 版本。Runtime MUST NOT 直接消费业务 RabbitMQ 队列、写 Agent Job/授权/Delivery 表或在启动时安装依赖。

#### Scenario: Worker调用TypeScript Runtime
- **WHEN** Python Worker 执行固定为 `typescript-v1` 的 Job attempt
- **THEN** Worker 通过版本化内部协议调用 TypeScript Runtime
- **AND** Runtime 返回规范事件和唯一终态，不直接修改 Job 状态

#### Scenario: Runtime镜像启动
- **WHEN** Compose 启动 `agent-runtime`
- **THEN** 服务以非 root、只读文件系统和精确 lockfile 依赖启动
- **AND** 镜像不包含 Python Claude Agent SDK

### Requirement: 执行协议必须严格版本化且有界
Runtime MUST 校验执行请求 protocol version、invocation、attempt、Job/Publication/model revision 与 hash、执行限制、Tool allowlist 和 request digest。流式响应 MUST 使用单调 sequence、受支持事件类型、字段及总字节上限，并且 MUST 只有一个 completed 或 failed 终态。

#### Scenario: 合法请求返回规范事件流
- **WHEN** Worker 提交 schema 合法且授权匹配的执行请求
- **THEN** Runtime 先返回 accepted，再返回零个或多个安全事件，最后返回唯一终态

#### Scenario: 请求摘要或协议不匹配
- **WHEN** 请求的 protocol、digest、Publication hash 或字段上限无效
- **THEN** Runtime 在调用模型和 MCP 前失败关闭并返回稳定协议错误码

### Requirement: Runtime Grant必须绑定单次执行
Worker SHALL 为每个 attempt 签发短期 Runtime Grant，至少绑定 issuer、audience、authorized party、Job、invocation、Publication/hash、request digest、JTI 和 expiry。Runtime MUST 验证全部 claims 和重放状态，不得仅依赖私有网络位置。

#### Scenario: 有效Grant启动执行
- **WHEN** Grant 的 audience、Job、invocation、digest 和有效期与请求完全一致
- **THEN** Runtime 允许该 invocation 进入执行

#### Scenario: Grant被重放或篡改
- **WHEN** JTI 已被不同摘要使用、Grant 已过期或任一绑定不一致
- **THEN** Runtime 在读取 Secret、调用模型或连接 MCP 前拒绝请求

### Requirement: Runtime必须隔离SDK配置和工具权限
每次SDK调用 MUST 使用独立options、env和Job Sandbox，显式设置`settingSources: []`，仅注册请求固定的`tool-mcp`和/或File MCP Server，并以精确的SDK `tools`可用集合、空`allowedTools`/`allowed_tools`、SDK `default` permission mode和deny-by-default `canUseTool`限制Tool。不得使用会在空自动批准集合下先行拒绝并跳过回调的`dontAsk`。Bash、NotebookEdit、WebFetch、WebSearch、Shell和开放文件修改能力 MUST 被禁用；文件Job的`Read`、`Glob`、`Grep`、`Write`与`Edit`必须经过当前沙盒路径守卫。

#### Scenario: 模型调用允许的只读Tool
- **WHEN** Job请求固定了合法只读MCP Server、Tool、schema hash和scope
- **THEN** Runtime只允许对应`mcp__<server>__<tool>`调用并由MCP服务再次复核Job和scope

#### Scenario: 模型调用允许的文件Tool
- **WHEN** Job请求固定了合法File MCP Tool且Principal JWT、schema hash和scope匹配
- **THEN** Runtime只连接部署固定File Service并把本地文件工具限制到当前Job Sandbox

#### Scenario: 模型尝试调用未授权工具
- **WHEN** 模型请求Bash、Web工具、沙盒外文件操作或不在精确集合中的MCP Tool
- **THEN** Runtime拒绝调用且不向任何Tool backend发出请求

### Requirement: Runtime不得泄漏凭据和私有推理
模型 Key、Runtime Grant、Master Key、Secret value、完整 Prompt、原始 Provider/MCP payload 和 private thinking MUST NOT 出现在 RabbitMQ、Job 快照、Runtime 日志、事件、terminal ledger 或响应中。Runtime 只可输出有界脱敏诊断和安全 Tool provenance；MCP 边界不得创建专用 Token。

#### Scenario: Provider错误包含凭据
- **WHEN** SDK、CLI 或 MCP 错误文本包含 Token、Authorization Header 或带凭据 URL
- **THEN** Runtime 在记录或返回前屏蔽并截断敏感内容

#### Scenario: SDK产生thinking消息
- **WHEN** SDK 流包含 thinking 或其他私有推理 block
- **THEN** Runtime 丢弃该内容，不写入事件、日志或 Job provenance

### Requirement: Runtime执行必须可取消且可幂等恢复
Runtime SHALL 支持取消进行中的 invocation，并把取消传播到 SDK AbortController 和 MCP 请求。相同 `invocation_id + request_digest` MUST 不重复启动模型执行；已终态调用 SHALL 可返回既有安全终态，不同 digest MUST 冲突失败。

#### Scenario: Worker超时后取消
- **WHEN** Job attempt 超时、被撤销或 Worker 连接断开
- **THEN** Worker 请求取消，Runtime 终止 SDK/MCP 活动并返回稳定 cancel/timeout 分类

#### Scenario: Worker在终态后断线
- **WHEN** Runtime 已完成但 Worker 尚未提交本地事务即断线
- **THEN** Worker 使用相同 invocation 和 digest 读取既有终态，而不重复调用模型

### Requirement: Runtime必须提供无副作用健康与模型探针
Runtime SHALL 提供 health、ready、version 和受服务授权保护的模型 probe。健康检查 MUST NOT 调用模型或业务 MCP；模型 probe MUST 固定连接 revision/config hash、禁止 Tool、单轮、短超时且只返回脱敏结果。

#### Scenario: Readiness检查
- **WHEN** 编排系统调用 Runtime readiness
- **THEN** Runtime 报告协议、SDK、配置、Secret/DB 依赖的脱敏状态且不产生模型费用

#### Scenario: 模型连接Probe
- **WHEN** Python 服务提交通过 RBAC/SSRF 校验的固定模型连接 probe
- **THEN** Runtime 使用 active Secret 完成无 Tool 探测并只返回版本、脱敏 host/model、耗时和稳定错误码

### Requirement: Agent Job 固定文件清单但实时复核访问
Agent Job 创建事务 MUST 固定任务工作区ID和Job File Manifest中的精确File/Version ID，并将该清单以有界、无正文、无凭据形式交给所选Runtime。Runtime按需物化时 MUST 由File Service重新检查RUNNING Job、当前内部用户、Business Application访问、私聊所有者或同群会话边界；不得读取清单外或之后产生的版本。

#### Scenario: 执行期间当前版本变化
- **WHEN** Job固定V3后另一Job提交V4
- **THEN** 当前Runtime仍只物化V3
- **AND** 基于V3的后续提交按正常并发规则得到冲突

### Requirement: Runtime 管理单 Job 文件沙盒
Python与TypeScript Runtime MUST 为每次调用创建隔离Job Sandbox，以受控映射保存本地相对路径、File ID和基础Version ID，并在成功、失败、取消或超时终态清理。启动恢复或周期扫描 MUST 清理没有RUNNING Job归属的残留沙盒；目录不得跨Job复用或持久化。

#### Scenario: Runtime进程异常退出
- **WHEN** Job Sandbox未执行正常finally清理且对应Job已经不再RUNNING
- **THEN** 恢复扫描删除该目录
- **AND** 后续Job不能看到其内容

### Requirement: Runtime 通过受控文件桥完成物化和提交
Runtime MUST 通过File Service受控流式接口下载Job File Manifest中的精确版本和上传显式选中的沙盒文件。File MCP只创建物化或提交意图并返回不透明标识，完整文件字节 MUST NOT 进入模型上下文、MCP JSON、Tool事件或审计。Runtime不得获得MinIO凭据、Bucket、对象键或可供模型使用的上传URL。

Python与TypeScript Runtime MUST 使用代码注册的进程内File MCP bridge代理Job冻结的部署固定File Service工具，并在远端ToolResult交回模型前处理隐藏传输控制信息。bridge MUST 使用当前Job File Principal JWT和固定内部流式路径，不得接受模型提供的URL、Header、Token、绝对路径或对象位置；SDK消息返回后再处理的旁路不满足本要求。

Agent Worker MUST 将有界且无正文的Job File Manifest投影交给Runtime。Runtime MUST 在模型请求前主动物化所有`auto_materialize=true`精确版本并向模型提供已校验的安全沙盒元数据；任何自动物化失败 MUST 使Job失败关闭。其余候选只能由Agent使用Manifest中的精确File/Version ID按需物化。

#### Scenario: 当前消息附件在模型执行前已进入沙盒
- **WHEN** Job File Manifest包含一个合法`auto_materialize=true`的当前消息TXT版本
- **THEN** Runtime在首次模型请求前通过受控File bridge完成下载、大小和SHA-256校验及sandbox entry登记
- **AND** 模型可直接从安全相对路径读取该文件而无需先发现File ID

#### Scenario: Agent显式提交沙盒文件
- **WHEN** Agent调用已冻结的文件提交工具并选择一个受控沙盒文件
- **THEN** Runtime使用当前Job绑定流式上传内容到File Service
- **AND** Tool事件只保留文件身份、版本、大小、哈希摘要和结果

#### Scenario: Runtime在模型看到结果前物化文件
- **WHEN** File Service为`file_prepare_materialization`返回合法隐藏传输控制信息
- **THEN** Runtime bridge在该ToolResult返回模型前完成流式下载、大小与SHA-256校验和sandbox entry登记
- **AND** 模型只收到安全相对路径、不透明handle、大小和摘要

### Requirement: Runtime 显式选择单个沙盒输出
仅当当前Job冻结`file_create_commit_intent`时，Runtime SHALL 注册代码自有的`select_sandbox_output`工具。该工具 MUST 只接受当前Job Sandbox中的安全相对`.txt`路径，在返回不透明sandbox entry handle前校验路径边界、常规文件、无符号链接、15 MiB上限和UTF-8；不得返回正文，不得扫描目录，也不得在Job结束时自动选择或提交其它文件。已物化输入继续使用其既有handle。

#### Scenario: Agent选择新生成的TXT
- **WHEN** Agent在`outputs/`或`work/`生成合法TXT并显式调用`select_sandbox_output`
- **THEN** Runtime只为该精确文件创建本Job有效的不透明handle并返回安全元数据
- **AND** 后续提交意图只能上传该handle映射的文件

#### Scenario: Agent未选择其它草稿
- **WHEN** Job沙盒中还存在未选择的其它文件并结束执行
- **THEN** Runtime不扫描、不上传且不提交这些文件
- **AND** finally清理整个Job Sandbox

### Requirement: 文件提交结果不扩展 Job 终态枚举
系统 MUST 为每个File Commit Intent保存独立业务结果，部分提交冲突或拒绝不得回滚其它成功版本。Runtime能持久化最终回复并准确报告文件结果时，Job SHALL使用现有`SUCCEEDED`；系统 MUST NOT 新增`PARTIAL` Job状态。只有Runtime整体执行失败、超时或无法产生最终回复时才使用现有失败类终态。

#### Scenario: 部分文件提交冲突
- **WHEN** 一个Job的两个文件成功且一个文件冲突，Runtime正常返回说明
- **THEN** Job为`SUCCEEDED`
- **AND** 每个提交保留独立结果

### Requirement: 钉钉文件结果按精确版本创建独立交付
钉钉用户明确要求修改或生成文件时，成功提交的精确File Version SHALL 默认创建回当前reply route的文件交付意图，用户明确要求只保存到工作区时除外。第一阶段交付 MUST 创建新的钉盘文件并记录新外部引用、精确Version ID和输入来源血缘，不得覆盖输入原件、交付冲突候选或跨会话发送。

当原 reply route 为钉钉 Stream `sessionWebhook` 时，普通文字回复 SHALL 继续使用该 Webhook；精确文件版本交付 MUST 使用入站冻结的会话类型和来源 Stream Connector应用凭据调用钉钉机器人OpenAPI，私聊目标为冻结的实际发送人，群聊目标为冻结的`openConversationId`。该专用途径 MUST 只处理与原Job、原会话、原Connector绑定的`FILE_VERSION` Delivery，不得授予Stream Connector通用结果投递能力。

`file_deliver_version` SHALL 接受当前Manifest中具有`DELIVER`动作的精确版本，或当前RUNNING Job自身`COMMITTED`提交意图产生的精确版本。对后者，File Service MUST 复核Commit、Job、Workspace、Version、文件归属和内容可用性；不得要求把新输出补写进不可变输入Manifest，也不得仅凭模型提供的File/Version ID授权。

#### Scenario: 群聊生成TXT结果
- **WHEN** 群聊Job按用户请求成功提交一个新TXT版本
- **THEN** 系统为当前群reply route创建该精确版本的新钉盘文件交付
- **AND** 原输入钉盘文件保持不变

#### Scenario: 用户要求只保存
- **WHEN** 用户明确要求结果只保存在任务工作区
- **THEN** 系统提交版本但不创建文件交付意图

#### Scenario: 私聊 Stream 文件与文字使用不同受控通道
- **WHEN** 私聊 Job 正常回复文字并成功提交默认交付的新 TXT 版本
- **THEN** 文字结果通过冻结的 `sessionWebhook` 发送
- **AND** 文件版本通过来源 Stream 应用的私聊机器人 OpenAPI发送给冻结的实际发送人

#### Scenario: 当前Job显式交付刚提交的新版本
- **WHEN** Agent对当前Job刚成功提交且不在输入Manifest中的精确版本调用`file_deliver_version`
- **THEN** File Service以提交意图来源证明授权并幂等返回同一Delivery状态
- **AND** 不返回“文件操作尚未就绪”或扩大Manifest

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
