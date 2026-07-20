# Agent 重试、失败通知与旧任务恢复

## 运行语义

Agent Job 首次进入 `PENDING`，Worker 条件 claim 后进入 `RUNNING`。可重试错误不会
立即通知钉钉，而是持久化为 `RETRY_WAIT`：

```text
PENDING -> RUNNING -> RETRY_WAIT -> RUNNING
                         |             |
                         +----有界重试--+

RUNNING -> SUCCEEDED
RUNNING -> FAILED / TIMEOUT -> 一次终态失败通知
```

`agent_job` 会保留 `retry_count`、`last_error_code`、脱敏 `error_message`、
`last_error_at` 和 `next_retry_at`。原用户、外部身份、会话、Agent publication 快照和
reply route 不会因重试而重建。

## RabbitMQ 队列

默认队列：

```text
agent.job.queue
agent.job.retry.delay.v1.queue
agent.job.dead.queue
```

`agent.job.retry.delay.v1.queue` 是无人消费的 durable delay queue。每条消息使用 AMQP
expiration，过期后通过 DLX 回到 `agent.job.queue`。旧
`agent.job.retry.queue` 没有 DLX，只允许盘点，启动代码不会用新参数重新声明它，避免
RabbitMQ `PRECONDITION_FAILED`。

安全检查当前拓扑（输出不含 AMQP 凭据）：

```bash
.venv/bin/python -m app.cli.check_agent_retry_topology
```

## 失败分类与通知

- `claude_inconsistent_result`：包括 SDK/CLI 返回等价于 `error result: success` 的矛盾结果；按有界策略重试。
- 网络、429/5xx、transport 和 CLI JSON decode：可重试。
- 缺少凭据、CLI 缺失、明确无效模型、max turns 和工具策略错误：不作为普通 transient 无限重试。
- `RETRY_WAIT` 阶段不向外发送消息。
- 只有 `FAILED` 或 `TIMEOUT` 才通过原 reply route 发送一次安全失败通知。
- 钉钉 Stream session webhook 已过期时仅记录脱敏 delivery failure，不改投其他目标，也不重新执行 Agent。

终态通知只包含稳定错误码、用户可理解原因和 Job ID；provider 完整 URL、session
webhook、凭据、原始 payload、prompt、工具原始结果与私有推理都不会进入通知。

## 滞留任务恢复

先运行默认 dry-run：

```bash
.venv/bin/python -m app.cli.reconcile_stranded_agent_retries
```

可用 `--job-id JOB_ID` 重复限定安全候选。确认数据库记录、旧队列消息和 reply route
仍有效后，显式执行：

```bash
.venv/bin/python -m app.cli.reconcile_stranded_agent_retries \
  --apply --job-id JOB_ID --actor-id ADMIN_USER_ID
```

命令会将旧版 `PENDING + retry_count>0 + error + 无结果 + 无有效锁` 迁移为
`RETRY_WAIT`，或重新发布已过期但未成功调度的 `RETRY_WAIT`。操作是条件更新且可重复；
publish 失败时仍保留可恢复状态并写审计。

旧 `agent.job.retry.queue` 默认永远不会被消费、purge 或删除。必须先把数据库候选和旧
队列消息逐条对应，确认所有需要恢复的 Job 已通过新队列完成后，才由运维人工清理。

## 真实模型验证

默认测试、readiness 和 Compose 启动都不会调用外部模型。只有明确 opt-in 且只使用
synthetic prompt 时，才运行：

```bash
RUN_REAL_CLAUDE_INTEGRATION=1 .venv/bin/pytest -q \
  backend/tests/test_real_claude_integration.py
```

验证记录只能保存 SDK/CLI 版本、模型策略引用、provider host 和脱敏错误摘要。

## 回滚

应用回滚时可以停止 Worker，保留 PostgreSQL 新字段和新队列数据；这些结构向后兼容。
不要把旧队列改造成新 DLX 队列。若需要恢复旧版本，先确保没有 `RETRY_WAIT` Job，再按
数据库候选逐条转回受控状态。RabbitMQ 新旧队列都应在完成消息对账后再人工清理。

## 2026-07-20 本地验证记录

- 新队列 `agent.job.retry.delay.v1.queue` 已按预期声明 DLX，consumer 为 0；主队列 consumer 为 1。
- RabbitMQ 4 隔离测试已观察到 expiration 到期、DLX 回主队列和 retry queue 归零。
- `job_ced04fdfc3c740a9ad8a20b52ab0cecd` 被 dry-run 识别为
  `legacy_pending`；命令模式为 `dry-run`，没有自动重放或修改该 Job。
- 该历史 Job 使用临时 DingTalk Stream session webhook。恢复前应由用户发送新消息取得新
  reply route；不要复用 2026-07-19 的旧 webhook，也不要直接对该 Job 执行 `--apply`。
