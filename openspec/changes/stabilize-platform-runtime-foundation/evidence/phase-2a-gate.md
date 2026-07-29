# Phase 2A Gate：独立 Migrator 与操作级 Unit of Work

记录时间：2026-07-29T03:21:10+08:00  
结果：PASS

本文件只验收任务 3.1–3.9。Gate 2 的最终证据
`gate-2-transactional-runtime.md` 仍需等待 Phase 2B/2C 的 Job 与 Delivery
双 Outbox 完成后生成，不得用本次 PASS 代替整个 Gate 2。

## 代码与 migration

- 分支：`master`
- 基线 commit：`debb504`
- worktree：dirty（本 OpenSpec change 与用户原有未提交改动并存，未执行
  reset/checkout）
- 源码 migration head：`018_runtime_session_isolation.sql`
- head migration SHA-256：
  `1f46be4f0aa62d15af03e2ee44c49c5391d684302f8d0e6f7ddebc7c9ce67d62`
- migration catalog 共 19 个唯一 version，实际 PostgreSQL 账本只读结果为：
  `count=19, min=001, max=018, distinct_version=19`

## 自动化 Gate

```bash
MIGRATION_POSTGRES_DSN='<本机 PostgreSQL 管理连接，未记录>' \
  .venv/bin/python scripts/runtime_foundation_gate.py verify-phase2a
```

结果：`41 passed`，`PHASE_2A_AUTOMATED_GATE: PASS`。固定测试清单覆盖：

- migration version/checksum catalog 和 legacy checksum 账本基线；
- one-shot Migrator、PostgreSQL advisory lock 和幂等重跑；
- 两个并发 Migrator 作用于新数据库时只有一个应用 migration，另一个为 no-op；
- checksum 漂移、重复 version 和中途失败时阻止后续版本；
- 失败 migration 的 schema 与账本同行回滚，修复后可重跑；
- API、Agent/Webhook/Channel/Attachment Worker、正式和本地 Internal API
  Platform 缺失 schema head 时只读拒绝启动，不执行 migration；
- PostgreSQL 连接池并发事务中提交与回滚相互隔离，连接最终全部归还；
- 嵌套 UoW/savepoint、异常回滚和 ContextVar 隔离；
- 模型、HTTP、RabbitMQ、工具数据库/Redis/Loki、DingTalk 和对象存储不得在
  平台数据库 UoW 内执行外部 I/O；
- Compose 业务服务必须等待 one-shot Migrator 成功退出。

```bash
.venv/bin/pytest -q
```

结果：`500 passed, 17 skipped, 1 xfailed, 2 warnings, 4 subtests passed`。
两个 warning 分别是既有 Starlette TestClient 弃用提示和既有 pytest
return-not-none 提示，无失败。未设置真实 PostgreSQL连接的普通全量测试会跳过
5 项 PostgreSQL integration；上面的 `verify-phase2a` 已单独强制执行并通过，
因此没有把 skip 计作 Gate 通过。

```bash
.venv/bin/ruff check backend/app backend/tests scripts/runtime_foundation_gate.py
git diff --check
```

结果：均通过。

## 本地 Compose 与数据只读核验

当前 worktree 的 Migrator、API、正式/本地 Internal API Platform 和四类 Worker
镜像已重建，镜像依赖包含 `psycopg-pool 3.3.1`。首次构建因宿主机
`127.0.0.1` 代理地址无法在构建容器内访问而失败；清空仅本次构建进程的代理变量后
重试成功，未修改仓库代理配置。

启动使用同一组仅存在于命令进程中的临时 Internal API current Token；未写入
`.env`、仓库、日志或本证据。重建后的只读结果：

- Migrator：`Exited (0)`；
- Migrator 日志：`MIGRATION_SUCCEEDED: head=018 baselined=0 applied=-`；
- `api-server`：healthy，`/api/health` 返回 `status=ok`；
- `local-internal-api-platform`：`/health` 返回 `status=ok`；
- PostgreSQL、RabbitMQ、MinIO：healthy；
- 正式 Internal API Platform、Agent Worker、Webhook Worker、Channel Dispatcher、
  Attachment Worker：running，其中声明 healthcheck 的服务均 healthy；
- `api-server`、两个 Internal API Platform 和四类 Worker 在各自容器内只读校验
  schema head，结果全部为 `018`；
- migration 账本为 19 条唯一 version，范围 `001` 至 `018`。

`local-internal-api-platform` 已补齐与其他数据库相关业务服务相同的启动时 schema
head 校验；它只读取/应用运行配置，不取得 migration writer 权限。

## 本阶段明确边界

- 已实现：唯一 schema writer、服务启动只读 head 校验、同步连接池、操作级 UoW、
  事务与外部 I/O 边界。
- 未实现：Job Dispatch Outbox（Phase 2B）和 Delivery Outbox（Phase 2C）；
  当前 PASS 不声称已消除 Job/RabbitMQ 或结果/Delivery 的双写窗口。
- 已进入 `RUNNING` 后 Worker 崩溃的租约/fencing 仍按设计延期。
- 真实 Oracle 11.2.0.4 连接测试 deferred；本次只证明 Internal API Platform
  镜像及 Oracle Client 层可以构建，不声称 Oracle 实库可用。
- HTTPS/HMAC 和公网生产安全不属于本阶段，也未实现。
