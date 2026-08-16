## ADDED Requirements

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

### Requirement: 数据库 Job retry 和 Outbox 必须保持唯一业务权威
Poison-message 处理 MUST NOT 创建或修改 Job `RETRY_WAIT`、retry count、Job Dispatch Outbox 或 Delivery Outbox。正常 Agent 执行的可重试、不可重试和终态决策 SHALL 继续由 Worker 与数据库 Job retry service 持久化，再由既有 Outbox 发布。

#### Scenario: Worker 已持久化业务重试
- **WHEN** Runtime 可重试失败已由 Worker 保存为 `RETRY_WAIT` 并创建 retry dispatch 事实
- **THEN** consumer 按 handler 正常返回确认原消息，不基于 broker delivery 再增加业务重试

### Requirement: 运行中心 Job 查询必须在持久层过滤和分页
Job 列表 SHALL 在数据库查询中应用当前管理范围、所有请求过滤条件、稳定 `(created_at,id)` keyset cursor 和 `limit + 1`，不得先截断固定窗口再于应用进程过滤。相同窗口、过滤条件和 cursor MUST 返回无遗漏、无重复的稳定页面。

#### Scenario: 匹配记录位于未过滤窗口之后
- **WHEN** 时间窗中前 500 条记录不匹配而更早记录匹配指定用户、状态或应用条件
- **THEN** 查询仍返回匹配记录，不因预取上限漏数

#### Scenario: 受限管理员翻页
- **WHEN** 非平台管理员按其 owner 或业务数据范围查询并连续使用 next cursor
- **THEN** 每页只包含授权且符合过滤条件的 Job，页面之间没有重复或越权记录
