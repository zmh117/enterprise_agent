# Phase 2C Gate：Delivery Outbox 与独立状态机

## 验收范围

- Agent Job 终态与 Delivery intent 同事务持久化，外部 adapter 不在该事务内调用。
- Delivery event、attempt、chunk 使用独立有限状态机和稳定幂等键。
- Job `SUCCEEDED` 只代表结果已持久化，不代表外部结果已送达。
- 多 Dispatcher 使用 PostgreSQL `FOR UPDATE SKIP LOCKED` 领取，不重复发送。
- RabbitMQ 中断恢复、重复 Job event、Delivery 分片中断、DEAD 和有限 replay。
- replay 只接受精确 `delivery_id`，复用固化 binding、脱敏目标摘要和原结果 artifact。
- Job 详情 API/前端展示独立 Delivery 时间线；只有 Delivery `SUCCEEDED` 显示“已送达”。

## 固定自动化 Gate

命令：

```bash
MIGRATION_POSTGRES_DSN='<local-postgres-admin-dsn>' \
RABBITMQ_TEST_URL='<local-rabbitmq-url>' \
.venv/bin/python scripts/runtime_foundation_gate.py verify-phase2c
```

结果：

```text
25 passed, 1 warning
PHASE_2C_AUTOMATED_GATE: PASS
```

固定目标覆盖：

- Delivery schema、原子终态、Dispatcher、chunk 幂等和安全运维 CLI。
- 管理 API 的脱敏时间线与只读聚合指标。
- PostgreSQL 多 Dispatcher `SKIP LOCKED`。
- PostgreSQL + RabbitMQ 4 的真实中断恢复、重复消费、DEAD 与 replay 链路。

## 全量回归

```text
backend: 558 passed, 11 skipped, 2 warnings, 4 subtests passed
frontend: 10 files passed, 45 tests passed
ruff: All checks passed
frontend build: passed
docker compose config --quiet: passed
git diff --check: passed
```

已知非阻断告警：

- Starlette `TestClient` 的上游弃用提醒。
- 一个既有 Pytest 测试函数返回 `Settings` 的提醒。
- 前端主 bundle 大于 500 kB 的构建提醒。

## 本地 Compose 运行时证据

- Migrator 首次应用结果：`MIGRATION_SUCCEEDED: head=020 baselined=0 applied=020`。
- Compose 再启动校验：`MIGRATION_SUCCEEDED: head=020 baselined=0 applied=-`。
- `api-server` 健康：`{"status":"ok","claude_invoked":false}`。
- `delivery-dispatch-worker` 已启动且健康，日志包含：

```text
Delivery outbox worker starting
Delivery outbox scan succeeded=0 skipped=1 retrying=0 failed=0 dead=0 recovered=0
```

- 创建一个 `route=none` 的 Compose 验收 Job，并由实际运行的
  Job Dispatcher、RabbitMQ、Agent Worker 和 Delivery Worker 处理：

```text
job_b7b6287810234355a30ee9a40f538b0c|SUCCEEDED|SKIPPED|1
```

这条记录证明 Agent Job 成功与 Delivery 终态分别持久化；`SKIPPED`
不会被标记为“已送达”，也没有重跑 Agent。

- Delivery 聚合指标在验收后为：

```json
{
  "active_count": 0,
  "counts": {
    "DEAD": 0,
    "FAILED": 0,
    "PENDING": 0,
    "RETRY_WAIT": 0,
    "RUNNING": 0,
    "SKIPPED": 1,
    "SUCCEEDED": 0
  },
  "terminal_failure_count": 0
}
```

- RabbitMQ 主队列均无积压；`agent.job.queue` 有一个消费者，
  Webhook、Channel 和 Attachment 队列也各有一个消费者。

## 结论

Phase 2C Gate 通过。Delivery 故障不会改变 Agent Job 成功状态或重新执行
Agent；投递意图、尝试、分片、DEAD 与 replay 均可独立审计和恢复。
