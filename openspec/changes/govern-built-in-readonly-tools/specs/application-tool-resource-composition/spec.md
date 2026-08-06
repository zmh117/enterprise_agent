## ADDED Requirements

### Requirement: Agent Publication 必须冻结精确内置工具 Envelope
Agent Draft SHALL 对同一稳定 Tool Identifier 至多选择一个 `ACTIVE` Built-in Tool Release；Agent Publish MUST 冻结 Tool Release ID、Handler Version、Implementation Digest、公开 Schema Hash 和模型描述，不得保存名称级或 `latest` 引用。

#### Scenario: Agent 发布精确工具版本
- **WHEN** 管理员发布选择了一个 ACTIVE Tool Release 的 Agent Draft
- **THEN** 新 Agent Publication 包含该精确 Tool Envelope，后续新 Release 不会自动替换它

#### Scenario: 同一 Identifier 选择多个版本
- **WHEN** Agent Draft 对同一稳定 Identifier 选择两个 Tool Release
- **THEN** 系统拒绝保存或发布并指出冲突项

#### Scenario: 发布时 Release 已失效
- **WHEN** Draft 保存后目标 Release 变为 DEPRECATED、DISABLED、ARCHIVED 或精确实现不再 INSTALLED
- **THEN** Agent Publish 重新校验并失败关闭

### Requirement: Application Publication 只能冻结 Agent Tool Envelope 的显式子集
Application Draft MUST 引用精确 Agent Publication，并 SHALL 只允许显式选择该 Publication 中的 Built-in Tool Release 子集；Application Publish MUST 冻结该子集且不得自动继承、替换或独立选择版本。

#### Scenario: 应用选择 Agent 已有工具
- **WHEN** 管理员勾选 Agent Tool Envelope 中的一部分 Tool Release
- **THEN** Application Publication 冻结精确 Application Tool Allowlist

#### Scenario: 应用请求 Agent 未包含工具
- **WHEN** 请求包含 Agent Tool Envelope 中不存在的 Identifier 或不同 Release ID
- **THEN** 后端拒绝保存或发布，前端也不得提供该候选

#### Scenario: Agent 发布新版本
- **WHEN** 同一 Agent 后续发布了新的 Tool Envelope
- **THEN** 既有 Application Draft 和 Publication 不自动切换，必须显式升级并重新校验

### Requirement: 一个逻辑资源槽必须支持 1..N 条精确资源映射
Application Publication SHALL 为每个被选工具的必需逻辑资源槽冻结一条或多条 Mapping；每条 Mapping MUST 包含业务目标 scope、可选 placement、精确 Resource Revision，以及适用时的 Partition Policy Revision 或 Loki Scope Policy Revision。

#### Scenario: 基地数据库服务多个车间
- **WHEN** 一个基地级数据库 Resource Revision 绑定到包含 GL001、GL002、GL003 的应用目标
- **THEN** 同一资源映射可由三个车间继承，但每个车间必须冻结自己的 Partition Policy Revision

#### Scenario: 同一基地同时有云边资源
- **WHEN** 应用为同一数据库 slot 和基地配置 cloud 与 edge 两个 Resource Revision
- **THEN** Publication 保存两条 placement 不同的精确 Mapping，不创建伪基地或伪车间

#### Scenario: 环境没有 placement
- **WHEN** 目标资源没有云边区分
- **THEN** Mapping 的 placement 必须缺省，提交 `none`、`default` 或其它占位值时发布失败

### Requirement: Application Publish 必须证明每个有效组合唯一可解析
发布器 MUST 展开所有已选工具、必需资源槽、应用叶子目标和已配置 placement，并验证每个有效组合恰好命中一个 Mapping；零命中、多个命中、范围重叠、策略不匹配或非 Published 依赖均 MUST 阻止发布。

#### Scenario: 必需资源缺失
- **WHEN** 某 Workshop 的数据库 slot 没有可继承的 Published Resource Revision
- **THEN** Application Publish 拒绝并返回缺失的工具、slot 和目标摘要

#### Scenario: 环境与基地映射重叠
- **WHEN** 同一 slot 和 placement 的环境级与基地级 Mapping 会同时覆盖同一个有效叶子目标
- **THEN** Application Publish 以歧义拒绝，不采用最近父级或优先级规则

#### Scenario: Loki global 与 environment 重叠
- **WHEN** 同一应用的一个环境同时命中 global Loki 和 environment Loki Mapping
- **THEN** Application Publish 拒绝该组合

### Requirement: Application Publication 必须冻结完整解析表
系统 SHALL 在发布时持久化规范化且不可变的目标解析表及内容 Hash，包含 Tool Release、slot、目标、placement、Resource Revision 和策略 revision；运行时 MUST 读取该表而不得查询 Resource Identity 的最新版本。

#### Scenario: Resource 发布新 revision
- **WHEN** Resource Identity 后续发布新 revision，但应用没有重新发布
- **THEN** 既有应用和新建 Job 继续使用 Application Publication 冻结的旧 revision

#### Scenario: Policy 发布新 revision
- **WHEN** Workshop Partition Policy 或 Loki Scope Policy 发布新 revision
- **THEN** 既有 Application Publication 不自动切换

### Requirement: Job 必须复制不可变 Tool Execution Snapshot
Job 创建时 MUST 从活动 Application Publication 复制 Agent Publication ID、Tool Release ID、Handler Version、Implementation Digest、目标路径、可用 placements、全部 Resource Mapping、Partition Policy 与 Loki Scope Policy 的 ID/revision/hash，以及授权事实摘要。

#### Scenario: 新 Job 创建成功
- **WHEN** 入站请求命中一个可执行的 Application Publication 和合法业务目标
- **THEN** 系统在分发前持久化完整 Tool Execution Snapshot

#### Scenario: Job 重试期间配置改变
- **WHEN** Job 首次执行后 Tool Release、Resource 或 Policy 发布了新版本
- **THEN** 重试仍使用原 Snapshot，不能浮动到新版本

#### Scenario: 冻结 Release 被禁用
- **WHEN** Job 重试前其冻结 Tool Release 变为 DISABLED 或 ARCHIVED
- **THEN** 重试按生命周期失败关闭，不得替换为其他 ACTIVE Release

### Requirement: 每次 Tool Call 必须解析一个明确 placement
当 Job Snapshot 为目标保存多个 placement 时，每次 Tool Call MUST 通过受控调用参数或确定性系统路由选择恰好一个 placement，并记录选择；Agent 不得借此改变业务目标或权限范围。

#### Scenario: 目标只有一个 placement
- **WHEN** 某 slot 对 Job 目标仅有 cloud Mapping
- **THEN** 运行时选择 cloud 并记录实际 Resource Revision

#### Scenario: 目标有 cloud 和 edge
- **WHEN** 某 slot 对同一目标同时有 cloud 和 edge Mapping 且调用明确请求其中一个允许值
- **THEN** 运行时只使用该 placement 的精确 Resource Revision

#### Scenario: 多 placement 未明确选择
- **WHEN** 候选包含 cloud 和 edge 但调用与系统路由无法唯一确定一个
- **THEN** 运行时在访问上游前失败关闭，不默认选择 cloud、edge 或第一条

### Requirement: 可调用工具必须满足完整治理交集
运行时 MUST 只暴露并执行同时满足精确实现已安装、Release 可调用、Agent Envelope、Application Allowlist、稳定工具使用授权、业务目标授权、精确资源映射和有效策略的工具。

#### Scenario: 任一交集条件缺失
- **WHEN** Tool Release 已发布但用户没有目标 Workshop 权限或资源映射无效
- **THEN** 模型不得获得该可调用 Tool 定义，直接调用也必须被 Internal API Platform 拒绝

#### Scenario: Agent 伪造资源事实
- **WHEN** Tool 请求尝试覆盖 Resource Revision、tenant、table prefix、Redis prefix 或强制 Loki selector
- **THEN** Internal API Platform 使用 Job Snapshot 中的事实并拒绝冲突输入

### Requirement: Tool Call 审计必须记录精确事实且不含 Secret
系统 SHALL 记录 Job、Application Publication、Tool Release、Handler Version、Implementation Digest、业务目标、实际 placement、Resource Revision、Policy Revision、有效范围 Hash、判定结果和 correlation id；MUST NOT 记录凭据、连接明文或无界业务响应。

#### Scenario: 工具调用成功
- **WHEN** 一个 DB、Redis 或 Loki Tool Call 成功完成
- **THEN** 审计能够还原所用精确版本和范围，同时结果正文只保留有界脱敏摘要

#### Scenario: 资源解析歧义
- **WHEN** 运行时检测到零个或多个候选 Mapping
- **THEN** 系统记录安全的解析原因和候选数量，不记录 endpoint、username 或 Secret 值
