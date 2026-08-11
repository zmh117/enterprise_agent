# rabbitmq-agent-job-execution Specification

## Purpose
TBD - created by archiving change wire-rabbitmq-agent-job-flow. Update Purpose after archive.
## Requirements
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
Worker MUST 在 Runtime 终态被验证且本地 Job/结果/Delivery 事务提交后才 ack 当前 RabbitMQ 消息。Runtime 已完成但本地提交失败时，Worker SHALL 使用相同 invocation/digest 恢复终态，不得直接启动新的模型执行。

#### Scenario: Runtime完成后数据库提交失败
- **WHEN** Runtime 已返回 completed 但 Worker 本地事务回滚
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
