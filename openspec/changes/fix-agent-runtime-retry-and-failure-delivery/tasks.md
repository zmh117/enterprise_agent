## 1. Job 重试状态与数据库迁移

- [x] 1.1 增加幂等 PostgreSQL migration，为 `agent_job` 增加或等价持久化 `RETRY_WAIT` 所需的结构化错误码、最后错误时间和下次重试时间，并为滞留扫描/到期 claim 建立合适索引。
- [x] 1.2 扩展 Job domain/status service，支持 `RUNNING -> RETRY_WAIT -> RUNNING`、重试耗尽到 `FAILED`、适用 timeout 到 `TIMEOUT` 的受控状态转换，拒绝非法跳转。
- [x] 1.3 更新 Job repository/domain/API 序列化，使 retry count、last error code、安全 error message、last error time、next retry time 和终态时间可查询，且旧行保持兼容。
- [x] 1.4 实现 `PENDING` 初次 claim 与已到期 `RETRY_WAIT` retry claim 的条件更新，确保重复消息或多个 Worker 只有一个能进入 `RUNNING`。
- [x] 1.5 增加 migration、旧数据读取、状态转换、到期/未到期 claim 和并发幂等测试。

## 2. RabbitMQ 延迟重试拓扑

- [x] 2.1 抽取共享 RabbitMQ topology 定义，统一主队列、版本化 `agent.job.retry.delay.v1.queue`、dead queue 的 durable 参数和主队列 dead-letter routing key。
- [x] 2.2 更新 QueueSettings、`.env.example`、Compose/runtime config 与文档，默认使用新版本 retry delay queue，同时保留旧 `agent.job.retry.queue` 名称仅用于对账。
- [x] 2.3 修改 RabbitMQ publisher：retry 消息仅包含 `job_id`、`correlation_id`，按本次 delay 设置 AMQP expiration，并启用 publisher confirms/发布失败的明确异常。
- [x] 2.4 修改 RabbitMQ consumer/bootstrap，使主队列消费前使用共享 topology，验证新 retry queue 的 DLX 参数，且不为 delay queue 注册消费者。
- [x] 2.5 确保已有无 DLX 的 `agent.job.retry.queue` 不会被不等价参数重新声明，启动和升级不会产生 RabbitMQ `PRECONDITION_FAILED`。
- [x] 2.6 增加队列拓扑检查命令或 readiness 安全摘要，报告主队列、新 retry queue、dead queue 及旧 retry queue 的参数和消息数，不输出 RabbitMQ 凭据。

## 3. Retry 调度、回流与终态处理

- [x] 3.1 重构 `JobRetryService`，使用异常稳定 error code 和当前 retry count 决定 retry/dead，在一次应用事务中持久化 `RETRY_WAIT` 元数据和 `next_retry_at`。
- [x] 3.2 在 retry publish confirm 成功、失败和 RabbitMQ 回流 claim 时记录关联同一 Job/correlation ID 的安全审计事件；发布失败必须留下可被恢复工具发现的状态。
- [x] 3.3 处理 retry 消息提前回流：不得提前调用模型，应按剩余时间安全重新调度或保留为可恢复状态，并避免形成忙循环。
- [x] 3.4 确保 retry、重复 delivery 和恢复始终复用原 internal user、external identity reference、session、Agent publication ID/revision/hash 和 reply route。
- [x] 3.5 确保不可重试错误或重试耗尽时原子进入 `FAILED`/适用 `TIMEOUT`，不再发布 retry，并只走一次 dead-letter 与终态失败投递。
- [x] 3.6 增加首次失败后成功、连续失败耗尽、不可重试、publisher confirm 失败、提前回流、重复回流和 publication 在等待期间变化的测试。

## 4. Claude SDK/CLI 安全错误分类

- [x] 4.1 扩展 Claude client 错误分类器，将 `is_error=true` 且 subtype/errors 矛盾或等价 `Claude Code returned an error result: success` 映射为稳定的 `claude_inconsistent_result`。
- [x] 4.2 保持网络、429/5xx、transport、CLI JSON decode 等 transient 分类，并保持缺少凭据、CLI 缺失、明确无效模型、max turns 和工具策略错误的非普通 transient 语义。
- [x] 4.3 为运行时异常携带有界安全诊断元数据，包括异常类、SDK/CLI 版本、模型策略引用、provider host 摘要和脱敏 subtype/errors/stderr，禁止保存凭据、完整 URL、prompt、原始工具结果或私有推理。
- [x] 4.4 将 `claude_inconsistent_result` 的用户安全消息改为可理解的模型运行失败说明，不向 Job、审计或钉钉直接暴露“错误结果：success”或内部堆栈。
- [x] 4.5 增加 fake SDK/CLI 单元测试，覆盖矛盾结果、带 errors 的 error result、敏感 stderr 脱敏、无 final answer、transient、配置错误和最大轮次耗尽。
- [x] 4.6 增加显式 opt-in 的真实模型兼容性 smoke，使用 synthetic prompt 对照当前 DeepSeek 配置和可用基线配置；默认测试、readiness 和 Compose 启动不得调用外部模型。

## 5. 终态失败通知与投递幂等

- [x] 5.1 增加统一安全失败通知格式，包含稳定错误码、用户可理解原因和 Job 追踪标识，不包含凭据、完整 provider/session webhook、外部 raw payload 或模型私有推理。
- [x] 5.2 调整 Worker 失败路径：`RETRY_WAIT` 不发送外部消息；只有 `FAILED`/适用 `TIMEOUT` 终态才调用一次 `deliver_job_failure()`。
- [x] 5.3 强化 delivery 幂等，确保重复 dead-letter、Worker 重启、重复主队列消息或恢复操作不会重复发送已经成功的终态通知。
- [x] 5.4 验证 `dingtalk_stream_session_webhook` 终态失败回复原会话；webhook 过期时只记录脱敏 delivery failure，不切换到未授权目标、不重新执行 Agent。
- [x] 5.5 增加中间 retry 静默、终态失败成功投递、终态通知重复处理、session webhook 过期和 Delivery 失败不触发 Agent retry 的测试。

## 6. 旧队列与滞留 Job 恢复

- [x] 6.1 实现默认 dry-run 的滞留 Job 对账 CLI，识别旧实现留下的 `PENDING + retry_count>0 + error + 无结果 + 无有效锁` 安全候选并输出脱敏摘要。
- [x] 6.2 为 CLI 增加显式 `--apply` 和 Job ID/安全筛选，幂等迁移候选到 `RETRY_WAIT` 并发布新 retry 消息，同时审计操作者、前后状态、队列版本和 publish 结果。
- [x] 6.3 CLI 必须报告旧 `agent.job.retry.queue` 的消息数但默认不消费、purge 或删除；文档要求人工完成数据库与旧队列逐条对账后再清理。
- [x] 6.4 增加 dry-run 零写入、显式恢复、重复恢复、已运行/终态拒绝、publish 失败和敏感 reply route 脱敏测试。
- [x] 6.5 在当前本地环境执行 dry-run，确认 2026-07-19 的历史 Job 仅被报告、不自动重放，并记录后续人工处理建议。

## 7. 真实闭环验证与文档

- [x] 7.1 扩展 RabbitMQ 4 容器集成测试，真实观察 retry 入队、expiration 到期、DLX 回主队列、再次消费和 retry queue 归零。
- [x] 7.2 增加“首次 synthetic transient 失败、第二次成功”的端到端测试，验证同一 Job 最终 `SUCCEEDED`、retry count 正确、无重复模型执行且只投递一次成功结果。
- [x] 7.3 增加“持续 synthetic 失败直到耗尽”的端到端测试，验证 `FAILED`、dead-letter、完整审计和一次安全失败 delivery attempt。
- [x] 7.4 运行完整 backend 测试、RabbitMQ 4 integration、ruff、mypy、migration、OpenSpec strict validation 和 Compose 配置检查。
- [x] 7.5 重建并启动 PostgreSQL、RabbitMQ、API、Agent Worker、DingTalk Stream ingress，核对新旧队列参数、consumer、ready 状态和无 `PRECONDITION_FAILED` 日志。
- [ ] 7.6 在明确 opt-in、仅 synthetic 输入条件下运行真实 DeepSeek/Claude 对照 smoke，记录 `claude_inconsistent_result` 是否复现及 SDK/CLI/provider 安全版本信息。
- [ ] 7.7 由真实已绑定且授权的钉钉用户发送一条新消息，验证身份/RBAC、Job、成功或有界重试、原会话结果/失败通知和无重复投递；不得复用已过期历史 session webhook。
- [x] 7.8 更新运行手册，说明 `RETRY_WAIT`、新旧 retry queue、错误分类、滞留恢复、失败通知、真实模型 opt-in 和回滚/旧队列清理步骤。
