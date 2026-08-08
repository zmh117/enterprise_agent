## MODIFIED Requirements

### Requirement: Agent sessions and jobs are persisted
The system SHALL persist Agent sessions, Agent jobs, user messages, assistant messages, retry metadata, result summaries, failure reasons, source channel metadata, resolved requester identity, business application publication, Handler versions, immutable Execution Scope, routing context, reply route, and the corresponding dispatch/delivery Outbox event in PostgreSQL during the relevant lifecycle transaction.

#### Scenario: New diagnostic request is accepted
- **WHEN** a verified Channel or Debug request passes strict application-role and scope checks
- **THEN** the system persists the isolated Agent session, Agent job, user message, authorization facts, immutable Execution Scope, routing context, reply route, and Job Dispatch Outbox event in one transaction

#### Scenario: Agent result is produced
- **WHEN** Agent execution completes with a final answer
- **THEN** the system persists the assistant message, result summary, job completion timestamp, and Delivery Outbox event in one transaction

#### Scenario: Legacy DingTalk request is accepted
- **WHEN** an existing supported DingTalk ingress is normalized through its published binding
- **THEN** the system persists the same immutable publication, requester, scope and Outbox facts as any other Channel request

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

## ADDED Requirements

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
