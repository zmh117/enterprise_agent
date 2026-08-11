## REMOVED Requirements

### Requirement: Top-level local platform entrypoint remains compatible
**Reason**: local platform entrypoint 物理删除且不保留兼容入口。
**Migration**: 使用 `tool-mcp` service entrypoint。

### Requirement: Local platform implementation is modularized
**Reason**: local platform 模块删除。
**Migration**: 必要 Loki 策略归入 MCP Tool Runtime。

### Requirement: Modularization preserves local platform behavior
**Reason**: 不再保留旧平台行为兼容。
**Migration**: 只保留工具级只读语义。

### Requirement: Tests cover both entrypoint compatibility and module internals
**Reason**: 旧入口和模块不存在。
**Migration**: 测试覆盖 MCP server、resolver 和 executor。

