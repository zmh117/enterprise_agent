## MODIFIED Requirements

### Requirement: Platform topology is persisted in PostgreSQL
系统 SHALL 在 PostgreSQL 中持久化 Environment、可选 Base 和可选 Workshop 的真实层级关系、启停状态、别名和扩展元数据；平台 MUST NOT 要求每个 Environment 都有 Base 或每个 Base 都有 Workshop，也不得保存用于补层级的虚节点。

#### Scenario: Create environment base and workshop
- **WHEN** 管理端创建一个环境、该环境下的真实基地和该基地下的真实车间
- **THEN** 系统持久化三层 topology 关系，并能按环境编码返回完整层级

#### Scenario: Create environment leaf
- **WHEN** 管理端创建一个本身就是有效业务目标且没有基地的环境
- **THEN** 系统持久化 Environment leaf，不自动创建默认 Base 或 Workshop

#### Scenario: Create base leaf
- **WHEN** 管理端创建一个没有车间划分的基地
- **THEN** 系统把该 Base 作为有效叶子目标，不要求占位 Workshop

#### Scenario: Disable workshop
- **WHEN** 管理端禁用一个车间配置
- **THEN** 后续 topology snapshot MUST 不包含该车间的启用资源映射

### Requirement: Resource bindings are persisted by scope
系统 SHALL 通过 Application Publication 的不可变 Mapping 在 PostgreSQL 中持久化 DB、Redis、Loki 等逻辑资源槽绑定；一个 slot MUST 支持 1..N 条 `业务目标范围 + 可选 placement → 精确 Resource Revision + 适用策略 Revision` 映射，并 MUST 在发布时拒绝缺失、重叠或歧义组合。

#### Scenario: Bind database to base
- **WHEN** 管理端为一个 Base 的数据库 slot 选择 Published Resource Revision
- **THEN** 系统在新 Application Publication 中保存精确 revision，并允许其 Workshop 后代通过各自 Published Partition Policy 继承

#### Scenario: Bind cloud and edge resources
- **WHEN** 同一逻辑目标的一个 slot 配置 cloud 和 edge 两个 Published Resource Revision
- **THEN** 系统保存两条 placement 不同的不可变 Mapping

#### Scenario: Bind global Loki to environment policy
- **WHEN** 应用使用 global Loki 查询一个 Environment
- **THEN** 系统保存精确 Loki Resource Revision 和该 Environment 的 Published Loki Scope Policy Revision

#### Scenario: Binding resolves ambiguously
- **WHEN** 环境级和基地级 Mapping 在同一 slot、placement 下同时覆盖一个有效叶子目标
- **THEN** Application Publish 拒绝且不保存部分 Publication

### Requirement: Registry exposes stable runtime revision
系统 SHALL 为 topology、Resource Revision、Application Resource Mapping、Workshop Partition Policy 和 Loki Scope Policy 暴露规范化 revision 或 hash，用于证明 runtime snapshot 与 Application Publication 及 Job Snapshot 一致。

#### Scenario: Configuration changes revision
- **WHEN** Environment/Base/Workshop、资源映射或任一策略发布新的不可变 revision
- **THEN** 对应 Draft 或新 Publication 的 revision/hash 发生变化，既有 Publication hash 保持不变

#### Scenario: Runtime reports revision
- **WHEN** Internal API Platform 从 Job Snapshot 解析一次工具调用
- **THEN** 运行状态和审计包含 Publication、Resource 与 Policy 的 ID/revision/hash 摘要

#### Scenario: Resource draft changes only
- **WHEN** 管理员修改尚未发布的 Resource 或 Policy Draft
- **THEN** 既有 Published 和 Effective revision/hash 不发生变化

## ADDED Requirements

### Requirement: Registry must separate resource, policy and publication lifecycle state
Registry MUST 分别持久化 Resource/Policy Draft、Verification Evidence、不可变 Published Revision、Application Publication Binding 和 Runtime Effective 状态；任何一个状态不得被另一个状态覆盖或合并成单一 `enabled` 字段。

#### Scenario: Published resource is not effective
- **WHEN** Resource Revision 已发布但运行时装载失败
- **THEN** Registry 查询同时返回 Published Revision 与不同的 Effective/health 状态，不误报为已生效

#### Scenario: Policy draft changes after verification
- **WHEN** Workshop 或 Loki Policy Draft 的规范化内容变化
- **THEN** 旧 Verification Evidence 失效，但上一 Published Revision 和依赖 Job 保持不变

### Requirement: Registry must enforce optional placement representation
Registry SHALL 只在资源实际存在物理位置差异时保存 `cloud` 或 `edge` placement；无 placement 的 Mapping MUST 保存为缺省值而非字符串占位，并且同一 Mapping 不得同时包含多个 placement。

#### Scenario: Save non-placement resource
- **WHEN** 管理端保存一个没有云边差异的 Redis Mapping
- **THEN** Registry 持久化缺省 placement 并拒绝 `none`、`standalone` 或 `default`

#### Scenario: Save one placement value
- **WHEN** 管理端保存 edge Resource Mapping
- **THEN** Registry 只保存枚举值 `edge`，不把它写入 Environment/Base/Workshop code
