# 测试层级收集与规范覆盖映射

## 当前收集快照

测量命令：`.venv/bin/pytest --collect-only -q -m <tier> backend/tests`

| 层级 | 文件数 | 收集用例数 | 默认 PR 快速套件 |
|---|---:|---:|---|
| unit | 24 | 173 | 是 |
| contract | 108 | 948 | 是 |
| integration | 8 | 17 | 否，显式外部环境 |
| acceptance | 16 | 140 | 否，完整回归 |
| migration | 15 | 142 | 否，完整回归 |
| 合计 | 171 | 1420 | fast 1121 / full 1420 |

相对优化前 1407 个收集用例，新增 13 个治理和 SQLite 模板防回归用例；没有删除原用例。一个跨企业身份/Callback 用例被移动到独立 acceptance 文件，两个跨 SDK/CLI/MCP 的 meta 保真用例从 contract 重新归类为 acceptance。

## Canonical Requirement 保护映射

| 边界 | 主要层级 | 代表性测试 | 保护内容 |
|---|---|---|---|
| Migrator / baseline / ledger | migration | `test_schema_migration_runtime.py`、`test_schema_fact_source_manifest.py`、`test_schema_migration_postgres_integration.py` | 空库、legacy head、checksum、schema 等价、PostgreSQL |
| 身份与授权拒绝 | contract / acceptance | `test_unified_identity_rbac.py`、`test_role_authorization_control_center.py`、`test_channel_ingress_and_delivery.py` | 当前主体、RBAC、会话撤销、越权失败关闭 |
| Job / Worker 恢复 | acceptance | `test_agent_runtime_recovery.py`、`test_agent_retry_and_failure_delivery.py`、`test_webhook_outbox_recovery.py` | 重试、DEAD、Outbox 恢复、幂等 |
| 文件工作区完整链路 | acceptance | `test_task_file_workspace_synthetic_acceptance.py`、`test_task_file_workspace_group_acceptance.py` | 入口、Workspace、Worker、Sandbox、File MCP、Delivery |
| MCP / 审计 | contract / acceptance | `test_mcp_audit_coordinator.py`、`test_agent_run_audit_repository.py`、`test_mcp_meta_fidelity.py` | Tool 身份、调用审计、跨 SDK/CLI meta 保真、拒绝前不执行 |
| Secret 不泄漏 | contract / acceptance | `test_platform_secret_security.py`、`test_phase3a_secret_leak_gate.py`、`test_file_storage_secret_bootstrap.py` | 日志、API、Job、配置与 Worker 边界 |
| Webhook 真实业务路径 | acceptance | `test_webhook_ingress_dispatch.py`、`test_webhook_outbox_recovery.py`、`test_end_to_end.py` | Token、Inbox/Outbox、Job、结果与恢复 |

## 解释边界

- `test-fast` 是 unit 与 contract 文件集合的真子集，不包含 integration、acceptance 或 migration。
- `test-full` 仍执行 `backend/tests` 全部文件；外部依赖测试继续以明确条件 skip，不会被快速套件替代。
- 上表是自动化代码覆盖映射，不证明真实 Grafana、RabbitMQ、数据库、Runtime、File Service、Docling 或 DingTalk 新鲜链路已经执行。
- 本变更没有删除重复测试；后续如需删除，必须单独补充 Requirement、正常、拒绝、恢复、审计和 Secret 等价证据。
