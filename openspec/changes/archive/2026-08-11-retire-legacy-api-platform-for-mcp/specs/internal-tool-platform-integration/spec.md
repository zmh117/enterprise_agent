## REMOVED Requirements

### Requirement: Runtime can select real Internal API Platform
**Reason**: Internal API Platform 服务永久删除。
**Migration**: Runtime 只调用固定 `tool-mcp`。

### Requirement: Internal API requests include execution context
**Reason**: Internal API HTTP 请求删除。
**Migration**: MCP 请求只携带 Job/correlation 标识，服务端读取上下文。

### Requirement: Internal API responses use a safe envelope
**Reason**: Internal API response envelope 删除。
**Migration**: MCP Tool result 使用有界安全 envelope。

### Requirement: Internal API failures are classified
**Reason**: Internal API client/server 错误分类删除。
**Migration**: MCP Tool Runtime 提供稳定 Tool/Resource/Policy 错误码。

### Requirement: Local mock platform can verify HTTP tool flow
**Reason**: mock Internal API Platform 删除。
**Migration**: 使用注入 fake executor 的 MCP 合约测试。

### Requirement: Internal API Platform 必须重新读取 Job 授权事实
**Reason**: 独立平台删除。
**Migration**: `tool-mcp` 直接重新读取 Job 与撤权事实。

### Requirement: Internal API 服务 Token 必须支持受控轮换
**Reason**: Internal API Token 与 HTTP 边界永久删除。
**Migration**: 删除 Token secret、usage、轮换文档和验证器。

