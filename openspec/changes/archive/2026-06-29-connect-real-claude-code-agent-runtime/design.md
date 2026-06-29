## Context

上一轮 `wire-rabbitmq-agent-job-flow` 已打通跨进程闭环：

```text
POST /api/agent/jobs
  -> PostgreSQL
  -> RabbitMQ
  -> agent-worker
  -> AgentExecutor
  -> StubClaudeCodeAgentClient   # 当前固定 stub
  -> FakeInternalApiClient
  -> 保存报告 / steps / tool calls
```

代码里已有 `RealClaudeCodeAgentClient` 占位实现和 `FEATURE_REAL_CLAUDE` 配置，但 bootstrap 始终注入 stub。本 change 用官方 **Claude Agent SDK（Python 包 `claude-agent-sdk`，导入 `claude_agent_sdk`）** 实现真实运行时。

关键事实（影响整体设计）：

- SDK 不是纯 HTTP 客户端，它在底层**封装 Claude Code CLI（Node.js）**，运行环境需要 Node.js + CLI 可执行文件。
- SDK 接口是 **async**：`query()`（一次性）、`ClaudeSDKClient`（会话）、`ClaudeAgentOptions`、`@tool`、`create_sdk_mcp_server`。
- 自定义工具 = **in-process SDK MCP server**，工具名 `mcp__<server>__<tool>`。
- 权限由 `allowed_tools` / `disallowed_tools` / `permission_mode` / `can_use_tool` 控制；`allowed_tools` 只“预批准”，不“限制”。

约束：

- 内部工具继续走 `FakeInternalApiClient`，避免同时调试 SDK 与真实内部平台。
- CI 默认无 API key、无 CLI，必须可完全用 stub/fake 跑通。
- 只读安全边界不变，且 SDK 内置写工具必须被关闭。

## Goals / Non-Goals

**Goals:**

- 用 Claude Agent SDK 实现可运行的 `RealClaudeCodeAgentClient`。
- 把 `ToolRegistry` 六个只读工具封装为 in-process SDK MCP server 暴露给 SDK。
- 强制只读：仅放行 `mcp__internal__*`，禁用全部内置写/Bash/编辑工具。
- async SDK 与同步 executor/worker 的桥接干净，不外泄事件循环。
- bootstrap 按 `FEATURE_REAL_CLAUDE` 选择 real/stub；test 默认 stub。
- 将 SDK 错误映射到现有 retry 语义；用 `max_turns` + wall-clock 限制执行。
- 持久化 tool events 与可观测 steps；health/ready 报告运行时模式。
- Dockerfile 安装 Node.js + CLI，使容器内 SDK 可用。

**Non-Goals:**

- 不接真实 ER / Loki / Redis / DB 内部 API。
- 不启用 SDK 内置写工具、审批、沙盒、代码修改。
- 不使用 SDK subagents / hooks / checkpointing。
- 不实现密钥管理 UI 或多模型路由。

## Decisions

### 1. 使用 Claude Agent SDK 驱动 agent loop（取代手写 Messages API 循环）

不再自己写 `messages.create()` tool loop，而是让 SDK 负责 agent loop、工具编排与上下文管理。`RealClaudeCodeAgentClient.run()` 构造 `ClaudeAgentOptions`，调用 `query()` 或 `ClaudeSDKClient`，消费消息流直到 `ResultMessage`。

MVP 选择 **`query()` 一次性调用**（单轮诊断问题，无需多轮会话与中断），实现更简单；若后续需要会话连续性再切 `ClaudeSDKClient`。

```python
options = ClaudeAgentOptions(
    model=model,
    system_prompt=system_prompt,           # role + safety + skills + report format
    mcp_servers={"internal": internal_server},
    allowed_tools=["mcp__internal__*"],
    disallowed_tools=["*"],                 # 移除全部内置工具，仅留下被 allow 的 mcp 工具
    permission_mode="default",
    max_turns=settings.execution.max_turns,
)
async for message in query(prompt=user_question, options=options):
    ...  # 收集 assistant 文本、tool_use/tool_result、ResultMessage.result
```

替代方案：继续用 raw Anthropic Messages API（上一版设计）。被否决，因为用户明确要求使用 SDK，且 SDK 自带 loop/权限/MCP，能减少手写编排与越权风险。

### 2. 只读工具通过 in-process SDK MCP server 桥接 ToolRegistry

为每个 MVP 工具定义 `@tool`，handler 内调用 `ToolRegistry.call(...)`，用 `create_sdk_mcp_server(name="internal", tools=[...])` 打包。

工具需要 `job_id / user_id / project_code`，而 SDK 只把模型参数传给 handler。**用每次 run 重新构建 server + 闭包捕获当前 job 上下文**（或 `contextvars`），避免并发 job 串台：

```python
def _build_internal_server(self, *, job_id, user_id, project_code):
    registry = self.tool_registry
    def make(tool_name):
        @tool(tool_name, DESCRIPTIONS[tool_name], SCHEMAS[tool_name],
              annotations={"readOnlyHint": True})
        async def handler(args):
            result = await asyncio.to_thread(
                registry.call, job_id=job_id, user_id=user_id,
                project_code=project_code, tool_name=tool_name, arguments=args)
            return {"content": [{"type": "text", "text": result.summary}]}
        return handler
    return create_sdk_mcp_server(name="internal",
        tools=[make(n) for n in registry.available_tools()])
```

注意：`ToolRegistry.call` 是同步且可能阻塞（网络/DB），在 async handler 内用 `asyncio.to_thread` 包裹，避免阻塞 SDK 事件循环。

替代方案：用外部 stdio MCP server。被否决，进程开销大、部署复杂，in-process 更贴合现有同进程工具服务。

### 3. 强制只读：禁用所有内置工具，仅放行 internal MCP

SDK 自带 Bash/Write/Edit/Read/WebFetch 等内置工具，必须关闭：

- `disallowed_tools=["*"]` 或不在 `allowed_tools` 中暴露内置工具，使其不进入模型上下文。
- `allowed_tools=["mcp__internal__*"]` 仅预批准只读工具。
- **不使用 `permission_mode="bypassPermissions"`**（它会连内置工具一起放行）。
- 可选再加 `can_use_tool` 回调，对非 `mcp__internal__` 前缀的调用一律 deny，作为纵深防御。

未注册/被拒工具：返回 policy error 文本给模型，不抛未捕获异常，让模型自行纠正而非整 job 崩。

### 4. async 桥接到同步 executor/worker

`AgentExecutor.execute()` 与 worker 均为同步。`RealClaudeCodeAgentClient.run()` 内部用 `asyncio.run(self._run_async(request))` 自管事件循环，对外仍是同步 `run(request) -> AgentRunResult`。

陷阱：FastAPI 进程已有运行中的事件循环，但 worker 是独立进程、纯同步，`asyncio.run` 安全；API 进程一般不直接执行 job（job 在 worker 执行），故不会出现 “asyncio.run inside running loop”。若将来 API 内联执行，需要改用 `anyio`/线程池。本 change 在文档中标注此约束。

### 5. Prompt 与 Skills 注入

System prompt 拼接：`context.system_role` + 编号 `safety_rules` + `tool_restrictions` + 报告结构要求 + `context.skills`（按 skill 名分段）+ `retrieved_context`（ER/业务流摘要，AgentContextBuilder 已预取）。User prompt = `context.user_question`。

Skills 注入采用 **system prompt 内联**，不依赖 SDK 的 `setting_sources`/文件系统自动加载（更可控、容器内路径无关）。`SkillLoader` 已能读取 `.claude/skills/*/SKILL.md`。

### 6. 错误映射与限制

| 条件 | 异常 | 重试 |
|------|------|------|
| 缺少 API key | 非 retryable | 否 |
| SDK CLI 不存在（CLINotFoundError） | 非 retryable | 否 |
| SDK ProcessError / 传输 / CLIJSONDecodeError | `RetryableExecutionError` | 是 |
| Anthropic 429/529/5xx、网络超时 | `RetryableExecutionError` | 是 |
| wall-clock 超过 `AGENT_TIMEOUT_SECONDS` | `RetryableExecutionError` | 是 |
| ToolPolicyError / 参数校验 | 返回给模型；持续失败则 fail job | 否 |

用 `asyncio.wait_for(..., timeout=settings.execution.timeout_seconds)` 包裹整个 SDK 会话；`max_turns` 防止无限工具轮次。

### 7. AgentExecutor 持久化 tool_events

executor 在 `claude_client.run()` 成功后遍历 `result.tool_events`，写入 `agent_tool_call`，并追加 “Model execution completed” step。stub 返回空 `tool_events` 不受影响。context 预取（ER/业务流）仍由 AgentContextBuilder 负责，real loop 内工具调用单独持久化，spec/tests 明确预期行数。

### 8. 依赖、Dockerfile 与配置

- `pyproject.toml` 增加 `claude-agent-sdk`。
- `backend/Dockerfile`：基于 `python:3.12-slim` 增加 Node.js（apt 或 NodeSource）与 Claude Code CLI（npm 全局安装），否则 SDK 运行报 CLINotFoundError。
- 配置新增：`anthropic_api_key`、`anthropic_base_url`（可选）、`max_turns`（`ExecutionSettings`，env `AGENT_MAX_TURNS`）。
- Compose 默认 stub（不强制密钥/CLI）；README 增加 opt-in 示例，不硬编码密钥。

### 9. 测试策略

- 单元测试：用 fake SDK transport / monkeypatch `claude_code_agent_client.query`，断言消息流解析、tool loop、timeout、错误映射、tool_events。
- 现有 stub 测试保持通过。
- 可选 `tests/integration/test_real_claude.py`，`@pytest.mark.integration`，仅在有 `ANTHROPIC_API_KEY` 且 CLI 可用时运行。
- `make check` 不依赖真实 SDK/CLI/key。

## Risks / Trade-offs

- [Risk] 容器缺 Node.js/CLI → SDK 启动即失败。缓解：Dockerfile 安装并在 ready 检查检测 CLI；映射为非 retryable，避免无意义重投。
- [Risk] async/sync 桥接在 API 进程内联执行时冲突 → 仅在 worker 执行 real job；文档标注约束。
- [Risk] 内置写工具误开放 → 默认 `disallowed_tools=["*"]` + 仅 allow `mcp__internal__*` + `can_use_tool` 纵深防御；加测试断言无内置工具可用。
- [Risk] 工具 handler 阻塞事件循环 → `asyncio.to_thread` 包裹同步 `ToolRegistry.call`。
- [Risk] 并发 job 工具上下文串台 → 每 job 重建 MCP server + 闭包捕获上下文。
- [Risk] API key 泄露日志 → 禁止记录 key；tool event 仅存 summary，沿用 audit 脱敏。
- [Risk] SDK 版本/字段变化 → 全部 SDK 调用隔离在 client 模块，单测覆盖解析逻辑。
- [Trade-off] MVP 用 `query()` 而非会话/streaming → debug API 仅在完成后看到完整结果，后续可升级。

## Migration Plan

1. `pyproject.toml` 增加 `claude-agent-sdk`；`Settings` 增加凭证与 `max_turns`。
2. 实现 in-process MCP 工具桥接与 `RealClaudeCodeAgentClient`（SDK options、消息解析、错误映射、async 桥接）。
3. bootstrap 按 feature flag 注入 real/stub，传入 tool_registry/limits/凭证。
4. 扩展 `AgentExecutor` 持久化 tool_events 与步骤。
5. 更新 `backend/Dockerfile` 安装 Node.js + CLI；更新 health/ready 字段。
6. 添加 fake-SDK 测试；更新 README 与 compose opt-in 文档。
7. 本地验证：`FEATURE_REAL_CLAUDE=false` 跑 `make check`；有 key + CLI 时手动跑一条 debug job。

Rollback：将 `FEATURE_REAL_CLAUDE=false` 或移除密钥，回退 stub；数据库 schema 无变更，无需 migration rollback。

## Open Questions

- MVP 是否足够用 `query()` 单次调用，还是已需要 `ClaudeSDKClient` 会话（支持 interrupt/多轮）？
- context 预取（ER/业务流）在 real runtime 下是否改为仅由模型按需调工具，以减少重复调用？
- Node.js + CLI 是否打进同一镜像，还是单独 base 镜像/sidecar？
- integration 测试纳入 CI nightly 还是仅手动文档化？
