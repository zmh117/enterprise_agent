## 实施基线

记录时间：2026-08-10

### 工作区

- 分支：`mcp_new`
- 基线提交：`f8c6b74 引入 TypeScript Agent Runtime 并保留 Python 默认`
- 开始实施时，除本 change 目录外无其他未提交文件；后续编辑不得覆盖用户已有改动。

### 当前Runtime与Worker

- `agent-worker` 继承 `backend/Dockerfile` 的 `claude-runtime` target，同时包含 Python `claude-agent-sdk`、Node 和全局 Claude Code CLI。
- Python Agent SDK 通过 `RealClaudeCodeAgentClient` 在 Worker 进程内执行。
- TypeScript SDK 固定为 `@anthropic-ai/claude-agent-sdk@0.3.226`，位于独立 `agent-runtime` 服务。
- `RuntimeMigrationGate` 通过环境/Application allowlist 为新 Job 选择 `python-v1`/`typescript-v1`；Job 已有 `agent_runtime_kind` 字段。
- Worker 继续拥有 RabbitMQ consume、Job claim、retry/终态、Tool 事件、结果、Delivery Outbox 和 ack。

### 当前协议与模型连接

- `agent-runtime/contracts/v1/protocol.schema.json` 是 Python/TypeScript 共享协议源。
- TypeScript Runtime 已实现 Runtime Grant、NDJSON 事件、取消、invocation registry、terminal ledger、digest conflict、health/readiness/version 和 model probe。
- Worker 使用 Runtime Grant Ed25519 私钥签发执行/取消票据；Runtime 只挂载公钥验证。

### 当前工具与MCP

- `runtime-tool-mcp` 是独立 Compose 服务，使用 `RUNTIME_TOOL_MCP_SIGNING_KEY_FILE` 的 HS256 Token。
- Worker 向 TypeScript Runtime 请求写入 `runtime-tool-mcp` URL、access token 和精确 Tool 列表。
- 本 change 的目标是删除该服务、Token issuer/verifier、secret 与 `RUNTIME_TOOL_MCP_*` 配置，改为私有网络内无 MCP Token/签名的官方 MCP SDK 标准 Tool Server。
- Runtime Grant 保留但禁止进入 MCP 请求；API Capability 等控制面退役不在本 change。

### Golden基线

- Python：`test_claude_code_agent_client.py` 覆盖成功、Tool 事件、timeout、最大轮次、最大 Tool Call、瞬时错误、矛盾结果和敏感诊断屏蔽。
- Worker：`test_agent_runtime_and_worker.py` 覆盖成功、retry、失败 Tool 事件、最大轮次终态、结果持久化和重复消息/Delivery。
- 跨语言：`test_agent_runtime_protocol_contract.py` 与 `agent-runtime/contracts/v1/golden/*` 固定请求摘要、schema 和安全 fixture。
- TypeScript：`agent-runtime/test/*` 覆盖 SDK adapter、Tool 限制、错误分类、Runtime Grant、取消、终态恢复、模型连接和 probe。
- 初次聚焦运行发现 Worker 测试缺少 `local-user` 的默认项目测试授权；已在测试夹具中显式补齐，不改变生产权限 fallback。
