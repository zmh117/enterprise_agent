## ADDED Requirements

### Requirement: 角色业务工具授权必须只引用 MCP Tool Identifier
角色 SHALL 继续承载业务应用访问、稳定 MCP Tool 使用权限和业务数据范围；角色模型 MUST NOT 保存或展示 API Capability、Handler、API Connection、Resource Mapping 或 Resource Revision grant。

#### Scenario: 授权 test 环境数据库工具
- **WHEN** 管理员为角色选择应用、`query_database`/`get_schema_directory` MCP Tool 和 `environment=test` 数据范围
- **THEN** 成员的新 Job 可以在应用 Tool 子集内访问 test 目标，资源由 `tool-mcp` 唯一解析

#### Scenario: 旧 Capability 授权字段提交
- **WHEN** 角色授权请求包含 API Capability 或 Resource Mapping
- **THEN** 后端拒绝旧字段且不创建兼容 grant

### Requirement: 统一 RBAC 必须是唯一授权事实源
系统 MUST 只使用现行 `rbac_*` 角色、成员、管理能力、应用访问、MCP Tool grant 和数据范围表计算授权；MUST NOT 保留或读取 `permission_policy`、`platform_access_grant`、旧授权清理操作表或 DB-backed 测试兼容层。

#### Scenario: 从包含旧授权数据的数据库升级
- **WHEN** 数据库同时包含现行统一 RBAC 和旧 policy/grant 行
- **THEN** 迁移保留现行用户、角色、成员、应用授权和数据范围，并永久删除旧授权表而不把旧行重新解释为有效权限
