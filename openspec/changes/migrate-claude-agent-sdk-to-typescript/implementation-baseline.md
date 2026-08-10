# 实施基线

## 当前事实

- 分支：`mcp_new`
- 基线提交：`c2f9863637b1b125c865435b1c0e7040794ad6fb`
- 记录时工作树：仅本 change 目录为未跟踪内容；实施不得覆盖后续出现的无关修改。
- Python 依赖：`pyproject.toml` 同时包含 `anthropic>=0.40` 与 `claude-agent-sdk>=0.1.0`。
- Worker 镜像：`backend/Dockerfile` 全局安装 `@anthropic-ai/claude-code`，Python Worker 同时包含 Python、Node 和 CLI。
- Runtime 开关：Compose 使用 `FEATURE_REAL_CLAUDE`；未定义独立 TypeScript Runtime 服务或跨语言执行协议。
- 真实客户端：`backend/app/modules/agent/infrastructure/claude_code_agent_client.py` 的 `RealClaudeCodeAgentClient` 在 Python 内管理 asyncio/thread、Secret 解析、SDK query、进程内 MCP、错误分类和模型连接测试。
- 业务状态：`AgentExecutor`/`JobRetryService`/Delivery Outbox 已由 Python 持有，迁移不得把这些事务下放到 Node。

## 当前Tool边界

`ToolRegistry.READONLY_TOOLS` 当前包含：

- `get_er_context`
- `get_business_flow_context`
- `get_schema_directory`
- `diagnose_loki_labels`
- `diagnose_loki_label_values`
- `diagnose_loki_probe`
- `query_loki`
- `query_database`
- `query_redis_get`
- `query_redis_scan`

此外，`RealClaudeCodeAgentClient` 会把 Job 固定的 governed QUERY Capability 转为进程内 SDK MCP Tool。TypeScript 灰度前，两类 Tool 都必须具有受治理远程等价边界；任何缺口都必须阻止对应 Application 切换。

## 可复用来源

从 `mcp_dev` 选择性移植：

- `agent-runtime/` 的协议、配置、Grant、ledger、SDK adapter、模型绑定、probe、测试和容器策略。
- Python 的 `runtime_protocol.py`、`generated_runtime_contracts.py`、`typescript_runtime_client.py`、`routed_runtime_client.py`、`runtime_migration_gate.py` 作为适配参考。
- 相关 Runtime/Worker/模型连接测试和 Compose 安全约束。

不得整体移植：

- `mcp_dev` 的旧平台删除、前端裁剪/恢复、Business Application 重写、MCP Tool Publication 控制面和 040 destructive schema 清理。
- 任何会删除当前 `mcp_new` API Capability、Internal API Platform、Tool Catalog、身份/RBAC、资源或管理前端的提交。

## 适配原则

1. 先移植无业务 schema 依赖的 Runtime 核心和契约测试，再适配当前模型连接表及 Secret Provider。
2. Python 保持 Job、授权、retry、审计、result 和 Delivery 的唯一写入者。
3. TypeScript Runtime 默认不承载现有 Job；migration gate 默认 `python-v1`。
4. 当前 Tool 没有远程等价实现时，`typescript-v1` 必须失败关闭，不得自动 fallback。
5. Python SDK 和 CLI 镜像层作为默认 `python-v1` Runtime 长期保留；真实钉钉链路、敏感扫描和观察窗口只决定显式 TypeScript Application 是否可启用。

## Python Runtime Golden证据

现有 `backend/tests/test_claude_code_agent_client.py` 已覆盖迁移所需 characterization：单轮成功、精确 Tool 权限、只读 Tool loop、受治理 Capability、策略拒绝、缺失/占位凭据、timeout、瞬时错误、不一致 result、错误脱敏、无效模型、失败前 Tool event、最大轮次和最大 Tool Call。基线运行结果为 `18 passed`；迁移后的 TypeScript 契约测试必须保持这些可观察语义。
