## Why

当前 `mcp_operation_audit` 只由 `ones-mcp` 写入，`tool-mcp` 的执行证据仍主要停留在 `agent_tool_call`，且现有 ONES 审计无法与 Runtime 的具体 SDK Tool Use 精确关联。与此同时，Python Runtime 会把无法识别来源的 SDK 原生工具默认标记为 `server_code=tool-mcp`，使 Agent 工具事实与 MCP 服务审计发生错误归类。

## What Changes

- 保留 `agent_tool_call` 作为 Agent Runtime 观察到的全部工具调用事实，覆盖 MCP Tool、SDK 内置 Tool、平台 SDK Tool 和未授权 Tool 尝试。
- 将 `mcp_operation_audit` 通用化为所有平台 MCP Server 的执行侧证据表，由 `tool-mcp` 与 `ones-mcp` 对成功、失败和拒绝调用统一写入。
- 为一次 MCP 调用建立服务端 `mcp_call_id`，通过 MCP `CallToolResult._meta` 返回 Runtime，并与 SDK `tool_use_id`、`agent_tool_call.id` 精确关联；禁止继续按 `job_id + tool_name` 批量猜测关联。
- 为 Runtime Tool Event 和 `agent_tool_call` 增加明确的 `tool_origin`；只有已匹配 Job 冻结 MCP Binding 的调用才能携带 `server_code`，SDK 内置、自定义和未知工具的 `server_code` 必须为空。
- 修复 Python Runtime 将未知 SDK 工具默认归类为 `tool-mcp` 的行为，并同步校正 TypeScript Runtime 对未识别拒绝调用的来源标记。
- 统一 MCP 审计事件语义，区分 `TOOL`、`AUTHORIZATION`、`RESOURCE`、`PROVIDER` 与 `CREDENTIAL` 证据，并保留有界业务载荷、稳定错误码、资源/身份版本和耗时。
- 保留现有 Job Tool Call 查询 API，由 `agent_tool_call` 提供长期、安全摘要；MCP 详细审计继续受 `audit:*:read` 和保留期约束。
- **BREAKING**：Runtime Tool Event 协议增加来源及精确关联字段，`server_code` 改为仅对 MCP 来源有效；`mcp_operation_audit` 数据库结构与写入接口升级为通用契约，Runtime、Worker 和两个 MCP 服务必须按受控顺序一起部署。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `execution-delivery`：明确 Agent Tool Call 与 MCP 执行审计的职责、Tool 来源分类、Runtime 事件协议和精确关联要求。
- `builtin-tool-resource`：要求 `tool-mcp` 为授权、资源解析和工具执行写入通用 MCP 操作审计，并返回服务端关联标识。
- `identity-access`：要求身份感知的 `ones-mcp` 使用同一通用审计契约记录 Provider、Credential 与 Tool 证据，同时保持认证材料隔离。

## Impact

- 数据库：`agent_tool_call`、`mcp_operation_audit`、索引、外键、保留期清理和兼容迁移。
- Runtime 协议：Python/TypeScript Tool Event 生成、MCP 结果元数据提取、严格来源分类和 Worker 持久化。
- MCP 服务：`tool-mcp`、`ones-mcp` 的统一审计写入、失败关闭和 `_meta` 关联返回。
- API：现有 Job Tool Call API 保持路径兼容；管理员 MCP 审计 API 扩展通用字段和筛选条件。
- 验证：双 Runtime、重复工具调用、并发调用、SDK 原生/未知工具、MCP 成功/失败/拒绝、审计保留和无 Secret 泄漏测试。
