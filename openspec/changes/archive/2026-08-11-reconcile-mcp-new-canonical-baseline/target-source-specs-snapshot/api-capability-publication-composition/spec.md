# api-capability-publication-composition Specification

## Purpose
TBD - created by archiving change add-governed-api-capability-handlers. Update Purpose after archive.
## Requirements
### Requirement: ACTIVE Release 进入 Agent 和 Application 配置目录
系统 SHALL 把可供新配置使用的 `ACTIVE` Capability Release 投影到 Agent 和 Application 管理目录，并 MUST 展示名称、稳定 Identifier、业务 `description`、Release Revision 和运维状态；管理端 MAY 展示 `release_note`，模型上下文 MUST NOT 包含该字段。

#### Scenario: 管理员配置 Agent
- **WHEN** 目录存在多个 `ACTIVE` Release
- **THEN** 界面默认推荐最新 Release，并允许管理员展开选择仍为 ACTIVE 的旧 Release

#### Scenario: 目录包含 DEPRECATED Release
- **WHEN** 某 Release 已软废弃且已有配置仍引用它
- **THEN** 历史引用处显示警告和可用替代信息，但新配置候选列表不得允许选择它

### Requirement: Agent Publication 冻结精确 Capability Envelope
Agent Draft SHALL 对同一 Capability Identifier 至多选择一个精确 `ACTIVE` Release；Agent Publish MUST 将 Identifier、Release ID、Capability/Handler Revision、公开 Schema hash 和业务描述冻结为不可变 Agent Capability Envelope。

#### Scenario: Agent 选择一个 Capability Release
- **WHEN** 管理员保存并发布选择了 `cap__ones__work_item__search` 某一 ACTIVE Release 的 Agent
- **THEN** Agent Publication 冻结该精确 Release而不跟随后续新版本

#### Scenario: Agent 对同一 Identifier 选择两个 Release
- **WHEN** Agent Draft 包含同一 Identifier 的多个 Release
- **THEN** 系统拒绝保存或发布并指出冲突项

#### Scenario: 发布时 Release 已不再 ACTIVE
- **WHEN** Draft 保存后目标 Release 被废弃、禁用或归档
- **THEN** Agent Publish 重新校验并失败关闭

### Requirement: Application Capability Allowlist 只能是 Agent Envelope 子集
Application Draft MUST 引用精确 Agent Publication，并 SHALL 只允许从该 Publication 的 Agent Capability Envelope 中显式选择 Capability Release 子集；后端 MUST 拒绝任何越过 Agent 上限、替换 Release ID 或自行指定版本的请求。

#### Scenario: 应用选择 Agent 已有能力
- **WHEN** 管理员勾选所选 Agent Publication 中的一部分 Capability
- **THEN** Application Publication 冻结精确子集为 Application Capability Allowlist

#### Scenario: Agent 未选择 Capability
- **WHEN** 应用请求配置 Agent Envelope 中不存在的 Identifier
- **THEN** 系统拒绝保存或发布，应用界面也不得提供该候选

#### Scenario: 应用未选择 Capability
- **WHEN** Agent Envelope 包含某 Release但 Application Allowlist 未包含它
- **THEN** 该 Capability 不得进入该应用的模型 Tool Catalog或执行路径

### Requirement: Application 不独立选择 Capability 版本
Application 配置界面 MUST 直接展示所选 Agent Publication 冻结的精确 Capability Release，且 MUST NOT 提供独立版本选择器或自动解析“最新版本”。

#### Scenario: 应用查看 Agent Capability
- **WHEN** 管理员选择一个精确 Agent Publication
- **THEN** 每个应用候选显示 Agent 已冻结的 Release Revision，管理员只能勾选或取消

#### Scenario: 新 Capability Release 发布
- **WHEN** 相同 Identifier 发布更高 Release Revision
- **THEN** 既有 Agent/Application Draft 与 Publication 均不自动切换

### Requirement: Agent 升级时重新验证应用能力子集
应用切换到新的 Agent Publication 时 MUST 重新校验原 Application Capability Allowlist；若新 Agent 缺少原 Capability、只含 DEPRECATED Release 或公开 Schema 不兼容，系统 MUST 阻止应用发布并要求管理员显式替换或移除。

#### Scenario: 新 Agent 保留兼容 Release
- **WHEN** 应用升级 Agent 且原能力子集在新 Envelope 中存在兼容 ACTIVE Release，并由管理员明确选择
- **THEN** 系统允许创建新的 Application Publication

#### Scenario: 新 Agent 移除原能力
- **WHEN** 新 Agent Envelope 不再包含应用原来选择的 Identifier
- **THEN** 系统阻止发布，不静默删除 Application Allowlist 项

#### Scenario: 新 Agent 只有软废弃版本
- **WHEN** 新 Agent 引用路径只能提供 DEPRECATED Release
- **THEN** 系统阻止新的应用升级并显示替换或移除要求

### Requirement: 既有 Publication 不跟随配置变化
Agent、Application 和 Capability 新发布、软废弃或替代关系 MUST NOT 自动改写既有 Agent/Application Publication；只有管理员显式创建并发布新版本才能升级绑定。

#### Scenario: Agent 发布新版本
- **WHEN** 现有应用仍引用旧 Agent Publication
- **THEN** 应用继续使用旧 Agent Capability Envelope 和 Allowlist

#### Scenario: Capability 设置 replacement
- **WHEN** DEPRECATED Release 指向新的 replacement_release_id
- **THEN** 既有应用不自动替换，管理员必须显式升级并重新发布

### Requirement: 钉钉应用访问不新增 Capability 用户角色 Grant
第一版钉钉 Application Access SHALL 来自消息路由命中绑定活动 Application Publication 的连接器以及实际发送人解析为启用内部用户；该访问资格同时给出 Application Capability Allowlist 的运行资格，系统 MUST NOT 再要求逐用户或逐角色 Capability Code `use` Grant。

#### Scenario: 启用用户命中活动应用
- **WHEN** 钉钉消息由已绑定且启用的内部用户发送，并命中活动应用路由
- **THEN** 用户取得该应用 Allowlist 的候选调用资格，仍须通过 Release、身份、Team 和 Token 校验

#### Scenario: 用户没有 Capability 角色 Grant
- **WHEN** 用户满足钉钉应用访问条件但系统不存在 Capability `use` Grant
- **THEN** 系统不得仅因缺少该 Grant 拒绝已允许的 Capability

#### Scenario: 其他 Trigger 类型访问
- **WHEN** 请求来自非钉钉 Trigger
- **THEN** 系统继续使用该 Trigger 已定义的访问策略，不把钉钉规则扩展为全局规则

### Requirement: 发布链替代全局功能开关
受治理 Capability 只有依次完成 Connection、Capability Release、Agent Publication 和 Application Publication 的显式发布后才能进入运行时；系统 MUST NOT 为该功能新增全局 Feature Flag 或功能开关页面。

#### Scenario: Capability 已发布但应用未选择
- **WHEN** Release 为 ACTIVE 但没有活动 Application Publication允许它
- **THEN** 现有运行时行为不变，模型无法看到或调用该 Capability

#### Scenario: 需要紧急停止
- **WHEN** 运维人员需要阻止某 Capability 的新调用
- **THEN** 使用具体 Release 的 `DISABLED` 状态失败关闭，不删除历史或切换全局开关

### Requirement: Release 状态对选择和历史运行具有确定语义
`DEPRECATED` Release SHALL 允许既有 Application Publication继续执行但阻止新 Agent/Application 选择与升级；`DISABLED` 和 `ARCHIVED` Release MUST 阻止所有新调用；系统 MUST NOT 按日期自动禁用或自动升级。

#### Scenario: 既有应用调用 DEPRECATED Release
- **WHEN** 历史 Application Publication 已冻结一个后来 DEPRECATED 的 Release
- **THEN** 运行时仍可暴露和执行，并在管理端显示废弃警告

#### Scenario: 既有应用调用 DISABLED Release
- **WHEN** 历史 Application Publication 冻结的 Release 已被 DISABLED
- **THEN** Tool 构建或执行失败关闭并记录安全状态原因
