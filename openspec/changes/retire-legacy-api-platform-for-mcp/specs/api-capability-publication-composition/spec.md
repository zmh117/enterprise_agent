## REMOVED Requirements

### Requirement: ACTIVE Release 进入 Agent 和 Application 配置目录
**Reason**: Capability Release 目录删除。
**Migration**: 配置目录只提供代码 MCP Tool Manifest。

### Requirement: Agent Publication 冻结精确 Capability Envelope
**Reason**: Capability Envelope 删除。
**Migration**: Agent Publication 冻结 MCP Tool Envelope。

### Requirement: Application Capability Allowlist 只能是 Agent Envelope 子集
**Reason**: Capability Allowlist 删除。
**Migration**: Application 只选择 Agent MCP Tool 子集。

### Requirement: Application 不独立选择 Capability 版本
**Reason**: Capability 版本不再存在。
**Migration**: Application 继承 Agent Tool schema hash 边界。

### Requirement: Agent 升级时重新验证应用能力子集
**Reason**: Capability 子集删除。
**Migration**: Agent 升级时重新验证 Application MCP Tool 子集。

### Requirement: 既有 Publication 不跟随配置变化
**Reason**: Capability Publication 模型删除。
**Migration**: MCP Tool identifier/schema hash 的不可变发布语义由 Application/Agent 规格承担。

### Requirement: 钉钉应用访问不新增 Capability 用户角色 Grant
**Reason**: Capability grant 删除。
**Migration**: 钉钉应用访问与 MCP Tool grant 继续独立求交。

### Requirement: 发布链替代全局功能开关
**Reason**: Capability 发布链删除。
**Migration**: Tool 是否可用由代码 Manifest、Agent/Application 和权限决定。

### Requirement: Release 状态对选择和历史运行具有确定语义
**Reason**: Capability Release 状态删除。
**Migration**: 历史 Job 保留摘要，新 Job 使用当前代码/发布快照。

