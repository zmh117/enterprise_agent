## MODIFIED Requirements

### Requirement: Audit events are persisted across the execution chain
系统 SHALL 持久化覆盖 Channel receipt、身份解析、connector/RBAC 决策、Job 创建、队列发布确认、Worker claim、工具调用、Claude 安全错误分类、retry 调度、retry 回流、显式恢复、终态结果、delivery attempt/chunk 和最终投递状态的审计事件，并使用 Job 与 correlation ID 串联全链路。

#### Scenario: Job completes successfully without retry
- **WHEN** Agent Job 被接受、首次执行成功并沿 reply route 投递
- **THEN** 审计链包含入口、身份/RBAC、Job、主队列发布、Worker、工具、最终报告和 delivery 结果

#### Scenario: Job succeeds after retry
- **WHEN** Job 首次发生可重试错误，延迟回流后再次执行成功
- **THEN** 审计链包含安全错误码、retry count、`next_retry_at`、retry publish confirm、回流后的再次 claim、最终报告和 delivery 结果

#### Scenario: Job fails after retries are exhausted
- **WHEN** Job 达到最大重试次数并进入 `FAILED`
- **THEN** 审计链包含每次安全错误分类、retry 调度/回流、终态 dead-letter 决策和一次失败通知 delivery 结果

#### Scenario: Retry dispatch is stranded
- **WHEN** Job 已持久化为等待重试但 RabbitMQ publish confirm 失败或超过预期时间没有回流
- **THEN** 审计记录 dispatch/recovery 状态，使运维能区分模型失败、队列滞留和 Worker 未消费

#### Scenario: Administrator recovers a stranded job
- **WHEN** 管理员通过显式 apply 恢复一个滞留 Job
- **THEN** 审计记录管理员内部身份、目标 Job、恢复前后状态、所用队列版本和 publish 结果，不记录完整外部 payload 或 webhook

#### Scenario: Job fails before execution
- **WHEN** Job 在 Agent runtime 开始前被拒绝
- **THEN** 审计链包含拒绝原因且没有工具执行或模型调用记录

#### Scenario: Grafana event is ignored
- **WHEN** Grafana 事件因为不是 `firing` 被忽略
- **THEN** 审计记录 connector、external event ID、忽略原因和安全 payload 摘要

## ADDED Requirements

### Requirement: 模型与重试审计不得泄漏敏感运行数据
系统 SHALL 对 Claude/DeepSeek 错误、RabbitMQ retry payload、恢复输出和失败通知执行统一脱敏与有界摘要；API key、认证 token、完整 session webhook、完整敏感 URL、原始外部消息、未受限工具结果和模型私有推理 MUST 不进入审计。

#### Scenario: Claude CLI emits sensitive stderr
- **WHEN** CLI 错误包含 authorization、token、key、完整 URL 或请求内容
- **THEN** 审计仅保存屏蔽后的错误分类和有界摘要

#### Scenario: Retry message is audited
- **WHEN** 系统发布或回流 retry 消息
- **THEN** 审计只记录 Job ID、correlation ID、retry count、delay/due time、队列版本和确认结果，不复制用户问题、reply route secret 或模型上下文
