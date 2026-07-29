# Phase 0 RabbitMQ 精确拓扑与路径分类

记录日期：2026-07-28  
记录范围：任务 1.4，只读检查当前 RabbitMQ 和代码装配；未声明、清空、删除或
重绑定任何 RabbitMQ 对象。

## 可重复命令

```bash
docker compose exec -T rabbitmq rabbitmqctl list_exchanges -q \
  name type durable auto_delete internal arguments
docker compose exec -T rabbitmq rabbitmqctl list_queues -q \
  name messages_ready messages_unacknowledged consumers durable auto_delete arguments
docker compose exec -T rabbitmq rabbitmqctl list_bindings -q \
  source_name source_kind destination_name destination_kind routing_key arguments
docker compose exec -T rabbitmq rabbitmqctl list_consumers -q \
  queue_name channel_pid consumer_tag ack_required prefetch_count active activity_status
```

代码定位：

```bash
grep -R \
  "agent\\.job\\.\\|webhook\\.dispatch\\|channel\\.dispatch\\|attachment\\.queue" \
  -n backend/app docker-compose.yml
```

## Exchange

当前没有自定义业务 exchange。业务消息全部通过 RabbitMQ 默认 exchange：

| Exchange | Type | Durable | Auto-delete | Internal | 分类 |
|---|---|---:|---:|---:|---|
| `""` | direct | true | false | false | 当前业务路径 |

其余仅为 RabbitMQ 内建的 `amq.direct`、`amq.fanout`、`amq.headers`、
`amq.match`、`amq.rabbitmq.log`、`amq.rabbitmq.trace`、`amq.topic`；
当前业务队列没有绑定到这些 exchange。

## Queue、消息和参数

快照时全部业务队列 `ready=0`、`unacked=0`。

| Queue | Consumer | Durable | DLX / routing key | 分类 |
|---|---:|---:|---|---|
| `agent.job.queue` | 1 | true | - | 当前 Job 执行 |
| `agent.job.retry.delay.v1.queue` | 0 | true | `""` → `agent.job.queue` | 当前 Job 延迟重试 |
| `agent.job.dead.queue` | 0 | true | - | 当前 Job dead-letter 归档 |
| `agent.webhook.dispatch.queue` | 1 | true | `""` → `agent.webhook.dispatch.dead.queue` | 当前 Webhook Inbox dispatch |
| `agent.webhook.dispatch.dead.queue` | 0 | true | - | 当前 Webhook dead-letter |
| `agent.channel.dispatch.queue` | 1 | true | `""` → `agent.channel.dispatch.dead.queue` | 当前 Channel Inbox dispatch |
| `agent.channel.dispatch.dead.queue` | 0 | true | - | 当前 Channel dead-letter |
| `agent.attachment.queue` | 1 | true | - | 当前 attachment |
| `agent.attachment.retry.queue` | 0 | true | `""` → `agent.attachment.queue` | 当前 attachment 延迟重试 |
| `agent.attachment.dead.queue` | 0 | true | - | 当前 attachment dead-letter |

所有队列 `auto_delete=false`、queue type 为 classic。

## Binding

10 个业务队列都只有 RabbitMQ 默认 exchange 自动提供的同名 binding：

```text
source="" exchange -> destination=<queue> queue
routing_key=<queue>
arguments=[]
```

没有业务 exchange-to-exchange binding，也没有额外 routing key binding。

## Consumer

| Queue | Ack | Prefetch | Active | Activity | 代码/服务归属 |
|---|---:|---:|---:|---|---|
| `agent.job.queue` | true | 1 | true | up | `RabbitMQConsumer.consume_agent_jobs` / `agent-worker` |
| `agent.webhook.dispatch.queue` | true | 1 | true | up | `RabbitMQConsumer.consume_webhook_events` / `webhook-worker` |
| `agent.channel.dispatch.queue` | true | 1 | true | up | `RabbitMQConsumer.consume_channel_events` / `channel-dispatch-worker` |
| `agent.attachment.queue` | true | 1 | true | up | `RabbitMQAttachmentConsumer` / `attachment-worker` |

consumer tag 和 channel PID 是连接级瞬时值，重连会变化，不能作为稳定标识。

## 当前发布与消费路径

`RabbitMQPublisher` 当前统一使用 `exchange=""` 和 queue name routing key，
并在 Job、Webhook、Channel 主路径开启 publisher confirm。消息只携带对象 ID
和 correlation ID；dead-letter 额外携带安全原因摘要。

当前直接发布调用点：

- 创建 Job 提交后直接 `publish_agent_job`
- attachment 准备完成后直接 `publish_agent_job`
- Job retry/recovery 直接 `publish_retry`
- Webhook Inbox 创建后直接 `publish_webhook_event`
- Channel Inbox 创建后直接 `publish_channel_event`
- attachment 创建/重试直接 publish

这些是“当前在用”路径，但 Job 创建后的直接 publish 同时也是本次要移除的
pre-Outbox 双写窗口。现场为空只能证明当前无 backlog，不能证明 DB/Rabbit
原子性。

消费者成功后 explicit ack；Job、Webhook、Channel handler 抛错时 nack/requeue。
attachment consumer 当前没有相同的异常捕获包装，handler 异常会退出连接，由未
ack 消息重新入队。

## 遗留路径

| 对象 | 配置/代码 | 现场 | Consumer | 结论 |
|---|---|---|---|---|
| `agent.job.retry.queue` | `legacy_retry_queue` 和管理状态 allowlist 仍存在 | queue 不存在 | 0 | 纯遗留兼容配置 |

`rabbitmq_topology.py` 已明确不声明该不兼容 legacy queue。后续切换工具仍必须按
精确名称检查它是否在切换时重新出现，不能因为本次不存在就使用通配删除。

## Outbox 目标路径

### Job Dispatch Outbox

- API/Ingress 事务只写 Job + 唯一 Outbox event，不直接连接 RabbitMQ。
- 独立 Dispatcher 是 Job 创建路径唯一 RabbitMQ publisher。
- 首期继续使用当前 `agent.job.queue` 和默认 exchange，降低拓扑切换风险。
- payload 收敛为 `event_id`、`job_id`、`correlation_id`；Worker 按 ID 从
  PostgreSQL 重读固化执行事实。
- retry/DEAD 的权威状态在 PostgreSQL；Rabbit retry/DLQ 仅是传输辅助和切换观测，
  不再是唯一事实。

### Delivery Outbox

- 当前没有 `agent.delivery.*` queue、binding 或 consumer。
- Delivery event 先在 PostgreSQL 原子创建，再由独立 Dispatcher 发布。
- 精确 queue 名、DLX 参数和消费者在 Phase 2C 实现时随 schema/装配一起定义，
  不能把当前 `agent.channel.dispatch.queue` 冒充为 Delivery Outbox。

### 切换规则

- 切换前重新执行本文件命令，生成 queue/exchange/binding/consumer/message digest。
- 对旧 pending/retry 只做 dry-run、精确 backfill 或 quarantine。
- 必须先证明旧对象 `ready=0`、`unacked=0`、consumer=0，再按精确名称删除。
- 禁止 `rabbitmqctl purge_queue` 或通配删除作为常规迁移手段。

## 结论

- 现场没有积压消息，具备后续建立 Outbox 的干净基线，但这不是切换授权。
- 当前 Job 创建仍存在 PostgreSQL commit 后直接 RabbitMQ publish 的双写窗口。
- 唯一确认的 RabbitMQ 遗留对象是“配置中存在、现场不存在”的
  `agent.job.retry.queue`。
- Job Outbox 可复用当前 Job queue；Delivery Outbox 当前完全不存在，后续不能误报
  为已实现。
