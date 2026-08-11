## REMOVED Requirements

### Requirement: Capability Handler 实现必须来自代码注册表
**Reason**: Capability Handler 概念永久退役。
**Migration**: 实现直接注册为 MCP Tool Manifest。

### Requirement: Handler 可执行集合必须满足全部治理交集
**Reason**: Handler 运行时删除。
**Migration**: MCP Tool Runtime 执行新的工具治理交集。

### Requirement: Handler 逻辑资源槽必须在应用发布时绑定
**Reason**: Resource Mapping 永久退役。
**Migration**: Tool Call 按 Agent 显式提供且实时鉴权的目标直接解析资源。

### Requirement: Job 必须固化不可变 Execution Scope
**Reason**: 旧 Handler Execution Scope 对象删除。
**Migration**: Job 只冻结 Tool 与发布/授权摘要，调用目标进入 Tool Call 审计而非 Job 执行范围。

### Requirement: 通用数据库查询必须作为受治理的只读业务能力
**Reason**: Capability 业务能力模型删除。
**Migration**: `query_database` 作为代码拥有的只读 MCP Tool 保留。
