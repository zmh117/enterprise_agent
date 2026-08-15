# Legacy 042 升级、Baseline Adoption 与回滚

当前迁移代际以 `100_baseline_v1.sql` 为起点。新版本直接建库；旧数据库只有在账本精确到 `042` 且结构、约束、索引和 PostgreSQL 注释与不可变 manifest 一致时，才能只登记等价 marker。

## 固定升级顺序

Baseline adoption 必须按以下顺序执行，不得把容器 `healthy` 当作已完成接轨：

1. 停止入口并排空在途任务，再停止所有业务写入进程。
2. 创建 PostgreSQL custom-format 逻辑备份，校验文件 checksum，并在隔离数据库完成一次恢复演练。
3. 保留旧镜像、旧 Compose 配置、旧卷身份和备份；记录将部署镜像的非敏感 build/commit ID。
4. 用目标 migrator 镜像运行只读 preflight，保存 JSON 摘要。
5. 仅在 preflight 成功后运行一次 one-shot Migrator adoption。
6. 在业务服务仍停止时运行只读 verify，并与 preflight 的关键计数和 runtime config 摘要对账。
7. 执行管理员 bootstrap/runtime grant 等受控初始化，启动业务服务，检查 `/api/ready`。
8. 完成一次有审计证据的最小闭环后解除维护窗口。

迁移器和只读检查器使用 [`legacy-v1-manifest.json`](../../backend/migrations/legacy-v1-manifest.json) 验证旧 catalog、双数据库 schema fingerprint、PostgreSQL table/column comment digest 和关键表计数证据。任何不一致都会在 marker 写入前失败。preflight/verify 只输出计数、digest、版本和 build 身份，不输出业务行、Secret、Token、密码、DSN 或原始消息。

## 维护窗口、备份与恢复证据

先停止新的入口，确认队列已排空，再停止其余写进程。实际服务集合以 `docker compose config --services` 为准；当前 Compose 可使用：

```bash
docker compose stop api-server dingtalk-runtime admin-web
# 按部署的 RabbitMQ 监控确认 normal/retry 队列已排空
docker compose stop \
  agent-worker job-dispatch-worker delivery-dispatch-worker webhook-worker \
  channel-dispatch-worker file-worker \
  python-agent-runtime typescript-agent-runtime tool-mcp
```

保持 PostgreSQL 运行，使用基础设施脚本创建逻辑备份：

```bash
scripts/compose_infra_upgrade.sh backup-postgres
```

将输出的 `BACKUP_DIR` 记录到变更单。至少确认 `enterprise_agent.dump`、`before-metrics.tsv` 和 `metadata.txt` 存在且非空，并核对 `metadata.txt` 中记录的 checksum。备份包含业务数据和加密后的 platform secret，仍属于敏感业务备份，不得提交仓库或附加到普通日志。

成功验收前，必须在与当前数据卷隔离的 disposable PostgreSQL 数据库实际执行 `pg_restore` 并核对 `before-metrics.tsv`；仅运行 `pg_restore --list` 不等同于恢复演练。不得以恢复演练覆盖当前 Compose 数据库。

记录旧镜像 digest、旧卷名称和当前部署配置。禁止执行 `docker compose down -v`，禁止删除旧卷、旧镜像或逻辑备份。

## 001–041 数据库

当前镜像不直接接受部分 legacy head。先用包含原 001–042 链的旧应用镜像把数据库升级到精确 `042`，完成备份与校验后，再切换当前镜像进行 adoption。不要复制已删除 SQL 到当前活动目录，也不要手工补 `042` 账本行。

## 精确 042 Preflight 与 Adoption

build 身份只能使用 release/commit 等非敏感标识：

```bash
export MIGRATOR_BUILD="$(git rev-parse --verify HEAD)"
docker compose build migrator
docker compose run --rm --no-deps migrator \
  python -m app.cli.baseline_adoption preflight --build "$MIGRATOR_BUILD" \
  | tee .local/baseline-adoption-preflight.json
```

成功输出必须包含 `status=ready-for-adoption`、`source_head=042`、`target_baseline=100`、目标 baseline checksum、schema/comment digest、关键表计数 digest、runtime config revision 摘要和期望 build。该命令不得创建缺失的 ledger/adoption 表，也不得登记 marker。

确认业务写入仍停止、恢复演练成功且 preflight JSON 已保存后，执行唯一获准写 migration ledger 的命令：

```bash
docker compose run --rm --no-deps migrator \
  python -m app.cli.migrate --build "$MIGRATOR_BUILD"
```

迁移器不重放 baseline DDL，不删除或改写业务数据；它在一个事务中追加 `schema_migration.version=100` 和一行 `schema_baseline_adoption`。合法账本形态为 `001..042,100[,101...]`。重复运行幂等退出。禁止手工 INSERT/UPDATE/DELETE migration ledger、覆盖 checksum 或伪造 adoption metadata。

## Adoption 后只读验收与启动

业务服务仍保持停止，执行：

```bash
docker compose run --rm --no-deps migrator \
  python -m app.cli.baseline_adoption verify --build "$MIGRATOR_BUILD" \
  | tee .local/baseline-adoption-verify.json
```

成功输出必须包含 `status=adoption-verified`、`schema_head=100`、唯一 marker、唯一 metadata、与 adoption 时一致的关键表计数、runtime config revision 摘要，以及 `business_start_gate=schema-verified`。preflight 与 verify 之间只有 marker/metadata 可以变化；关键业务计数、schema/comment fingerprint 和 runtime config 摘要必须一致。

然后执行 Compose 原有受控 bootstrap/grant，并启动服务：

```bash
docker compose up --force-recreate migrator
docker compose up -d \
  tool-mcp python-agent-runtime typescript-agent-runtime \
  api-server agent-worker job-dispatch-worker delivery-dispatch-worker \
  webhook-worker channel-dispatch-worker file-worker dingtalk-runtime admin-web
curl --noproxy '*' -fsS http://127.0.0.1:8000/api/ready
```

`/api/ready` 必须同时报告 schema current，runtime config 不得因缺失 definition 处于 degraded。若受控初始化确实创建了缺失 definition，记录初始化前后的不透明 revision/hash；随后连续两次读取 snapshot/ready 时 revision/hash 必须稳定且不得新增配置审计。

最后完成一次符合该环境业务验收脚本的最小闭环，至少形成 `ingress/inbox -> outbox -> queue -> job/worker -> delivery/audit` 的同一 correlation 证据。不得只检查容器状态或只证明消息进入队列。

## 回滚边界

如果只完成 adoption 且没有应用任何 `101+` migration，且 verify 或最小闭环失败，可以在业务写入仍停止时受控移除 marker 和 metadata：

```bash
docker compose run --rm migrator \
  python -m app.cli.rollback_baseline_adoption
```

该命令不修改业务 schema 或数据，账本恢复到 `042`，随后才能回退旧镜像。fresh `100` 数据库不能使用此命令。回滚后仍须保留失败证据和备份，先定位验收失败原因，不能直接重试或手工修 ledger。

一旦应用 `101+`，禁止 marker-only rollback。应用镜像可以按兼容策略回退，但 schema 回退必须使用维护窗口前已演练的逻辑备份恢复到隔离的新数据库/卷，再切换旧镜像；或使用经过评审的 forward-fix migration。不能删除账本行、伪造 checksum 或手工逆向 DDL。

只有 `/api/ready` 与最小闭环均通过、验收记录完成后，才可按独立保留策略清理旧镜像、旧卷或备份；本 Runbook 不授权自动清理。

## 故障排查

- `current head is 001..041`：先用旧镜像升级到 042。
- `checksum or identity`：旧 SQL/账本已漂移；恢复可信备份或调查来源，不要覆盖 checksum。
- `schema fingerprint`：结构、约束或索引与 042 不一致；在备份副本定位差异。
- `PostgreSQL comments`：表/字段注释缺失或被修改；按可信 042 schema 修复后重试。
- `retained-data counts changed before verification`：维护窗口内仍有写入或数据被修改；保持服务停止，调查后按 adoption-only rollback 或备份恢复边界处理。
- `migrator build does not match`：preflight、adoption、verify 使用了不同构建；禁止继续启动服务。
- `non-empty schema has no migration ledger`：来源不可信，禁止自动 baseline。
- bootstrap 失败：按 [空库与初始管理员手册](schema-baseline-bootstrap.md) 修复 Secret 输入；不要跳过步骤启动业务服务。

Compose 基础设施备份、卷与 PostgreSQL 18 恢复流程见 [Compose 升级手册](compose-postgres18-rabbitmq4-upgrade.md)。
