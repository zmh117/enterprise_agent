# Runtime 提示词版本回归修复验收（2026-09-10）

## 根因与边界

- 本地 Job `job_3854767c7f204ae089f64cc03159b4ec` 启动后约 0.35 秒失败；Worker 只接受 execution_started，没有实际 Tool Call。
- Worker 默认 Prompt v5 与 Runtime 观测 v6 不一致。修复前现有 `test_worker_builds_exact_request_and_validates_ndjson_terminal` 复现 `Runtime Tool contract observation identity mismatch`。
- 仅安全元数据参与排查和回放；未读取认证材料或原始业务正文，未连接真实 ONES。原 Job 保持 FAILED、retry_count=0，不重跑、不修改历史快照。

## 实现

- `app.shared.tool_contract.PROMPT_TEMPLATE_VERSION` 为 Worker 默认上下文与 Runtime 观测的共同事实源，当前 v6。保留观测 hash、快照 hash、版本、构建身份及事件顺序校验。
- 工具契约拒绝消息包含事件序号、固定字段名和安全期望/实际值；仅规范版本/哈希可回显，其他字段只显示格式或匹配状态。被拒绝事件不写入已验证 Runtime 事件账本。
- 复用现有错误步骤与执行失败摘要，运行记录展示 `failure_code`、`failure_summary`；Worker 在 Runtime 终态前拒绝时也可定位到 RUNTIME_PROTOCOL，不伪造工具调用。

## 本地验证（Confirmed-current）

- 后端 224 项通过：runtime_http_client、agent_run_audit_repository、mcp_tool_runtime、python_agent_runtime、ones_auto_collection、python_runtime_internal_architecture、agent_runtime_and_worker、agent_retry_and_failure_delivery、agent_runtime_protocol_contract、agent_runtime_recovery、agent_runtime_compose_security。
- 覆盖默认上下文的 1.4/1.5 请求、ONES/非 ONES binding、真实 Runtime 观测构造及 Worker NDJSON 接收、版本/快照/观测 hash/构建身份拒绝、非规范字符串不回显、Executor 错误步骤与失败终态/摘要持久化。
- 前端运行记录 24 项通过，包含没有 Tool Call 或运行审计时展示协议失败原因。生产构建与定向 ESLint 通过；Vite 原有配置及大分包提示不影响构建。
- 5 个实现文件定向 mypy、实现与修改测试 Ruff、Compose 配置、git diff --check、严格 OpenSpec 校验通过。

## 部署验证

- 重建并仅替换 api-server、agent-worker、python-agent-runtime、admin-web；API 与 Runtime healthy，Worker running，管理页面 HTTP 探针通过。
- API/Worker 默认版本均为 v6。用已部署 Runtime 容器构造含 ONES 只读派生工具的合成观测，并交给已部署 Worker 的原接收实现：execution_started → tool_contract_observed → 合成 SUCCEEDED terminal 均通过；故意使用 v5 请求只接受第一个事件，并返回包含两侧版本的安全中文错误。
- 该跨容器验证只验证协议接收，不调用模型、业务 MCP 或真实 ONES，不冒充完整业务 Job 验收。
- ones-mcp 在部署前后的容器 ID 均为 `02874568d804`，持续 running/healthy；未恢复 Mock、未改环境示例/连接配置、未发布 Agent/Application、未提交或推送代码。
- 5.3 与 6.6 的真实 ONES 新 Job 验收仍未完成，不归档变更。
