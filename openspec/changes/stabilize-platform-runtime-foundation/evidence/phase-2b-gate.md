# Phase 2B Gate：Job Dispatch Outbox

记录时间：2026-07-29T04:12:37+08:00  
结果：PASS

本文件只验收任务 4.1–4.10。Gate 2 的最终证据
`gate-2-transactional-runtime.md` 仍需等待 Phase 2C Delivery Outbox 完成后生成；
不得用本次 PASS 代替整个 Gate 2。

## 代码与 migration

- 分支：`master`
- 基线 commit：`debb504`
- worktree：dirty（本 OpenSpec change 与用户原有未提交改动并存，未执行
  reset/checkout）
- 源码与本地 Compose PostgreSQL migration head：`019`
- `019_job_dispatch_outbox.sql` SHA-256：
  `38be9470f25c7b34febfde0096eef6aa6756928d3025383037af084b4fd9d2df`
- PostgreSQL migration 账本：20 个唯一 version，范围 `001` 至 `019`

## 固定自动化 Gate

```bash
MIGRATION_POSTGRES_DSN='<本机 PostgreSQL 管理连接，未记录>' \
RABBITMQ_TEST_URL='<本机 RabbitMQ 连接，未记录>' \
  .venv/bin/python scripts/runtime_foundation_gate.py verify-phase2b
```

结果：`34 passed`，`PHASE_2B_AUTOMATED_GATE: PASS`。命令缺少任一真实依赖
连接时直接失败，不能把 integration skip 当作 Gate 通过。固定清单证明：

- Job、消息、授权快照、审计和唯一 Job Dispatch Outbox event 同一 UoW 提交；
- PostgreSQL 两个 Dispatcher 使用 `FOR UPDATE ... SKIP LOCKED` 并发领取 40 个
  event，无重复 claim；
- RabbitMQ 4.3.2 publisher confirm 发送持久化的三标识消息；
- RabbitMQ 中断前已提交的 Job/Event 保持可恢复；持续失败在固定第 2 次尝试后
  进入持久化 `DEAD`；
- confirm 后、Outbox 状态写回前崩溃会安全重发；重复 event/message 只产生一个
  Worker claim、一个模型调用和一个业务结果；
- confirm 与 `PUBLISHED` 均持久化后崩溃不会重发；
- Worker 执行失败通过同一 Outbox event 有限重试，终态写入 Job/Audit，不再使用
  Agent retry/dead RabbitMQ queue；
- DEAD replay 按 event/job 精确定位，受 `max_replay_count` 限制，拒绝任意 payload；
- 切换工具只接受精确旧队列，无法转换的消息只保存摘要到 quarantine。

真实组合测试为每次运行创建临时 PostgreSQL 数据库和随机 RabbitMQ 隔离队列，
执行 migration/seed 后验证完整链路，并在结束时删除临时数据库和队列；没有污染
常驻业务库，也没有向日志或证据写入连接信息。

## 全量与静态回归

```bash
.venv/bin/pytest -q
```

结果：`526 passed, 18 skipped, 2 warnings, 4 subtests passed`。两个 warning 为既有
Starlette TestClient 弃用提示和既有 pytest return-not-none 提示，无失败。普通
全量测试未配置真实依赖时会跳过 opt-in integration；上面的固定 Gate 已强制执行
真实 PostgreSQL/RabbitMQ 测试。

```bash
.venv/bin/ruff check backend/app backend/tests scripts/runtime_foundation_gate.py
git diff --check
docker compose config --quiet
```

结果：均通过。

## Compose 迁移与运行态

后端 Migrator、API、Agent Worker、Job Dispatcher、Webhook/Channel/Attachment
Worker 和 Internal API Platform 镜像均由当前 worktree 重建。宿主机代理指向
容器不可访问的回环地址，构建时只清空该命令进程的代理变量，未修改仓库或宿主机
代理配置。

切换时先停止旧业务容器，再执行 one-shot Migrator：

```text
MIGRATION_SUCCEEDED: head=019 baselined=0 applied=019
MIGRATION_SUCCEEDED: head=019 baselined=0 applied=-
```

第二行来自服务启动依赖对同一 Migrator 的幂等重跑。启动时使用同一组只存在于
命令进程和容器 secret file 的临时 Internal API current Token；未写入 `.env`、
仓库、本证据或应用日志。

运行态只读结果：

- `api-server` healthy，`/api/health` 返回
  `{"status":"ok","claude_invoked":false}`；
- `job-dispatch-worker` healthy，心跳持续更新；
- Agent、Webhook、Channel、Attachment Worker 均 running；声明 healthcheck 的
  Dispatcher 均 healthy；
- PostgreSQL、RabbitMQ、MinIO 和 DingTalk Runtime healthy；
- API、Agent Worker、Job Dispatcher、Webhook/Channel/Attachment Worker、
  Internal API Platform 在各自容器内执行只读 `SchemaHeadValidator`，全部返回
  `019`；
- 常驻数据库现有 18 个 Job 全部为 `SUCCEEDED`；
- `PENDING/RETRY_WAIT` 且缺少 Dispatch Outbox 的 Job 数量为 0；
- 常驻 `job_dispatch_outbox` 与 cutover quarantine 当前均为 0 条，这是无待调度
  Job 的正常空闲状态。

RabbitMQ 4.3.2 当前 Job 路径：

| queue | ready | unacked | consumers |
|---|---:|---:|---:|
| `agent.job.queue` | 0 | 0 | 1 |
| `agent.job.retry.delay.v1.queue` | 0 | 0 | 0 |
| `agent.job.dead.queue` | 0 | 0 | 0 |

新代码只声明和消费 `agent.job.queue`。两个旧队列为空且无消费者，但本次没有删除；
精确旧拓扑删除属于任务 10.5 的破坏性维护操作，必须在新鲜清单/digest 和再次用户
确认后执行。

Internal API Platform `/health` 当前为 `degraded`，原因是数据库中既有旧工具资源
缺少新 contract 的必填字段。该状态未影响 Job Dispatch Outbox、PostgreSQL 或
RabbitMQ Gate；资源清空与按新 contract 重配属于后续 Phase 4/5。本文不把
Internal API Platform 描述为 ready。

## 本阶段明确边界

- 已实现并证明：已提交 Job 不因 RabbitMQ 中断丢失；Dispatcher 多副本安全领取；
  publisher confirm；有限退避/DEAD；有界 replay；重复 event 不重复业务结果；
  运行态独立 Dispatcher 和主队列单消费者。
- 未实现：Delivery Outbox（Phase 2C）。Job 成功后的投递独立恢复尚不能作为本次
  Gate 的能力声明。
- 已进入 `RUNNING` 后 Worker 崩溃的租约/fencing 仍按设计延期；Outbox 不是执行
  lease。
- 本次真实组合测试使用 Stub Agent，不声称完成真实模型、工具、Grafana 或
  DingTalk 外部链路验收；这些属于 Phase 6。
- 旧 retry/dead 队列只是不再使用，并未在本阶段删除。
