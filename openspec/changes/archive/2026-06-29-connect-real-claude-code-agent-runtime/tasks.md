## 1. 依赖、配置与运行时环境

- [x] 1.1 在 `pyproject.toml` 增加 `claude-agent-sdk` 依赖。
- [x] 1.2 扩展 `backend/app/shared/config.py`：新增 `anthropic_api_key`、可选 `anthropic_base_url`，以及 `ExecutionSettings.max_turns`（env `AGENT_MAX_TURNS`），并从环境加载。
- [x] 1.3 更新 `backend/Dockerfile`：安装 Node.js 与 Claude Code CLI，确保容器内 SDK 可运行。
- [x] 1.4 在 `docker-compose.yml` 增加（注释/示例）opt-in 启用 real Claude 的环境变量，不硬编码密钥。

## 2. 只读工具的 SDK MCP 桥接

- [x] 2.1 为 MVP 六个只读工具定义 `@tool`（name/description/schema，`annotations.readOnlyHint=True`），handler 调用 `ToolRegistry.call(...)`。
- [x] 2.2 用 `asyncio.to_thread` 包裹同步 `ToolRegistry.call`，避免阻塞 SDK 事件循环。
- [x] 2.3 用 `create_sdk_mcp_server(name="internal", ...)` 打包，每次 run 重建 server 并以闭包绑定当前 job 的 `job_id/user_id/project_code`。
- [x] 2.4 未注册/被拒工具返回 policy error 文本给模型，不抛未捕获异常。

## 3. RealClaudeCodeAgentClient 实现

- [x] 3.1 在 `claude_code_agent_client.py` 用 `query()` + `ClaudeAgentOptions` 实现 `_run_async`，对外 `run()` 用 `asyncio.run` 桥接为同步。
- [x] 3.2 构造 system prompt：role + safety rules + tool restrictions + 报告结构要求 + skills + retrieved context；user prompt 用 `context.user_question`。
- [x] 3.3 配置权限：`allowed_tools=["mcp__internal__*"]`、`disallowed_tools=["*"]`，不使用 `bypassPermissions`，可选 `can_use_tool` 拒绝非 internal 工具。
- [x] 3.4 用 `max_turns` 与 `asyncio.wait_for(timeout=AGENT_TIMEOUT_SECONDS)` 限制执行。
- [x] 3.5 解析 SDK 消息流：收集 assistant 文本与 `ResultMessage.result` 为 `final_answer`，收集 tool_use/tool_result 为 `tool_events`（仅摘要，不含私有 reasoning）。
- [x] 3.6 错误映射：缺 key / CLINotFound → 非 retryable；ProcessError/传输/JSON decode/超时/限流 → `RetryableExecutionError`。

## 4. 装配与可观测性

- [x] 4.1 在 `bootstrap.py` 按 `settings.feature_real_claude` 注入 real/stub，并向 real client 传入 `tool_registry`、model、limits、凭证；test container 默认 stub。
- [x] 4.2 扩展 `AgentExecutor.execute()`：成功后持久化 `result.tool_events` 到 `agent_tool_call`，并追加 “Model execution completed” step。
- [x] 4.3 确认 stub 路径（空 tool_events）不产生重复或遗漏记录。
- [x] 4.4 更新 `backend/app/main.py` health/ready：返回 `feature_real_claude`、API key 是否配置、CLI 是否可检测，不发起 live 调用。

## 5. 测试

- [x] 5.1 新增 `test_claude_code_agent_client.py`：monkeypatch SDK `query`/transport，覆盖单轮回答、tool loop、未注册工具拒绝、timeout、错误映射、tool_events 解析。
- [x] 5.2 新增断言：real runtime 不放行任何内置工具（仅 `mcp__internal__*`）。
- [x] 5.3 扩展 AgentExecutor 测试：注入 fake real client，断言 tool_events 写入 `agent_tool_call`。
- [x] 5.4 运行现有 `test_agent_runtime_and_worker.py`，确保 retry / duplicate delivery 行为不变。
- [x] 5.5 增加 bootstrap 装配测试：feature flag 开/关注入的 client 类型正确。
- [x] 5.6 （可选）新增 `@pytest.mark.integration` 真实 SDK 冒烟测试，仅在有 key + CLI 时运行。

## 6. 文档与验证

- [x] 6.1 更新 `backend/README.md`：`FEATURE_REAL_CLAUDE`、`ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL`、`AGENT_MAX_TURNS`、Node.js/CLI 前置条件与启用步骤。
- [x] 6.2 记录手动验证路径：开启 real Claude 提交 debug job，worker 消费后 job 为 `SUCCEEDED` 且报告非 stub 模板。
- [x] 6.3 运行 `make check`（CI 无 key/CLI，全程 stub/fake）通过。
- [x] 6.4 运行 `openspec validate connect-real-claude-code-agent-runtime`，确认可进入 apply 阶段。
