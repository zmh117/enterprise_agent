## ADDED Requirements

### Requirement: Runtime 请求必须只冻结 MCP Tool 而不包含旧平台对象
Worker 发送给 Python/TypeScript Runtime 的执行请求 SHALL 只包含固定 `tool-mcp` Server code、精确 Tool identifier/schema hash 和 Job 标识；MUST NOT 包含 Capability Release、Handler Revision、API Connection、Resource Mapping、Resource Revision、Internal API Token 或任意 MCP URL。

#### Scenario: Worker 构造 Runtime 请求
- **WHEN** Job 冻结了两个 MCP Tool
- **THEN** Runtime 请求只携带这两个 Tool 的稳定标识和 schema hash，并由 Runtime 使用部署固定 URL

#### Scenario: 请求包含旧平台字段
- **WHEN** 请求包含 capability、handler、connection、resource_mapping 或 internal_api_token
- **THEN** Runtime 合约校验失败且不启动模型调用

