## REMOVED Requirements

### Requirement: 运行时 Tool Catalog 只暴露完整治理交集
**Reason**: API Capability Runtime 永久退役。
**Migration**: MCP Tool Catalog 使用 Agent/Application/角色/数据范围交集。

### Requirement: 每次 Tool 执行重新校验授权和可用状态
**Reason**: 旧 Capability 执行器删除。
**Migration**: 撤权复核迁移到标准 MCP Tool Runtime。

### Requirement: Job 冻结外部执行主体但不冻结 Token
**Reason**: Capability 外部凭据执行链删除。
**Migration**: 不再为 Job 创建 Capability 外部主体快照。

### Requirement: 主体快照必须实时复核撤权
**Reason**: 外部 Capability 主体快照删除。
**Migration**: 应用和工具权限继续按内部用户复核。

### Requirement: 系统上下文字段不可由 Agent 覆盖
**Reason**: Capability Mapping 输入管线删除。
**Migration**: MCP Tool 系统目标字段仍由 Job 冻结且不可覆盖。

### Requirement: 固定执行管线解释已编译 Mapping Plan
**Reason**: Mapping Plan 和执行管线删除。
**Migration**: 工具实现直接校验输入并返回规范结果。

### Requirement: 外部 HTTP 请求遵守冻结网络和认证边界
**Reason**: 通用 API Capability HTTP executor 删除。
**Migration**: 未来专用外部 MCP Tool 必须另行定义网络边界。

### Requirement: QUERY 调用使用有界重试分类
**Reason**: Capability HTTP 调用删除。
**Migration**: 各 MCP Tool 自身定义受控重试。

### Requirement: 每个 HTTP attempt 独立记录安全元数据
**Reason**: 通用 HTTP attempt 模型删除。
**Migration**: Tool Call 继续记录有界执行摘要。

### Requirement: 原始响应只存在于单次 attempt 内存
**Reason**: Capability HTTP response 管线删除。
**Migration**: MCP Tool 结果仍必须有界和脱敏。

### Requirement: INTERNAL 分类随规范化结果传播
**Reason**: Capability 数据分类对象删除。
**Migration**: MCP Tool 结果统一标记为不可信内部证据。

### Requirement: 外部文本始终是不可信业务数据
**Reason**: Capability 专用结果模型删除。
**Migration**: 等价安全提示由 MCP Tool 结果 envelope 承担。

### Requirement: Agent 可通过公开 Schema 组合 Capability
**Reason**: Capability 组合永久删除。
**Migration**: Agent 只可组合其冻结 MCP Tool 的公开 schema。

