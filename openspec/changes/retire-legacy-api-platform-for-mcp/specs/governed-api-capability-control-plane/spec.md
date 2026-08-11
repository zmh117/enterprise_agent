## REMOVED Requirements

### Requirement: 受治理 API Capability 使用专用稳定标识
**Reason**: API Capability 控制面永久退役。
**Migration**: 仍需的只读能力必须实现为代码拥有的 MCP Tool identifier。

### Requirement: 统一工作台保持领域对象分离
**Reason**: Capability/Handler 工作台永久删除。
**Migration**: 管理端只保留 MCP Tool Manifest 只读目录。

### Requirement: Capability 公开契约具有严格 Schema
**Reason**: Capability 对象已删除。
**Migration**: MCP Tool Manifest 直接拥有 input schema。

### Requirement: Handler 只能使用固定声明式执行器
**Reason**: Handler 对象和执行器永久删除。
**Migration**: MCP Tool 实现由代码函数直接注册。

### Requirement: Mapping Plan 只允许确定性投影
**Reason**: Handler Mapping Plan 永久删除。
**Migration**: 每个 MCP Tool 实现直接产生其公开结果。

### Requirement: Draft 写入使用乐观并发控制
**Reason**: Capability/Handler Draft 不再存在。
**Migration**: 无需迁移。

### Requirement: Capability 测试和验证使用当前管理员自己的绑定
**Reason**: Capability 测试工作流已删除。
**Migration**: MCP Tool 使用资源 Draft 验证和受控运行验收。

### Requirement: 测试预览排除认证材料和原始响应
**Reason**: Capability 测试预览已删除。
**Migration**: 工具资源测试仍遵守 Secret 脱敏。

### Requirement: Publish 原子、幂等且创建不可变版本
**Reason**: Capability Publish 已删除。
**Migration**: Tool 通过代码部署，Agent/Application 冻结 identifier/schema hash。

### Requirement: Capability 与 Handler 按变更类型独立版本化
**Reason**: 两类对象永久删除。
**Migration**: 变更通过代码版本和 schema hash 管理。

### Requirement: Release 内容不可变但支持受控运维状态
**Reason**: Capability Release 生命周期永久删除。
**Migration**: 无活动引用时删除 Release 数据。

### Requirement: 管理操作使用细粒度 RBAC 和安全审计
**Reason**: 对应管理操作全部删除。
**Migration**: 移除专用 RBAC capability；保留通用平台审计。

