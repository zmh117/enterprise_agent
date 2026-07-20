## MODIFIED Requirements

### Requirement: Agent job status transitions are controlled
系统 SHALL 通过 Job 应用服务控制至少 `WAITING_INPUT`、`PENDING`、`RUNNING`、`RETRY_WAIT`、`SUCCEEDED`、`FAILED` 和 `TIMEOUT` 状态，并持久化 retry count、最后安全错误、结构化错误码、最后错误时间和下次重试时间；状态跳转 MUST 使用条件更新防止并发覆盖。

#### Scenario: Worker claims pending job
- **WHEN** Agent Worker 开始执行一个 `PENDING` Job
- **THEN** 系统原子将 Job 改为 `RUNNING` 并记录开始时间、锁和 Worker ID

#### Scenario: Retryable failure schedules retry wait
- **WHEN** `RUNNING` Job 发生可重试错误且仍有重试次数
- **THEN** 系统增加 retry count、保存安全错误分类和 `next_retry_at`，并将 Job 原子转为 `RETRY_WAIT`

#### Scenario: Retry message becomes due
- **WHEN** retry 消息回到主队列且 Job 为已到期的 `RETRY_WAIT`
- **THEN** 一个 Worker 原子 claim Job 为 `RUNNING`，清理本次等待锁定信息并继续使用原 Job 上下文执行

#### Scenario: Retry message arrives before due time
- **WHEN** retry 消息回到主队列但 `next_retry_at` 尚未到达
- **THEN** Worker 不提前执行 Job，并按剩余延迟安全重新调度或记录可恢复状态

#### Scenario: Worker completes job
- **WHEN** Agent Worker 产生有效最终报告
- **THEN** 系统将 Job 从 `RUNNING` 改为 `SUCCEEDED`，记录完成时间并清除等待重试时间

#### Scenario: Retry limit is exhausted
- **WHEN** `RUNNING` Job 再次失败且已使用全部重试次数
- **THEN** 系统将 Job 改为 `FAILED`、记录终态安全原因和完成时间，且不再生成 retry 消息

#### Scenario: Worker hits timeout
- **WHEN** Worker 超过配置执行超时且该超时不再重试或重试次数已耗尽
- **THEN** 系统记录 `TIMEOUT` 或等价终态及安全超时原因，并触发终态失败投递

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

## ADDED Requirements

### Requirement: Job retries preserve identity, Agent publication and reply route
系统 SHALL 在所有 retry、重复 delivery 和显式恢复中保持原内部请求人、外部身份引用、Agent publication ID/revision/hash、会话和 reply route，不得在重试时重新选择当前用户映射或最新 Agent 发布版本。

#### Scenario: Agent publication changes during retry wait
- **WHEN** Job 等待重试期间管理员发布新的 Agent revision
- **THEN** retry 仍使用原 Job 固定的 publication snapshot、工具集合和模型策略

#### Scenario: DingTalk identity or role changes during retry wait
- **WHEN** 原用户的钉钉绑定或角色在 Job 等待重试期间发生变化
- **THEN** 系统保留历史 Job 的身份引用和审计事实，同时在实际工具访问处继续执行适用的当前安全授权检查
