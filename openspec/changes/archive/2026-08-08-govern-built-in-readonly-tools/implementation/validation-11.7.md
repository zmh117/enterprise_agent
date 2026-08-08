# 11.7 Removal 前后备份与回滚演练证据

执行日期：2026-08-06（Asia/Shanghai）

## 自动化演练

新增：`backend/tests/test_builtin_tool_removal_backup_rollback.py`。

演练使用文件型 SQLite 数据库，并在复制前关闭所有数据库连接：

1. 发布精确 Application Publication v1，创建并冻结一个包含 cloud/edge Resource Revision 的精确 Job；
2. 发布新的 cloud Resource Revision 和 Application Publication v2，并激活 v2；
3. 完成原 Job 的精确 Tool Fact 与 Delivery Attempt，使其满足真实链 Acceptance 约束；
4. Removal Gate 第一次零引用观察为 `BLOCKED / consecutive=1`，关闭数据库并生成 pre-removal 备份；
5. 第二次零引用观察绑定 Acceptance，Gate 成为 `READY / consecutive=2`，关闭数据库并生成 post-removal 备份；
6. 分别把两份备份复制为独立恢复数据库，并由当前代码重新打开、校验 migration head 和运行事实。

## 两次恢复共同证明

- 原 Job Snapshot Hash 不变；
- 原 Job 仍引用 Publication v1；
- 原 Job 仍只冻结原 cloud/edge Resource Revision，未出现 v2 的 cloud Resource Revision；
- 当前 Application Deployment 仍引用 Publication v2，证明“活动版本升级”和“旧 Job 固定版本”相互独立；
- 调用 Legacy Job Snapshot 写边界仍返回 `builtin_tool_legacy_write_forbidden`；
- `agent_tool_binding` 旧绑定计数在拒绝前后不变，仅写入脱敏拒绝审计；
- pre-removal 恢复后的 Gate 仍为未就绪；post-removal 恢复后的 Gate 仍为 `READY`，没有跨备份伪造状态。

## 执行结果

```text
.venv/bin/pytest -q backend/tests/test_builtin_tool_removal_backup_rollback.py
```

结果：`1 passed`；另有一个来自测试依赖的既有 Starlette deprecation warning。

该证据是仓库 SQLite 数据层的可复现文件备份/恢复演练；不声称已经执行生产 PostgreSQL 物理备份、时间点恢复或真实维护窗口切换。
