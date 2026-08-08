# Phase 0 基线

记录日期：2026-07-28  
记录范围：任务 1.1，仅执行只读检查、测试和构建；未修改运行中容器或数据库。

## 可重复命令

### 后端

```bash
.venv/bin/python -m compileall -q backend/app
.venv/bin/pytest -q
```

基线结果：

- Python compileall：通过。
- pytest：`405 passed, 12 skipped, 2 warnings, 4 subtests passed in 39.83s`。
- warning：
  - Starlette TestClient 的 httpx 兼容性弃用提示。
  - `backend/tests/test_feature_configuration.py::test_settings` 返回对象而不是使用 assert。

### 前端

```bash
cd frontend
npm run lint
npm test -- --run
npm run build
```

基线结果：

- ESLint：通过。
- Vitest：`10 passed` test files，`44 passed` tests。
- TypeScript + Vite production build：通过。
- 非阻塞 warning：主 JavaScript chunk 约 812.76 kB，超过 Vite 500 kB 提示阈值。

### Compose 服务

```bash
docker compose config --services
docker compose ps --format json
```

默认 Compose 定义服务：

- `rabbitmq`
- `postgres`
- `webhook-worker`
- `minio`
- `minio-init`
- `attachment-worker`
- `channel-dispatch-worker`
- `api-server`
- `dingtalk-runtime`
- `admin-web`
- `agent-worker`
- `internal-api-platform`

检查时核心服务均处于 running；`postgres`、`rabbitmq`、`minio`、`api-server`、`dingtalk-runtime`、`webhook-worker`、`channel-dispatch-worker` 为 healthy。另有此前启动的测试 Profile 容器仍在运行：MySQL、SQL Server 及两套隔离 Redis，均为 healthy。本基线未启动、停止或重建任何容器。

### Migration

```bash
find backend/migrations -maxdepth 1 -type f -name '*.sql' -print | sort
docker compose exec -T postgres psql -U enterprise_agent -d enterprise_agent -Atc \
  "select table_name from information_schema.tables where table_schema='public' and table_name like '%migration%' order by table_name"
```

基线结果：

- 代码 migration 文件覆盖 `001` 至 `017`。
- 存在重复版本：
  - `009_admin_web_read_models.sql`
  - `009_agent_job_retry_failure_delivery.sql`
- 当前数据库不存在权威 `schema_migration` 账本，只有业务用途的 `identity_migration_audit`。
- 因无 migration ledger/checksum，当前数据库的“已应用 head”无法被可靠查询；只能观察代码最高文件名为 `017`，不能据此声明数据库已达到 `017`。

### RabbitMQ 精确拓扑

```bash
docker compose exec -T rabbitmq rabbitmqctl list_exchanges -q \
  name type durable auto_delete internal arguments
docker compose exec -T rabbitmq rabbitmqctl list_queues -q \
  name messages_ready messages_unacknowledged consumers durable arguments
docker compose exec -T rabbitmq rabbitmqctl list_bindings -q \
  source_name source_kind destination_name destination_kind routing_key
docker compose exec -T rabbitmq rabbitmqctl list_consumers -q \
  queue_name channel_pid consumer_tag ack_required prefetch_count active
```

业务队列基线：

| Queue | Ready | Unacked | Consumers |
|---|---:|---:|---:|
| `agent.job.queue` | 0 | 0 | 1 |
| `agent.job.retry.delay.v1.queue` | 0 | 0 | 0 |
| `agent.job.dead.queue` | 0 | 0 | 0 |
| `agent.webhook.dispatch.queue` | 0 | 0 | 1 |
| `agent.webhook.dispatch.dead.queue` | 0 | 0 | 0 |
| `agent.channel.dispatch.queue` | 0 | 0 | 1 |
| `agent.channel.dispatch.dead.queue` | 0 | 0 | 0 |
| `agent.attachment.queue` | 0 | 0 | 1 |
| `agent.attachment.retry.queue` | 0 | 0 | 0 |
| `agent.attachment.dead.queue` | 0 | 0 | 0 |

当前业务队列全部为空，4 个活跃消费者的 prefetch 均为 1。本文件只记录事实；旧/当前/目标 Outbox 拓扑分类由任务 1.4 单独完成。
