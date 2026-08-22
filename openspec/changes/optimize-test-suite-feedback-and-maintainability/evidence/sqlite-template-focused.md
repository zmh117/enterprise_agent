# SQLite 迁移模板聚焦证据

## 实现边界

- `build_test_container(...)` 仅在 `migrate=True`、DSN 精确为 `sqlite:///:memory:` 且未显式关闭复用时使用模板
- 非 SQLite、`migrate=False` 和 `reuse_migrated_sqlite_template=False` 保留原始路径
- 模板身份覆盖活动 migration 版本、文件名、规范化 checksum 和 legacy manifest 内容
- 每个 `Database` 恢复到唯一的 shared-memory URI；只在同一 Database 连接池内共享，不跨测试共享
- 模板缓存按 migration 身份区分，内容变化后创建新模板

## 聚焦验证

命令：

```text
.venv/bin/pytest -q --durations=20 \
  backend/tests/test_sqlite_test_template.py \
  backend/tests/test_variable_depth_topology.py \
  backend/tests/test_test_suite_governance.py
```

结果：23 passed，2.32 秒。

- 模板恢复、两个独立 Database 的写入隔离通过
- 同一 Database 的额外 pool connection 可见性通过
- migration 身份不变复用、内容变化重建通过
- 两个 seed Container 的 fixture 与写入隔离通过
- 显式禁用模板后真实 Migrator 路径通过
- 非内存 DSN 和缺失模板拒绝通过

Topology fixture 的每用例 setup 从优化前最慢列表中的约 0.95–1.11 秒下降到约 0.04–0.05 秒；参数化用例继续使用不同 Container 和数据库事实。

## 高频 Container 回归

命令覆盖 Admin API、统一身份 RBAC、业务应用控制面、Agent 模型连接和 topology：

```text
.venv/bin/pytest -q --durations=20 \
  backend/tests/test_admin_api_contracts.py \
  backend/tests/test_unified_identity_rbac.py \
  backend/tests/test_business_application_control_plane.py \
  backend/tests/test_agent_profile_model_connections.py \
  backend/tests/test_variable_depth_topology.py
```

结果：80 passed，17.76 秒。授权、CSRF、Secret redaction、发布、seed、migration repeatability 和 fail-closed 路径均保持通过。

该聚焦结果不是完整回归证据；完整收集数和预算在后续任务中验证。
