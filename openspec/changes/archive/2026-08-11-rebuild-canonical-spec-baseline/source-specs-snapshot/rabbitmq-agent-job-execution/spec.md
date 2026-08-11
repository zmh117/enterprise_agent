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
在 Docker Compose / runtime 装配中，`agent-worker` SHALL 使用 `RabbitMQConsumer` 持续消费 `agent.job.queue` 并调用 Agent job handler。

#### Scenario: Worker 消费队列任务
- **WHEN** `agent.job.queue` 中存在未消费 job 消息
- **THEN** `agent-worker` 从 RabbitMQ 接收消息，并将 `job_id` 传递给 `AgentExecutor`

#### Scenario: Worker 成功执行后确认消息
- **WHEN** `AgentExecutor` 成功将 job 执行到 `SUCCEEDED`
- **THEN** `agent-worker` ack 当前 RabbitMQ 消息，且不会再次执行同一消息

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
系统 SHALL 提供 Docker Compose 级验证方式，证明 `api-server`、PostgreSQL 18、RabbitMQ 4 Management 和 `agent-worker` 能协同完成成功 Job、真实延迟重试、dead-letter 和终态失败投递闭环。

#### Scenario: curl 验证成功闭环
- **WHEN** 使用 Docker Compose 启动服务并通过 curl 提交调试问题
- **THEN** 系统返回 `job_id`，Worker 经 RabbitMQ 4 消费后将 Job 更新为 `SUCCEEDED`，查询 Job 能看到最终诊断报告

#### Scenario: 验证 RabbitMQ 4 延迟重试回流
- **WHEN** 集成 smoke 首次触发可重试错误并配置短延迟
- **THEN** 测试观察 retry queue 入队、到期、dead-letter 回主队列、同一 Job 再次被 Worker claim，并最终成功或耗尽重试进入终态

#### Scenario: 验证 RabbitMQ 4 最终失败路径
- **WHEN** 集成 smoke 持续触发可重试错误直到次数耗尽或直接触发不可重试错误
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
