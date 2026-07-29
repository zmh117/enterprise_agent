# Agent Job Dispatch Outbox、重试与故障恢复

## 当前运行语义

Agent Job 与唯一 `job_dispatch_outbox` 事件在同一数据库事务中提交。API、Webhook、
DingTalk 和 Channel 入口都不直接发布 Agent Job RabbitMQ 消息。

```text
入口事务
  -> agent_job(PENDING / WAITING_INPUT)
  -> job_dispatch_outbox(PENDING)

独立 job-dispatch-worker
  -> 原子领取到期 Outbox
  -> RabbitMQ publisher confirm
  -> Outbox PUBLISHED

agent-worker
  -> 按 event_id 从 PostgreSQL 重读 event 和 Job
  -> 原子 claim Job
  -> RUNNING -> SUCCEEDED / RETRY_WAIT / FAILED / TIMEOUT
```

RabbitMQ Agent 消息只包含 `event_id`、`job_id`、`correlation_id`。Worker 必须核对三者
与 PostgreSQL 事实一致，不能把 RabbitMQ payload 当成执行参数。

## Outbox 不是 Job 执行租约

`job_dispatch_outbox` 只负责“已提交 Job 最终能发布到 RabbitMQ”。它不表示模型正在
执行，也不负责接管已经进入 `RUNNING` 的 Job。

- Outbox `RUNNING` 表示 Dispatcher 临时持有发布权；超过领取超时后可以恢复为
  `RETRY_WAIT` 或 `DEAD`。
- Job `RUNNING` 表示某个 Agent Worker 已原子领取执行权。
- 当前版本**不恢复 Worker 崩溃后遗留的 Job `RUNNING`**，也没有 Job 执行租约续期、
  抢占或自动回收。
- 重复 RabbitMQ 消息依靠持久化 Job 状态和原子 claim 防止重复执行；这不等于提供了
  `RUNNING` 崩溃恢复。

因此，状态页、验收报告和运行手册只能描述“Outbox 发布可恢复”和“重复消息执行幂等”，
不得写成“Agent 执行自动恢复”或“Outbox 是执行租约”。

## 重试与终态

可重试执行错误在一个数据库事务内完成：

1. Job 从 `RUNNING` 进入 `RETRY_WAIT`，增加 `retry_count` 并写入脱敏错误；
2. 同一个 Job Dispatch Outbox event 进入 `RETRY_WAIT`，按 `next_attempt_at` 到期；
3. Dispatcher 到期后重新发布主队列消息。

不再使用 Agent retry delay queue 或 Agent dead-letter queue 作为新运行路径。最终失败
直接持久化为 Job `FAILED` / `TIMEOUT`，并按 Delivery 状态机发送一次安全失败通知。

Broker 发布失败只改变 Outbox：

```text
PENDING / RETRY_WAIT -> RUNNING -> PUBLISHED
                              \-> RETRY_WAIT -> ... -> DEAD
```

发布 attempt 和运维 replay 都有持久化上限。错误摘要不得包含 URL 凭据、Token、
Secret、任意消息体或业务 payload。

## 只读状态、指标与有界 replay

精确查询一个事件：

```bash
.venv/bin/python -m app.cli.job_dispatch status --event-id EVENT_ID
.venv/bin/python -m app.cli.job_dispatch status --job-id JOB_ID
```

读取无事件 ID、Job ID 或 payload 的聚合指标：

```bash
.venv/bin/python -m app.cli.job_dispatch metrics
```

仅 DEAD Outbox event 且对应 Job 仍为 `PENDING` 时允许有界重放：

```bash
.venv/bin/python -m app.cli.job_dispatch replay \
  --event-id EVENT_ID \
  --actor-id OPERATOR_ID \
  --reason INCIDENT_TICKET
```

命令不接受自定义 payload。原因正文不写入数据库，只保存 SHA-256 digest；每个事件的
`replay_count` 不能超过 `max_replay_count`。Job `RUNNING`、`RETRY_WAIT`、终态 Job
以及非 DEAD Outbox 都不能通过这个命令改写。

## 旧队列一次性切换

切换前停止所有 Agent Job 入口、消费者和 Dispatcher，至少包括：

```bash
docker compose stop api-server agent-worker job-dispatch-worker \
  webhook-worker channel-dispatch-worker dingtalk-runtime
```

先执行 dry-run：

```bash
.venv/bin/python -m app.cli.job_dispatch_cutover
```

报告输出当前主队列、两个旧 retry queue、旧 dead queue 的精确名称和
`topology_digest`。旧消息按以下规则处理：

- 可确定 Job 且状态为 `PENDING` / `RETRY_WAIT`：回填或重置同一个 Outbox event；
- 已终态 Job 的重复消息：安全确认；
- 无效 JSON、缺少 Job、标识不匹配、`WAITING_INPUT` / `RUNNING` 或 DEAD event：
  只保存 source queue、SHA-256 digest 和原因到隔离清单，不保存原始 payload；
- 已是当前三标识契约的主队列消息：保留给 Agent Worker。

确认报告后，使用完全一致的 digest：

```bash
.venv/bin/python -m app.cli.job_dispatch_cutover \
  --apply \
  --confirm-topology-digest TOPOLOGY_DIGEST
```

只有扫描未截断、隔离清单为空、旧队列消息为 0 且 consumer 为 0 时，才允许删除工具
列出的精确旧队列：

```bash
.venv/bin/python -m app.cli.job_dispatch_cutover \
  --apply \
  --delete-empty-old-queues \
  --confirm-topology-digest TOPOLOGY_DIGEST
```

工具没有 queue pattern、payload override、purge 或通配删除参数。不得用
`rabbitmqctl purge_queue`、`*`、正则或前缀批量删除替代该流程。

## 旧数据库重试记录

旧版 `PENDING + retry_count>0` 或已到期 `RETRY_WAIT` 先 dry-run：

```bash
.venv/bin/python -m app.cli.reconcile_stranded_agent_retries --job-id JOB_ID
```

确认后执行：

```bash
.venv/bin/python -m app.cli.reconcile_stranded_agent_retries \
  --apply --job-id JOB_ID --actor-id OPERATOR_ID
```

该命令只把数据库事实转换为 `RETRY_WAIT + Job Dispatch Outbox`，不直接发布旧 retry
queue。对于 `RUNNING` Job，它只报告、不恢复。

## 验收边界

可以宣告：

- 已提交 Job 与唯一 Outbox 同事务存在；
- RabbitMQ 中断后 Outbox 有界退避并最终进入 DEAD；
- confirm 后崩溃可能产生重复消息，但已完成 Job 不会重复执行；
- 多 Dispatcher 使用 PostgreSQL `FOR UPDATE SKIP LOCKED`；
- DEAD replay 精确、有审计且有总次数上限。

不能宣告：

- 已经 `RUNNING` 的 Agent Job 会在 Worker 崩溃后自动恢复；
- `PUBLISHED` 等于 Agent 已执行或结果已投递；
- Outbox 替代了 Job 执行租约；
- 未运行切换工具就可以安全删除旧 RabbitMQ 对象。
