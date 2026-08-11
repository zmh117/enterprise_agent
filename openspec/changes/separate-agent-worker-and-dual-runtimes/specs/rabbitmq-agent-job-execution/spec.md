## MODIFIED Requirements

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

## ADDED Requirements

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
