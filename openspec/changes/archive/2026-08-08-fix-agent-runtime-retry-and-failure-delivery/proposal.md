## Why

真实钉钉任务已经完成身份解析、RBAC、Job 创建和 Worker claim，但 Claude Agent SDK 返回矛盾的 `is_error=true / subtype=success` 结果后，任务被发布到一个既没有延迟回流拓扑、也没有消费者的 retry queue，导致 Job 永久停留在 `PENDING`，用户始终收不到成功结果或失败通知。该问题会把任何可重试模型故障放大成静默丢任务，必须在继续真实钉钉验收前修复。

## What Changes

- 建立可实际工作的 RabbitMQ Agent Job 延迟重试拓扑：retry 消息按配置延迟后 dead-letter 回主队列，并保留最小 `job_id + correlation_id` 载荷。
- 对已有无参数 retry queue 采用兼容升级方案，不通过不等价参数重新声明旧队列；提供可审计、默认非破坏性的滞留 Job 对账与恢复路径。
- 让 Job 的重试次数、最近安全错误、重试调度、再次 claim、最终成功或最终失败形成一致且可查询的状态链，并继续固定原内部用户和 Agent publication。
- 对 Claude SDK/CLI 的矛盾错误结果建立显式安全分类，例如 `is_error=true` 但 subtype 为 `success`：保留脱敏诊断元数据、有限重试，不把错误文本误当最终答案，也不无限重试。
- 在重试耗尽或遇到不可重试错误时，通过 Job 原有 `reply_route` 只发送一次安全失败通知；中间重试不骚扰用户，Delivery 失败不重新执行 Agent。
- 增加 RabbitMQ 4 真实集成测试，验证“首次失败 → 延迟等待 → 自动回主队列 → 再次执行 → 成功或终态失败投递”的完整闭环，而不只验证 retry queue 中存在一条消息。
- 增加使用合成/脱敏问题的可选真实 Claude/DeepSeek 对照 smoke，定位模型、兼容端点、SDK/CLI 组合问题；常规测试和 readiness 不调用外部模型。
- 补充运行手册和可观测性：能够区分身份拒绝、运行时失败、等待重试、重试滞留、终态失败通知和 Delivery 失败，且不记录 API key、认证 token、完整 session webhook 或模型私有推理。

## Capabilities

### New Capabilities

无。本次修复强化现有 Agent 执行、重试和结果投递能力，不引入新的业务能力边界。

### Modified Capabilities

- `rabbitmq-agent-job-execution`: 将 retry 从“消息被写入队列”提升为可验证的延迟回流和再次消费语义，并增加兼容升级与滞留任务恢复要求。
- `agent-job-lifecycle`: 明确可重试失败、等待重试、再次 claim、重试耗尽和终态失败的持久化状态及幂等约束。
- `claude-agent-runtime-integration`: 增加 SDK/CLI 矛盾结果的分类、脱敏诊断和有界重试要求。
- `result-delivery-routing`: 明确终态失败必须沿原 reply route 发送一次安全通知，中间重试不得发送，Delivery 失败不得触发 Agent 重跑。
- `agent-audit-permission`: 补充 retry 调度/回流、Claude 安全错误分类、恢复操作和终态失败投递的端到端审计要求。

## Impact

- 后端：RabbitMQ publisher/consumer/topology、Job retry service、Agent worker、Job 状态仓储、Claude Agent SDK client、结果投递服务和审计事件。
- 基础设施：RabbitMQ 4 队列命名与参数、Compose/runtime queue 配置；需要兼容已经存在的 `agent.job.retry.queue`。
- 数据：可能增加重试调度或错误分类字段/记录；必须提供幂等 migration，并保持现有 Job、身份和 Agent publication 可读。
- 运维：增加滞留 Job 对账/恢复命令和队列拓扑检查；恢复默认只报告或重新调度安全候选，不自动清空旧队列。
- 测试：单元测试、状态机测试、RabbitMQ 4 容器集成测试、失败投递幂等测试，以及显式 opt-in 的真实模型和真实钉钉 smoke。
- 安全边界不变：Agent 仍为只读诊断 Agent，队列仍只携带内部标识，外部模型测试仅使用合成或已脱敏输入。
