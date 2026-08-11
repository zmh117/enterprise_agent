# 当前实现基线

- `agent-worker`：Job、retry、结果、审计、Delivery 事实所有者。
- `python-agent-runtime`：安装 Python `claude-agent-sdk`。
- `typescript-agent-runtime`：安装官方 TypeScript `@anthropic-ai/claude-agent-sdk`。
- `tool-mcp`：两个 Runtime 共用的固定标准 MCP Server。
- `RUNTIME_GRANT_*`：只保护 Worker -> Runtime，不用于 MCP。
- Agent Definition/Publication 固定 `python-v1` 或 `typescript-v1`。
- Agent Publication 冻结 MCP Tool identifier/schema hash；Application 选择显式子集。

迁移的回归门禁是协议、Runtime provenance、Tool Event、timeout/cancel、retry、唯一终态、模型 probe 和敏感信息扫描。旧 API Platform 或过渡 MCP 适配器不属于需要保留的基线。
