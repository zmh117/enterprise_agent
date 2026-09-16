# 空关联与 Tool Call 摘要修复验证（2026-09-10）

## 范围与原因

- ONES 可选迭代返回 UUID/名称均为空的对象时，原规范化函数仍按必填具名对象校验，导致一条未关联迭代的工作项使整页失败。可选人员使用同样的校验逻辑。
- MCP 根 Tool Call 原来复制集合正文；管理查询再用 `substr(..., 1, 2000)` 截断 JSON，前端解析失败后直接展示字符串，形成原始 JSON 片段。
- SDK 文件工具响应只有正文省略标记或包装对象，前端未识别工具操作阶段，因而显示没有诊断价值的占位文案。

## 已实现

- 可选 sprint、owner、assign 共用具名关联规范化：null、空对象或 UUID/名称均为空表示未关联，并省略对应字段；不丢弃工作项。半空对象、错误类型和必填关联仍严格拒绝。列表、详情、关联工作项以及其他使用可选人员函数的接口共享修复。
- 新 MCP 根 Tool Call 在原始结果上提取固定计数、大小、完整性和安全错误元数据；详细审计的既有行为保持不变。管理与 Debug 读取历史摘要时只在 1,048,576 字符预算内解析，兼容 JSON/payload/MCP text/runtime_file_bridge 包装。先投影再输出，不切断 JSON；不可恢复的旧摘要不猜测、不回显。
- 错误原因先脱敏再限长，保留错误码。时间线不展示工作项正文、名称、人员、路径或提交凭证。
- 文件工具按真实状态展示读取、沙盒写入/修改、检索、提交意图及输出选择。Write 字节数只来自已观测请求；意图与选择明确标注“尚未提交”。失败调用不显示成功语义。
- 未修改环境示例、Compose、公开工具 schema、Publication 或历史 Job；未恢复 Mock 服务。

## 本地自动化验证

以下合计 **313 passed**：

```text
.venv/bin/pytest -q --tb=short
  backend/tests/test_tool_response_summary.py
  backend/tests/test_ones_response_compatibility.py
  backend/tests/test_mcp_audit_coordinator.py
  backend/tests/test_admin_api_contracts.py
  backend/tests/test_phase3a_secret_leak_gate.py
  backend/tests/test_python_agent_runtime.py
  backend/tests/test_agent_job_debug_queries.py
  backend/tests/test_agent_runtime_and_worker.py
  backend/tests/test_ones_auto_collection.py
  backend/tests/test_ones_mcp_runtime.py
  backend/tests/test_ones_graphql_operations.py
  backend/tests/test_ones_rest_operations.py
  backend/tests/test_ones_basic_query_interfaces.py
  backend/tests/test_python_file_mcp_runtime_bridge.py
  backend/tests/test_python_runtime_internal_architecture.py
  backend/tests/test_test_suite_governance.py
```

- 复现分页索引 50 的空迭代/人员，验证 51 条全部保留；覆盖详情及关联工作项、合法关联保留、半空/错误类型/必填字段拒绝。
- 超过 2000 字符的历史结果通过真实管理 HTTP 查询与 Debug Repository 投影，正文不可见，尾部计数可见。新根摘要在详细审计达到 4096 字节截断阈值后仍保留完整计数。
- 原有工具事实关联、分页稳定性、沙盒成功/失败/取消/超时清理、安全与 Runtime 协议回归通过。
- `runtime-records.test.tsx`：**34 passed**，包括长/损坏 JSON、包装解析、计数与完整性、文件阶段、失败不误报成功及敏感正文不展示。
- 变更 Python 文件 Ruff、6 个生产代码文件 mypy、两个前端文件 ESLint 均通过。
- 前端本地构建、Docker 镜像构建通过；保留 Vite 既有配置兼容和大 chunk 提示，不属于本次变更。
- `docker compose config --quiet`、`openspec validate paginate-ones-graphql-list-tools --strict`、`git diff --check` 通过。

## 已部署与容器验证

部署前只读取 Job 状态计数，PENDING/RUNNING/RETRY_WAIT 均为零。重建并以 `--no-deps --no-build` 更新以下本地服务，没有关闭或禁用 ones-mcp：

| 服务 | 容器 ID | 状态 |
| --- | --- | --- |
| ones-mcp | 1e743934d577 | running / healthy |
| api-server | c39130c4be49 | running / healthy |
| python-agent-runtime | 64a4bf77b8b2 | running / healthy |
| agent-worker | 5329d1f6ef30 | running，无独立 healthcheck |
| admin-web | 27f5c3b57174 | running，无独立 healthcheck |

- ONES 容器用合成 Provider 回调经过真实解析与收集器完成 5 页、1000 条收集；每条包含空迭代/人员，全部工作项保留，`truncated=false`，未调用外部 ONES。
- Runtime 容器执行合成 SDK Write 事件规范化，输出 SUCCEEDED、9 字节及正文省略标记；没有实际创建文件。
- API 容器验证超过 2000 字符的合成结果投影只保留计数；通过 HTTP 读取 admin-web 静态入口及 bundle，确认 HTTP 200 和三种“尚未提交”新文案。
- 此项为合成链路、容器和静态资源验证，不等于真实 ONES、真实模型 Job 或浏览器端到端验收。

## 未执行

遵守“不连接真实 ONES”的限制；没有读取现场业务正文、凭据或重跑历史 Job。5.3、6.6 的真实 ONES/Publication 验收继续待办，不能以本次测试和健康检查替代。未执行 Git 提交或推送。
