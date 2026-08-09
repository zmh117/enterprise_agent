## ADDED Requirements

### Requirement: 业务应用运维不得依赖 Web 工作台
Agent 与渠道运行仍需要的 Business Application 定义、Publication 和环境状态 SHALL 只通过受认证管理 API/CLI 运维；轻量用户门户 MUST 不提供业务应用创建、编辑、校验、发布、激活或停用入口。

#### Scenario: 管理员登录轻量门户
- **WHEN** 具有 Business Application 管理权限的用户登录门户
- **THEN** 前端仍不显示工作台或隐藏写表单，运维必须使用受控 API/CLI

#### Scenario: 运行时读取保留 Publication
- **WHEN** 新 Job 由已激活的渠道或应用发布创建
- **THEN** Runtime 读取仍需要的精确 Application/Agent 发布事实，但不得解析已删除的 Capability 或旧 Resource Composition

### Requirement: 业务应用发布不得依赖已删除的 API Capability
新建或更新的 Business Application Publication MUST 只引用仍受支持的 Agent、Channel、Delivery、MCP Tool allowlist 与 MCP Resource Deployment 事实；请求包含 Capability、Handler、Connection 或旧 Resource Composition 引用时 MUST 被拒绝。

#### Scenario: 旧客户端提交 Capability Release
- **WHEN** 管理请求包含已删除的 Capability Release ID
- **THEN** API 返回明确的已移除契约错误且不创建 Draft 或 Publication

## REMOVED Requirements

### Requirement: Web提供真实的业务应用列表与详情工作区
**Reason**: 业务应用 Web 工作台退出轻量门户。

**Migration**: 不保留列表或详情页面；历史调试只显示 Job 冻结的安全应用发布摘要。

### Requirement: Web支持受控的应用编辑、校验和发布
**Reason**: 前端不再承担平台配置与发布操作。

**Migration**: 使用统一 Session/RBAC/CSRF 保护的管理 API/CLI，不迁移前端状态。

### Requirement: Capability和数据源安全边界在真实页面中保持有效
**Reason**: 页面被移除，Capability 控制面也彻底删除。

**Migration**: 无页面或 Capability 数据迁移；新 API 只接受代码定义 MCP Tool 与精确 Resource Deployment 引用。

### Requirement: 业务应用工作区满足响应式和可访问性要求
**Reason**: 工作区本身删除，不再构成产品界面。

**Migration**: 无；轻量用户门户的响应式和可访问性要求由其自身规格承担。
