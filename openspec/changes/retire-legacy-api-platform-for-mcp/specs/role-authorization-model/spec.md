## ADDED Requirements

### Requirement: 角色业务工具授权必须只引用 MCP Tool Identifier
角色 SHALL 继续承载业务应用访问、稳定 MCP Tool 使用权限和业务数据范围；角色模型 MUST NOT 保存或展示 API Capability、Handler、API Connection、Resource Mapping 或 Resource Revision grant。

#### Scenario: 授权 test 环境数据库工具
- **WHEN** 管理员为角色选择应用、`query_database`/`get_schema_directory` MCP Tool 和 `environment=test` 数据范围
- **THEN** 成员的新 Job 可以在应用 Tool 子集内访问 test 目标，资源由 `tool-mcp` 唯一解析

#### Scenario: 旧 Capability 授权字段提交
- **WHEN** 角色授权请求包含 API Capability 或 Resource Mapping
- **THEN** 后端拒绝旧字段且不创建兼容 grant

