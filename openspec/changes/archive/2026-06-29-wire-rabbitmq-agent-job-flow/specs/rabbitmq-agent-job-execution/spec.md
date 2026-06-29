## ADDED Requirements

### Requirement: API 服务必须使用 RabbitMQ 投递 Agent Job
在 Docker Compose / runtime 装配中，系统 SHALL 使用 `RabbitMQPublisher` 将新建 Agent job 投递到 `agent.job.queue`，不得使用 `InMemoryMessageBus` 作为跨进程任务通道。

#### Scenario: API 创建任务后发布 RabbitMQ 消息
- **WHEN** `api-server` 通过调试 API 或钉钉 webhook 创建 Agent job
- **THEN** 系统将 job 持久化到 PostgreSQL，并通过 `RabbitMQPublisher` 发布包含 `job_id` 和 `correlation_id` 的消息到 `agent.job.queue`

#### Scenario: 测试仍可使用内存消息总线
- **WHEN** 单元测试或进程内测试显式选择测试装配
- **THEN** 系统可以使用 `InMemoryMessageBus`，但该装配 MUST 不作为 Docker Compose runtime 默认路径

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
系统 SHALL 在应用启动生命周期中执行 migration 和可配置 seed 初始化，并 MUST 不在每次 webhook 或调试 API 请求中重新构建 container 或重复执行初始化逻辑。

#### Scenario: API 启动初始化
- **WHEN** `api-server` 启动
- **THEN** 系统执行幂等 migration 和必要 seed，并将 container 存放在应用生命周期状态中供请求复用

#### Scenario: 请求复用启动时 container
- **WHEN** 调试 API 或 DingTalk webhook 收到请求
- **THEN** handler 从应用状态读取已初始化 container，而不是在请求中重新 `build_container`

### Requirement: 失败处理必须路由到 retry 或 dead-letter
系统 SHALL 在 worker 执行失败时根据错误类型和重试次数执行 retry 或 dead-letter 决策，并记录可查询的失败状态和审计事件。

#### Scenario: 可重试失败进入 retry 路径
- **WHEN** job 执行出现可重试错误且未超过最大重试次数
- **THEN** 系统增加 retry metadata，发布 retry 消息，并记录 retry 审计事件

#### Scenario: 不可重试失败进入 dead-letter 路径
- **WHEN** job 执行出现不可重试错误或超过最大重试次数
- **THEN** 系统将 job 标记为 `FAILED`，发布 dead-letter 消息，并记录失败原因

### Requirement: Docker Compose 必须可验证完整闭环
系统 SHALL 提供 Docker Compose 级验证方式，证明 `api-server`、`postgres`、`rabbitmq` 和 `agent-worker` 能协同完成一次 Agent job。

#### Scenario: curl 验证成功闭环
- **WHEN** 使用 Docker Compose 启动服务并通过 curl 提交调试问题
- **THEN** 系统返回 `job_id`，worker 消费后 job 变为 `SUCCEEDED`，查询 job 能看到最终诊断报告

