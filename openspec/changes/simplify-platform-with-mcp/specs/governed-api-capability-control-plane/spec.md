## REMOVED Requirements

### Requirement: 受治理 API Capability 使用专用稳定标识
**Reason**: 通用 API Capability 控制面彻底退役，稳定标识和专属持久化不再存在。

**Migration**: 不迁移旧标识；需要的能力以代码定义 MCP Server 与 Tool 名重新注册。

### Requirement: 统一工作台保持领域对象分离
**Reason**: Capability/Handler/Connection 工作台及其领域对象全部删除。

**Migration**: 无页面或数据兼容；领域 MCP Tool 由代码拥有。

### Requirement: Capability 公开契约具有严格 Schema
**Reason**: 公开契约不再由 Capability 记录管理。

**Migration**: 不转换旧 Schema；MCP Tool 使用代码中的结构化输入输出 Schema。

### Requirement: Handler 只能使用固定声明式执行器
**Reason**: Handler Registry 与声明式执行器随控制面删除。

**Migration**: 不保留 Handler；允许的 Provider 操作直接在领域 MCP Server 代码中实现并测试。

### Requirement: Mapping Plan 只允许确定性投影
**Reason**: Mapping Plan 对象和执行器全部删除。

**Migration**: 不转换旧 Mapping；MCP Tool 返回代码定义的有界结构化结果。

### Requirement: Draft 写入使用乐观并发控制
**Reason**: Capability/Handler/Connection Draft 不再存在。

**Migration**: 无；新 Resource 与 Secret 写入继续各自使用 expected revision。

### Requirement: Capability 测试和验证使用当前管理员自己的绑定
**Reason**: Capability 测试入口与其凭据解析路径删除。

**Migration**: 无；ONES MCP 仅通过真实 Job 主体调用，资源技术验证通过 CLI 执行且不进入模型。

### Requirement: 测试预览排除认证材料和原始响应
**Reason**: Capability 测试预览 API 和数据删除。

**Migration**: 无；MCP 调试只保留脱敏 provenance 与结果摘要。

### Requirement: Publish 原子、幂等且创建不可变版本
**Reason**: Capability Publish 和不可变 Release 模型被删除。

**Migration**: 不转换 Release；代码发布 MCP Tool，资源发布使用独立不可变 Resource Revision。

### Requirement: Capability 与 Handler 按变更类型独立版本化
**Reason**: 两类版本对象均彻底退役。

**Migration**: 无；MCP Server 版本、Tool Schema Hash 和 Resource Revision 分别记录新事实。

### Requirement: Release 内容不可变但支持受控运维状态
**Reason**: Capability Release 数据直接删除且不提供历史读取。

**Migration**: 无；MCP Server 版本只能随代码部署变化。

### Requirement: 管理操作使用细粒度 RBAC 和安全审计
**Reason**: Capability 专属管理操作、权限与审计事件删除。

**Migration**: 无；通用身份/RBAC继续保护新的 CLI 管理 API，但不保留旧 Capability 权限或事件。
