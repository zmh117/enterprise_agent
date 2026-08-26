## 验证日期

2026-08-26

## 自动化验证

- `backend/tests/test_python_agent_runtime.py` + `backend/tests/test_python_file_mcp_runtime_bridge.py`：59 passed。
- `backend/tests/test_runtime_http_client.py` + `backend/tests/test_job_execution_policy.py`：46 passed。
- `backend/tests/test_agent_runtime_and_worker.py` + `backend/tests/test_python_runtime_internal_architecture.py`（排除已存在的无关基线用例）：9 passed，1 deselected。
- Ruff（本变更涉及的 6 个源文件与 3 个测试文件）：通过。
- mypy（本变更涉及的 6 个源文件）：通过。

定向用例证明：

- `max_tool_calls=1` 时首次请求允许、第二次请求返回 `interrupt=true`，并统一为 `execution_policy_max_tool_calls_exhausted`。
- `max_tool_calls=0` 时首次工具请求即在授权/副作用前终止。
- SDK 正常完成、原样抛错或包装中断时，Runtime 均保留此前安全工具事件并返回稳定策略耗尽错误。
- Runtime 自身墙钟监视器触发 `runtime_timeout`；provider 内部 timeout 仍为可重试运行错误。
- Python Runtime failure envelope 对预算耗尽和本地墙钟超时均使用 `retry_class=NEVER`。
- Runtime HTTP client 按 `runtime_timeout` 稳定错误码还原 `ExecutionTimeout`，兼容 `NEVER` 与旧 `TRANSIENT` envelope。
- Worker 对结构化 `ExecutionTimeout` 和旧 `RetryableExecutionError(runtime_timeout)` 均不创建 retry dispatch，`retry_count=0`，Job 为 `TIMEOUT`，失败通知最多一次。

## 已知无关基线

`test_python_runtime_has_no_dynamic_plugin_or_runtime_registry` 在当前 HEAD 上失败：测试只允许 `claude_agent_sdk` 与 `claude_code_sdk` 两个动态导入，但 HEAD 的 `claude_client.py` 已存在 `claude_agent_sdk._cli_version` 导入。本变更未新增或修改该导入，也未调整插件/Runtime registry 边界，因此没有在本 change 中扩大范围修复。

## 结构边界

本变更未修改数据库 migration、Runtime 协议 schema、Sandbox 限额、Publication/Job 快照字段或 `.env.example` 的既有 Feature 开关。
