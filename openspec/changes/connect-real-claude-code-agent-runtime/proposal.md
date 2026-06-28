## Why

RabbitMQ 跨进程任务闭环已经打通，但 `AgentExecutor` 仍固定使用 `StubClaudeCodeAgentClient`，诊断报告只是模板拼接，没有真正的 Agent 推理与工具循环。本 change 用官方 **Claude Agent SDK（`claude-agent-sdk` / `claude_code_sdk`）** 落地 `RealClaudeCodeAgentClient`：复用 SDK 内置的 agent loop、权限模式与 in-process MCP 工具机制，把现有只读工具暴露给真实 Claude 运行时，使 worker 能完成端到端只读诊断；同时保留 stub 作为测试与无凭证环境的默认路径。

## What Changes

- 在 `pyproject.toml` 增加依赖 `claude-agent-sdk`（底层依赖 Node.js + Claude Code CLI 运行时）。
- 实现 `RealClaudeCodeAgentClient.run()`：基于 `ClaudeSDKClient` / `query` + `ClaudeAgentOptions` 驱动 agent loop，接收 `AgentRunRequest`，返回结构化 `AgentRunResult`（含 `final_answer` 与 `tool_events`）。
- 把现有 `ToolRegistry` 的六个只读工具封装为 **in-process SDK MCP server**（`@tool` + `create_sdk_mcp_server`），通过 `mcp_servers` 暴露给 SDK，工具命名 `mcp__internal__<tool>`。
- 用 `allowed_tools=["mcp__internal__*"]` 自动批准只读工具，并用 `disallowed_tools` / `permission_mode` / `can_use_tool` 移除并拒绝所有内置写工具（Bash、Write、Edit、文件系统读、WebFetch 等），强制只读边界。
- 用 `asyncio.run()` 在同步的 `AgentExecutor` / worker 中桥接 SDK 的 async 接口。
- 在 `bootstrap` 中按 `FEATURE_REAL_CLAUDE` 选择 real / stub；测试 runtime 默认 stub。
- 扩展配置：新增 `ANTHROPIC_API_KEY`、可选 `ANTHROPIC_BASE_URL`，与 `CLAUDE_MODEL`、`AGENT_TIMEOUT_SECONDS` 协同；新增最大轮次（`AGENT_MAX_TURNS`）。
- 更新 `backend/Dockerfile`：安装 Node.js 与 Claude Code CLI，使 SDK 在容器内可运行。
- 通过 SDK skills/system prompt 注入既有诊断 Skill 指南；将 SDK 消息流解析为 `final_answer` 与 `tool_events`，持久化 `agent_tool_call` / `agent_step`，不存储私有 reasoning。
- 将 SDK 进程/传输/超时错误映射为 `RetryableExecutionError`；CLI 缺失、凭证缺失、策略拒绝映射为不可重试。
- health/ready 报告 `feature_real_claude`、API key 与 CLI 可用性，不发起 live Claude 调用。
- 增加 fake-SDK 单元测试与 opt-in 集成测试；CI 默认不依赖真实凭证与 CLI。

非目标：

- 不接真实内部 API 平台（仍使用 `FakeInternalApiClient`）。
- 不启用 SDK 的写/编辑/Bash 等内置工具，不实现审批、沙盒或代码修改。
- 不实现 Web 管理后台或密钥轮换 UI。
- 不实现 SDK subagents、hooks、checkpointing 等高级特性（保留后续）。

## Capabilities

### New Capabilities

- `claude-agent-runtime-integration`: 基于 Claude Agent SDK 的真实运行时实现、in-process MCP 只读工具桥接、权限/只读强制、async 桥接、错误映射、运行时选择与凭证/CLI 配置。

### Modified Capabilities

- `claude-diagnostic-runtime`: 从“仅包装契约 + stub”扩展为“在 `FEATURE_REAL_CLAUDE=true` 时通过 Claude Agent SDK 执行只读诊断，工具仅经 SDK MCP 暴露，并持久化工具事件与证据型最终报告”。

## Impact

- 影响 `backend/app/modules/agent/infrastructure/claude_code_agent_client.py`：用 SDK 实现 real client、MCP 工具桥接与错误映射。
- 影响 `backend/app/bootstrap.py`：按 feature flag 注入 client，向 real client 传入 `ToolRegistry`、模型、limits、凭证。
- 影响 `backend/app/modules/agent/application/agent_executor.py`：持久化 `tool_events`，补充执行步骤。
- 影响 `backend/app/shared/config.py`、`docker-compose.yml`、`backend/Dockerfile`：新增 Anthropic / SDK 运行时配置与 Node.js + CLI 安装。
- 影响 `backend/app/main.py` health/ready 响应字段。
- 影响 `pyproject.toml`：新增 `claude-agent-sdk` 依赖。
- 新增/扩展测试：`test_claude_code_agent_client.py`（fake SDK transport）、AgentExecutor 工具事件持久化测试；可选 `@pytest.mark.integration` 真实 SDK 冒烟。
