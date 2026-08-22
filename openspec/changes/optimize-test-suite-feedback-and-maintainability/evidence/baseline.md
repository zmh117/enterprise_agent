# 测试套件优化前基线

## 参考环境

- 日期：2026-08-22
- Checkout：`one_runtime`，测量时实现内容对应 `09f0667`
- 系统：macOS / arm64
- Python：仓库根目录 `.venv`，Python 3.12
- 后端命令：`.venv/bin/pytest -q --durations=30 backend/tests`
- 前端命令：`npm test`（工作目录 `frontend`）

## 代码规模

- 后端直接测试文件：168 个 `test_*.py`，60,995 行
- 后端测试辅助代码：`conftest.py`、`helpers.py`、`business_mcp_fixtures.py` 共 884 行
- 前端测试文件：15 个，7,030 行
- 测试及辅助代码合计：68,909 行
- 后端生产 Python：103,506 行
- 前端生产 TypeScript/TSX：24,907 行
- 测试及辅助代码约为生产代码的 53.7%；行数仅作规模背景，不作为删减 KPI

## 执行结果

### 后端完整套件

- 收集：1407
- 通过：1377
- 跳过：30
- Subtests：2 通过
- Wall-clock：442.84 秒（7 分 22 秒）
- 结果：通过

最慢测试：

| 耗时 | 阶段 | 测试 |
|---:|---|---|
| 2.72s | call | `test_mcp_meta_fidelity.py::test_python_claude_cli_executes_permission_checked_builtin_write` |
| 2.20s | call | `test_admin_api_contracts.py::test_admin_capabilities_are_permission_derived_and_scope_safe` |
| 2.17s | call | `test_unified_identity_rbac.py::test_dingtalk_enterprise_identity_isolation_conflict_and_unknown_fail_closed` |
| 2.04s | call | `test_business_application_control_plane.py::test_admin_api_enforces_feature_auth_csrf_unknown_fields_and_conflict` |
| 1.64s | call | `test_unified_identity_rbac.py::test_session_expiry_password_change_and_owned_revocation_fail_closed` |
| 1.53s | call | `test_mcp_meta_fidelity.py::test_python_claude_agent_sdk_preserves_remote_mcp_result_meta` |

参数化 topology 测试的多个 setup 各约 1 秒，原因是 function-scoped fixture 每次创建文件数据库并执行完整 migration。

### 前端完整套件

- 文件：15 通过
- 用例：117 通过
- Wall-clock：6.20 秒
- 结果：通过
- 非阻断警告：Agent Profile 测试暴露 Base UI button/render prop 语义警告；Vite 提示未来 native config loader 不支持 `__dirname`

## 结构热点

- 11 个不少于 1000 行的后端测试文件共 16,900 行，占后端直接测试代码 27.7%
- 34 个不少于 500 行的后端测试文件共 32,524 行，占 53.3%
- Top 10 后端测试文件占后端直接测试代码 25.7%
- `backend/tests/helpers.py` 为 802 行，同时承担 Container、应用发布、授权、Channel 和 Delivery Arrange
- 测试代码中有 86 个直接 `build_test_container(...)` 调用，33 个测试文件显式包含 `migrate=True`
- Pytest 仅注册 `integration` marker，且只有 `test_real_claude_integration.py` 显式使用
- 当前 CI 在 fail-fast schema 检查后再次执行整个 `backend/tests`，没有可执行的 unit/contract/acceptance/migration 分层

## 验收口径

- PR 快速套件目标：完整 unit + contract，不超过 120 秒
- 后端完整套件目标：收集范围不下降，不超过 300 秒
- 完整验收、拒绝/恢复、migration、审计和 Secret 边界不得因优化被删除
- 容器健康、局部测试通过或行数下降均不等价于完整业务验收
