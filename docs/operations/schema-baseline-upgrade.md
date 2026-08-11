# Legacy 042 升级、Baseline Adoption 与回滚

当前迁移代际以 `100_baseline_v1.sql` 为起点。新版本直接建库；旧数据库只有在账本精确到 `042` 且结构、约束、索引和 PostgreSQL 注释与不可变 manifest 一致时，才能只登记等价 marker。

## 升级前置检查

1. 停止业务写入或进入已验证的维护窗口。
2. 创建可恢复的 PostgreSQL 逻辑/物理备份，并在隔离库验证恢复。
3. 记录关键业务表计数或业务认可的 hash；至少覆盖用户、外部身份、RBAC、Agent/Application Publication、Connector 和 Resource。
4. 查询 `schema_migration`，必须是无空洞、无重复、checksum 未漂移的精确 `001..042`。
5. 保留当前旧镜像和部署配置；不要先删除数据库卷。

迁移器会使用 [`legacy-v1-manifest.json`](../../backend/migrations/legacy-v1-manifest.json) 自动验证旧 catalog、双数据库 schema fingerprint、PostgreSQL table/column comment digest 和关键表计数证据。任何不一致都会在 marker 写入前失败。

## 001–041 数据库

当前镜像不直接接受部分 legacy head。先用包含原 001–042 链的旧应用镜像把数据库升级到精确 `042`，完成备份与校验后，再切换当前镜像进行 adoption。不要复制已删除 SQL 到当前活动目录，也不要手工补 `042` 账本行。

## 精确 042 Adoption

```bash
docker compose build migrator
docker compose run --rm migrator python -m app.cli.migrate
```

迁移器不重放 baseline DDL，不删除或改写业务数据；它在一个事务中追加 `schema_migration.version=100` 和一行 `schema_baseline_adoption`。合法账本形态为 `001..042,100[,101...]`。重复运行幂等退出。

## 回滚边界

如果只完成 adoption 且没有应用任何 `101+` migration，可以受控移除 marker 和 metadata：

```bash
docker compose run --rm migrator \
  python -m app.cli.rollback_baseline_adoption
```

该命令不修改业务 schema 或数据，账本恢复到 `042`，随后才能回退旧镜像。fresh `100` 数据库不能使用此命令。

一旦应用 `101+`，禁止 marker-only rollback。应用镜像可以按兼容策略回退，但 schema 回退必须走已演练的备份恢复或专门的 forward-fix migration，不能删除账本行、伪造 checksum 或手工逆向 DDL。

## 故障排查

- `current head is 001..041`：先用旧镜像升级到 042。
- `checksum or identity`：旧 SQL/账本已漂移；恢复可信备份或调查来源，不要覆盖 checksum。
- `schema fingerprint`：结构、约束或索引与 042 不一致；在备份副本定位差异。
- `PostgreSQL comments`：表/字段注释缺失或被修改；按可信 042 schema 修复后重试。
- `non-empty schema has no migration ledger`：来源不可信，禁止自动 baseline。
- bootstrap 失败：按 [空库与初始管理员手册](schema-baseline-bootstrap.md) 修复 Secret 输入；不要跳过步骤启动业务服务。

Compose 基础设施备份、卷与 PostgreSQL 18 恢复流程见 [Compose 升级手册](compose-postgres18-rabbitmq4-upgrade.md)。
