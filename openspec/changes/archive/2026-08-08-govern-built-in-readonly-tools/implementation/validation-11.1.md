# 11.1 严格校验与迁移恢复证据

执行日期：2026-08-06（Asia/Shanghai）

本文件只记录命令、计数、schema head 和安全结果，不记录 Secret、连接地址、业务消息或工具响应正文。

## OpenSpec 与静态检查

- `openspec validate govern-built-in-readonly-tools --type change --strict --no-interactive`
  - 结果：通过，change valid。
- `.venv/bin/python -m ruff check backend/app backend/tests`
  - 结果：通过，`All checks passed!`。

## 后端测试

- `.venv/bin/pytest -q backend/tests`
  - 最终全量回归结果：`947 passed, 23 skipped, 18 subtests passed`；新增的
    `test_live_loki_acceptance.py` 在未显式提供现场 URL 时安全跳过。
  - 已覆盖精确 Agent/Application Tool Envelope、Job Snapshot、legacy 新写拒绝、Internal API Job facts、资源/策略隔离、迁移和运行时回归。

## 前端测试与构建

- `npm --prefix frontend test`
  - 结果：`15` 个 test files、`89` 个 tests 全部通过。
- `npm --prefix frontend run typecheck`
  - 结果：通过。
- `npm --prefix frontend run lint`
  - 结果：通过。
- `npm --prefix frontend run build`
  - 结果：生产构建通过；保留 Vite 对单个大 chunk 的非阻断告警。

## SQLite 备份恢复与重新升级演练

自动化用例：
`backend/tests/test_schema_migration_runtime.py::test_pre_028_backup_can_be_restored_and_reupgraded_without_data_loss`

演练步骤：

1. 只加载 `001`–`027` migration，确认 schema head 为 `027`，写入无敏感测试用户作为保留数据标记。
2. 关闭连接并复制数据库文件作为 pre-028 备份。
3. 对工作数据库应用 `028`–`032`，确认 head 为 `032`、新治理表存在且保留数据仍在。
4. 关闭连接，用备份覆盖工作数据库，确认 ledger 回到 `027`、新治理表不存在且保留数据仍在。
5. 对恢复后的数据库再次应用 `028`–`032`，确认精确应用序列、head `032` 和保留数据。

结果：定向演练通过。该证据是仓库内 SQLite migration 的可复现备份恢复测试；不声称已经执行生产 PostgreSQL 的物理备份恢复。
