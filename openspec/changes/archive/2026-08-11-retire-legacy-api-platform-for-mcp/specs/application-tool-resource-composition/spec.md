## ADDED Requirements

### Requirement: Agent 与 Application 必须冻结精确 MCP Tool 子集
Agent Publication SHALL 冻结代码 Manifest 中精确 Tool identifier 与 schema hash；Application Publication MUST 只冻结所选 Agent Tool Envelope 的显式子集，不得保存 Capability Release、Handler Version、Resource Mapping 或动态 Server URL。

#### Scenario: 应用选择 Agent 工具子集
- **WHEN** 管理员从 Agent Publication 的 MCP Tool Envelope 选择部分工具并发布应用
- **THEN** Application Publication 冻结 identifier/schema hash 子集且后续代码变化不自动替换

### Requirement: Job 必须冻结工具但不得冻结调用目标
Job 创建时 MUST 冻结 Agent/Application Tool 交集、当前用户有效 Tool grant 与发布/授权摘要；MUST NOT 从 DingTalk Routing Context 或用户消息冻结 `environment`、`base`、`workshop`、`placement`，也 MUST NOT 复制 Application Resource Mapping。目标由 Agent 按已发布 Skill 在每次 Tool Call 中显式提供，并由服务端实时复核当前数据范围。

#### Scenario: 配置在 Job 重试前变化
- **WHEN** Tool Manifest、角色 Grant、工具资源或后续用户消息在 Job 首次执行后变化
- **THEN** 重试继续使用原 Job 工具发布快照，但使用本次 Tool Call 目标，并对撤权、越界和资源歧义失败关闭

#### Scenario: Routing Context 目标为空但消息提供环境
- **WHEN** DingTalk Routing Context 的目标字段为空而当前消息明确要求 `environment=test`
- **THEN** Agent 可以按 Skill 以 `environment=test` 调用已分配 Tool，服务端不得用空 Routing Context 覆盖或拒绝该目标

### Requirement: Tool 可调用性必须满足业务治理交集
运行时 MUST 只暴露同时满足 Agent Envelope、Application 子集、有效角色 Tool grant、应用访问、业务数据范围、Manifest/schema 一致和唯一资源解析的 Tool。

#### Scenario: 用户有工具权限但应用未选择
- **WHEN** 用户具有 Tool grant 但 Application Publication 未选择该 Tool
- **THEN** 模型不得获得该 Tool，直接调用也必须被拒绝

### Requirement: 遗留目标冻结存储必须不存在
系统 MUST NOT 保留 `business_application_revision_target`、`business_application_publication_target`、`agent_job_execution_scope` 或 `agent_job.execution_scope_id/execution_scope_hash` 作为运行目标或授权事实；会话隔离继续使用 `agent_session.execution_scope_hash`，实际工具目标只来自本次 Tool Call 并实时鉴权。

#### Scenario: 已有数据库升级
- **WHEN** 已执行旧目标冻结迁移的数据库升级到本变更最终 schema
- **THEN** 遗留目标表、Job 目标列和索引被删除，而历史 Job 主记录、Tool Call 审计与会话隔离事实保持可读

## REMOVED Requirements

### Requirement: Agent Publication 必须冻结精确内置工具 Envelope
**Reason**: Tool Release/Handler Version 控制面由代码拥有的 MCP Tool Manifest 取代。
**Migration**: 将可证明的精确 Tool identifier/schema hash 回填到 Agent Publication MCP Tool Envelope。

### Requirement: Application Publication 只能冻结 Agent Tool Envelope 的显式子集
**Reason**: 要求由新的 MCP Tool 子集契约替代，不再引用 Built-in Tool Release。
**Migration**: 将应用工具选择转换为 Agent MCP Tool Envelope 的 identifier/schema hash 子集。

### Requirement: 一个逻辑资源槽必须支持 1..N 条精确资源映射
**Reason**: Application Resource Mapping 永久退役。
**Migration**: 删除映射；运行时按 Tool Call 目标和工具资源目录唯一解析。

### Requirement: Application Draft 必须显式声明有限叶子目标
**Reason**: 旧叶子目标矩阵与 Resource Mapping 耦合。
**Migration**: 应用保留业务范围声明；Agent 在调用时选择目标，角色数据范围由服务端实时校验。

### Requirement: Application Publish 必须证明每个有效组合唯一可解析
**Reason**: 发布期 Resource Mapping 矩阵永久退役。
**Migration**: 发布只校验 Tool 子集；实际资源在 Tool Call 时唯一解析并失败关闭。

### Requirement: Application Publication 必须冻结完整解析表
**Reason**: 不再持久化 Application Resource Mapping 解析表。
**Migration**: 删除旧解析表；审计记录实际解析的 Resource Revision。

### Requirement: Job 必须复制不可变 Tool Execution Snapshot
**Reason**: 旧快照包含 Handler Release 和 Resource Mapping。
**Migration**: 使用只含精确 Tool 与发布/授权摘要的新快照替代；目标记录在实际 Tool Call 审计中。

### Requirement: 每次 Tool Call 必须解析一个明确 placement
**Reason**: 旧实现通过 Mapping 选择 placement。
**Migration**: 该安全语义迁移到 `standard-mcp-tool-runtime` 的直接资源解析。

### Requirement: 可调用工具必须满足完整治理交集
**Reason**: 旧交集依赖 Tool Release、Handler 与 Resource Mapping。
**Migration**: 使用新的 MCP Tool、角色、应用、范围和直接资源解析交集。

### Requirement: Tool Call 审计必须记录精确事实且不含 Secret
**Reason**: 旧审计字段依赖 Handler/Mapping/Policy revision。
**Migration**: 使用 MCP Tool identifier/schema、目标、placement 和实际 Resource Revision 审计。
