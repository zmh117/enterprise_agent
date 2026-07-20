## Context

2026-07-19 的真实钉钉任务证明身份、RBAC、Job 创建、RabbitMQ 主队列和 Worker claim 均正常。故障发生在真实模型阶段：Claude Agent SDK/CLI 对 DeepSeek Anthropic 兼容端点返回了 `is_error=true` 但 subtype 为 `success` 的矛盾结果。应用把它分类为可重试错误并将 Job 重新置为 `PENDING`，随后 `RabbitMQPublisher.publish_retry()` 只向 `agent.job.retry.queue` 写入普通持久消息。该队列既没有 TTL/DLX 回主队列，也没有消费者，任务因此永久滞留，无法耗尽重试并触发失败投递。

当前附件 retry queue 已采用“每条消息 expiration + queue DLX 回主队列”，说明该模式在本仓库已有先例；Agent Job retry 没有采用同样拓扑。现存 `agent.job.retry.queue` 已由 RabbitMQ 创建为无 DLX 参数的 durable classic queue，RabbitMQ 不允许使用不等价参数原地重新声明，因此升级必须处理既有队列兼容性。

本变更涉及消息总线基础设施、Job 状态机、Claude SDK 基础设施适配、Worker 失败处理、结果投递和审计。Agent 模块继续只依赖消息发布/消费接口，不感知 RabbitMQ channel 或队列参数；只读诊断和统一身份边界保持不变。

## Goals / Non-Goals

**Goals:**

- 可重试 Job 在配置延迟后自动回到主队列并再次被 Worker 消费。
- 每次 retry 都有明确持久化状态、重试次数、错误分类和下次执行时间，且不会并发重复执行。
- SDK/CLI 矛盾结果得到稳定、安全、可测试的错误分类，不被当作成功答案，也不会无限重试。
- 重试耗尽或不可重试失败后，Job 进入终态并沿原 reply route 只发送一次安全失败通知。
- 对现存无参数 retry queue 和滞留 Job 提供不丢数据、不默认清空队列的升级恢复方案。
- 用 RabbitMQ 4 容器验证真实延迟、DLX 回流、再次 claim 和最终投递，而不只断言消息入队。

**Non-Goals:**

- 不修改用户、钉钉身份绑定、RBAC、Agent publication 或数据范围模型。
- 不引入任意写工具、Shell、代码修改、部署或自动修复能力。
- 不把 Delivery retry 与 Agent execution retry 合并；投递失败不能触发模型重跑。
- 不在 readiness、常规测试或部署启动阶段自动调用付费外部模型。
- 不承诺修复 DeepSeek 或 Claude Code 上游实现；本系统负责正确分类、观测、有限重试和安全失败。
- 不自动重放所有历史 `PENDING` Job，也不自动删除或 purge 旧 retry queue。

## Decisions

### 1. 使用版本化延迟队列，避免原地修改既有队列参数

新增默认队列名 `agent.job.retry.delay.v1.queue`。该 durable queue 固定声明：

- `x-dead-letter-exchange=""`
- `x-dead-letter-routing-key=agent.job.queue`

发布 retry 消息时通过 AMQP message `expiration` 设置本次延迟，消息体仍只包含 `job_id` 和 `correlation_id`。延迟队列没有消费者是正常设计；到期后由 RabbitMQ 自动 dead-letter 回主队列。

选择版本化新队列而不是给 `agent.job.retry.queue` 增加参数，因为 RabbitMQ 会对已有 durable queue 的不等价声明返回 `PRECONDITION_FAILED`。也不选择 Worker `sleep`，因为它会占用 prefetch slot、阻塞并发，并在进程重启后失去延迟语义。

队列声明收敛到共享 RabbitMQ topology 组件，publisher、consumer、集成测试和运维检查使用同一组名称和参数，避免各模块分别声明出不同拓扑。发布路径启用 publisher confirms；拓扑不一致或发布未确认必须被视为明确基础设施失败。

### 2. 增加 `RETRY_WAIT` 状态和可查询的重试调度元数据

Job 从 `RUNNING` 遇到可重试错误后，在持久化事务中：

1. `retry_count + 1`；
2. 状态转为 `RETRY_WAIT`；
3. 保存 `last_error_code`、安全 `error_message`、`last_error_at` 和 `next_retry_at`；
4. 保留内部用户、外部身份引用、Agent publication ID/revision/hash 和 reply route。

retry 消息从延迟队列回到主队列后，Worker 仅能原子 claim 已到期的 `RETRY_WAIT` Job。初次任务仍从 `PENDING` claim。重复消息、过早消息、已完成 Job 或已被其他 Worker claim 的消息都被安全 ack/忽略。

使用显式 `RETRY_WAIT` 而不是继续复用 `PENDING`，因为 `PENDING` 无法区分“首次待执行”和“已失败、等待某个时间重试”，也无法可靠发现滞留任务。数据库仍为状态事实源，RabbitMQ 只负责唤醒执行。

### 3. 有界处理 Claude SDK/CLI 矛盾结果

Claude client 增加结构化错误分类器，至少区分：

- `claude_transient_error`：网络、429/5xx、transport、CLI JSON decode 等可重试错误；
- `claude_inconsistent_result`：SDK/CLI 报告 error result，但错误列表为空、subtype 与 error 标志矛盾，或等价的 `error result: success`；
- `claude_configuration_error`：缺少凭据、无效模型、CLI 不存在等不可重试错误；
- `max_turns_exhausted`、`tool_policy_error` 等已有非普通 transient 分类。

`claude_inconsistent_result` 允许进入普通最大次数约束下的有限重试，但安全消息不得直接显示“错误：success”。审计只保存 SDK/CLI 版本、provider/base URL 主机安全摘要、模型策略引用、异常类、脱敏 subtype/error code 和有界 stderr；不得保存 API key、认证 token、完整 URL query、prompt 全文、工具原始结果或模型私有推理。

不把矛盾结果直接标记为成功，因为没有可信 final answer；也不永久标记不可重试，因为兼容端点或 CLI 的瞬时协议异常可能在下一次成功。

### 4. 只在终态失败时投递一次安全失败通知

中间 `RETRY_WAIT` 不触发外部投递。重试耗尽或不可重试错误时，Worker 先原子将 Job 转为 `FAILED`，再调用现有 `ResultDeliveryService.deliver_job_failure()`。失败通知包含稳定错误码、用户可理解的安全原因和 Job 追踪标识，不包含堆栈、凭据或内部完整配置。

投递继续使用 Job 创建时固定的 reply route。对 `dingtalk_stream_session_webhook`，只要 webhook 仍有效就回复原会话；若已经过期，记录 delivery failure，不降级到未明确授权的其他 DingTalk 目标。投递幂等沿用持久化 delivery attempt，重复 dead/Job 消息不得重复发送已成功的终态通知。

### 5. 提供显式滞留 Job 对账和恢复命令

增加运维 CLI，默认 dry-run，识别旧实现遗留的安全候选，例如：`PENDING`、`retry_count > 0`、有错误信息、无结果、未终态、锁已释放且长期没有后续审计。输出 Job ID、重试次数、最后错误分类、reply route 类型和 webhook 是否可能过期的安全摘要。

只有显式 `--apply` 且指定 Job ID/筛选条件时才把候选迁移为 `RETRY_WAIT` 并发布到新延迟队列；操作必须幂等并写审计。CLI 不默认 purge `agent.job.retry.queue`，旧队列删除或清理由运维在确认消息已对账后单独执行。

### 6. 验收必须覆盖真实时间和真实回流

单元测试覆盖状态机、错误分类、失败投递和幂等。RabbitMQ 4 集成测试使用短 TTL，必须观察：retry queue 入队、到期后 retry queue 归零、主队列再次出现/被消费、同一 Job retry_count 正确、最终成功或 FAILED、对应审计和 delivery attempt 完整。

真实模型 smoke 为显式 opt-in，使用合成问题分别运行当前 DeepSeek 兼容配置和一个已知可用的基线配置，记录安全分类差异。真实钉钉验收必须重新发送消息，不能依赖可能已过期的历史 session webhook。

## Risks / Trade-offs

- [新旧 retry queue 并存，运维容易误判] → 新队列使用明确版本名，ready/运维检查同时报告新旧队列消息数，文档说明旧队列只用于对账清理。
- [数据库已写 `RETRY_WAIT` 但 RabbitMQ 发布失败] → 使用 publisher confirm，发布失败记录审计并由滞留扫描识别；恢复 CLI 可安全重新发布，Worker claim 仍保证幂等。
- [RabbitMQ 已回流但数据库状态尚未到期] → Worker 不执行，按剩余延迟重新调度或安全忽略并由恢复扫描兜底，不能提前运行。
- [重复消息导致重复模型调用] → claim 条件包含状态、到期时间和锁，只有一个 Worker 能从 `RETRY_WAIT` 进入 `RUNNING`。
- [失败通知的 session webhook 已过期] → 明确记录 delivery failure，不自动切换出口；运维可在 Web/审计中看到失败，用户需发送新消息建立新 route。
- [真实模型 smoke 产生费用或发送敏感数据] → 默认关闭，必须显式启用，只允许合成/脱敏输入，并对输出和错误做有界脱敏。
- [将上游永久兼容问题误判为 transient] → `claude_inconsistent_result` 只允许有限次数，最终进入 FAILED 并通知用户；对照 smoke 用于进一步确认 provider/model 组合。

## Migration Plan

1. 先部署幂等数据库 migration，增加 `RETRY_WAIT` 及重试调度/错误分类所需字段或等价记录结构。
2. 部署共享 RabbitMQ topology 和新版本 retry queue 配置；启动时声明新队列，不修改旧 `agent.job.retry.queue`。
3. 部署 publisher/consumer、Job 状态机、Claude 错误分类和终态失败投递代码。
4. 运行队列拓扑检查和 RabbitMQ 4 延迟回流集成 smoke，确认 publisher confirm、DLX 和消费者正常。
5. 运行滞留 Job CLI dry-run，人工核对旧队列与数据库候选；仅对明确安全且 reply route 仍可用的 Job 执行恢复。历史 2026-07-19 Job 不默认重放。
6. 用一条新的钉钉消息执行真实验收，验证成功路径；再用受控 synthetic failure 验证重试耗尽和安全失败通知。
7. 观察期结束且旧队列消息全部对账后，由运维显式归档或删除旧队列。

回滚时保留数据库新增字段和新队列，不做破坏性降级；回滚应用到旧版本后停止向新 retry queue 发布。已进入 `RETRY_WAIT` 的 Job 由运维 CLI 报告并人工决定恢复或终止，不能静默改回 `PENDING`。

## Open Questions

- 当前 DeepSeek `deepseek-v4-pro[1m]` 与 Claude Agent SDK/CLI 的矛盾结果究竟来自 provider 兼容层、模型输出还是特定 SDK/CLI 版本，需要在实现安全诊断元数据后用 opt-in 对照 smoke 确认；该未知项不影响重试与失败通知修复。
- 生产环境旧 `agent.job.retry.queue` 是否还有除已定位 Job 之外的历史消息，实施前必须通过 dry-run 对账确认，不能从本地单条样本推断生产范围。
