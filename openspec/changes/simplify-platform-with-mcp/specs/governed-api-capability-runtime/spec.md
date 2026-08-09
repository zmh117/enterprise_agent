## REMOVED Requirements

### Requirement: 运行时 Tool Catalog 只暴露完整治理交集
**Reason**: Capability Tool Catalog 与其发布交集彻底删除。

**Migration**: 不物化旧目录；新 Job 使用代码定义 MCP Tool 与精确 allowlist。

### Requirement: 每次 Tool 执行重新校验授权和可用状态
**Reason**: 旧 Capability 执行器删除。

**Migration**: 不保留兼容执行；MCP Server 按短期令牌、scope、Job、身份、凭据和资源实时复核。

### Requirement: Job 冻结外部执行主体但不冻结 Token
**Reason**: Capability Job 凭据解析链删除。

**Migration**: 旧 Job 不迁移；新 Job 由 MCP 主体与凭据解析契约冻结主体并实时解析新 Provider Credential。

### Requirement: 主体快照必须实时复核撤权
**Reason**: 旧 Capability 主体复核实现随 Runtime 删除。

**Migration**: 旧快照不转换；新 MCP Tool Call 使用统一主体契约重新实现撤权复核。

### Requirement: 系统上下文字段不可由 Agent 覆盖
**Reason**: Capability 系统字段与 Mapping 上下文不再存在。

**Migration**: 无；MCP 身份与资源上下文改由鉴权层和隐藏依赖注入，模型同名字段被拒绝。

### Requirement: 固定执行管线解释已编译 Mapping Plan
**Reason**: 固定 Capability 管线与 Mapping Plan 解释器全部删除。

**Migration**: 不转换 Mapping；领域 MCP Tool 代码直接执行受控 Provider 操作。

### Requirement: 外部 HTTP 请求遵守冻结网络和认证边界
**Reason**: 通用 Capability HTTP 客户端与 Connection Revision 删除。

**Migration**: 不保留任意 HTTP 路径；ONES MCP 只连接部署固定的受信 ONES Provider。

### Requirement: QUERY 调用使用有界重试分类
**Reason**: Capability QUERY 调用类型和重试器删除。

**Migration**: 无；每个 MCP Tool 在代码中声明独立超时和错误分类。

### Requirement: 每个 HTTP attempt 独立记录安全元数据
**Reason**: Capability HTTP attempt 表和历史直接删除。

**Migration**: 不转换 attempt；新 MCP Tool Call 记录有界 attempt/provenance。

### Requirement: 原始响应只存在于单次 attempt 内存
**Reason**: 旧 Capability attempt 生命周期删除。

**Migration**: 无历史迁移；新 MCP Server 继续把原始 Provider 响应限制在单次调用内存。

### Requirement: INTERNAL 分类随规范化结果传播
**Reason**: Capability INTERNAL 分类和规范化结果模型删除。

**Migration**: 无；MCP Tool 输出使用代码定义的安全数据分类。

### Requirement: 外部文本始终是不可信业务数据
**Reason**: 旧要求绑定 Capability Runtime 对象，随该运行时删除。

**Migration**: 不迁移旧数据；等价的 MCP Provider 输出不可信边界在 Agent Runtime 新要求中重新定义。

### Requirement: Agent 可通过公开 Schema 组合 Capability
**Reason**: Capability Schema 与 Tool 名全部删除。

**Migration**: 不转换旧组合；Agent 只组合当前 allowlist 中的 MCP Tool 结构化输入输出。
