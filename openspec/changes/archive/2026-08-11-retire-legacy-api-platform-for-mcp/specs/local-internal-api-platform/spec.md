## REMOVED Requirements

### Requirement: Local Internal API Platform is available for development
**Reason**: local Internal API Platform 服务永久删除。
**Migration**: 本地开发启动标准 `tool-mcp`。

### Requirement: Local platform queries real Loki through bounded endpoint
**Reason**: 本地平台 HTTP endpoint 删除。
**Migration**: `tool-mcp` Loki Tool 直接执行有界查询。

### Requirement: Loki query input is constrained
**Reason**: 约束不再由本地平台承担。
**Migration**: 同等约束迁移到 `tool-mcp` Loki executor。

### Requirement: Local context endpoints provide explicit placeholders
**Reason**: 本地 placeholder endpoint 删除。
**Migration**: 未实现的 MCP Tool 不注册。

### Requirement: Unconfigured database and Redis tools are disabled by default
**Reason**: 本地平台服务删除。
**Migration**: 没有唯一可用 Resource 时 MCP Tool 调用失败关闭。

### Requirement: Real Claude and local Loki can be validated end to end
**Reason**: 旧 E2E 链路退役。
**Migration**: 验收改为 Runtime→tool-mcp→Loki Resource。

