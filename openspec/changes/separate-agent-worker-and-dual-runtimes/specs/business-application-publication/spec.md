## MODIFIED Requirements

### Requirement: 发布前执行跨组件完整校验
系统 MUST 在创建 Business Application Publication 前校验应用状态、草稿完整性、Agent Publication、Workflow Publication、Channel Connector、Trigger、Actor、Delivery、Capability、项目范围和策略约束。所选 Agent Publication MUST 包含受支持且与 Agent Definition 一致的 runtime kind；应用草稿不得再保存独立 Runtime override。

#### Scenario: 发布合法草稿
- **WHEN** enabled 应用的草稿引用有效且范围兼容的 Python 或 TypeScript Agent Publication、其他已发布组件，并且所有策略通过校验
- **THEN** 系统将该 revision 标记为校验通过并允许创建 publication
- **AND** Runtime 由所选 Agent Publication 唯一派生

#### Scenario: 引用已禁用或不存在的组件
- **WHEN** 草稿引用不存在、已禁用、完整性校验失败或项目范围冲突的组件
- **THEN** 系统拒绝发布并返回按字段和组件分类的校验结果
- **AND** 不创建部分 publication

#### Scenario: 未解析Capability
- **WHEN** 草稿包含当前 Capability Catalog 无法解析的编码或版本
- **THEN** 系统拒绝发布并指出未解析的 Capability
- **AND** 不把该编码映射为现有数据库、Redis或Loki内部工具

#### Scenario: Agent Runtime不受支持
- **WHEN** 所选 Agent Publication 的 runtime kind 缺失、不受支持或与 Definition 不一致
- **THEN** 系统拒绝应用发布且不使用环境变量或 Application allowlist 猜测 Runtime

#### Scenario: 应用提交Runtime覆盖
- **WHEN** 应用草稿 payload 同时提交 Agent Publication 和独立 runtime kind/runtime URL
- **THEN** 系统拒绝覆盖字段或明确忽略旧字段，且 Publication 只采用 Agent Publication 的 Runtime

### Requirement: 发布创建不可变且可验证的应用快照
系统 SHALL 为每次成功发布创建不可变 snapshot，冻结应用元数据、组件 Publication ID、组件 revision/version、组件 hash、所选 Agent Publication 的 runtime kind、Trigger、Delivery、Capability引用和策略，并 MUST 保存 snapshot schema version 与 canonical SHA-256。Runtime kind 仅为 Agent Publication 的验证投影，不得成为可独立修改的选择项。

#### Scenario: 创建应用发布快照
- **WHEN** 合法 revision 首次发布
- **THEN** 系统在单一事务中创建 publication、保存 snapshot 与 hash并记录发布审计
- **AND** snapshot 中 Runtime 投影与所选 Agent Publication 一致

#### Scenario: 组件后续产生新版本
- **WHEN** 被引用 Agent 或 Workflow 后续发布新版本
- **THEN** 已有应用 publication 仍引用原 Publication ID、revision、hash 和 Runtime 投影
- **AND** 只有新的应用 revision 和 publication 才能采用新组件

#### Scenario: 检测快照篡改
- **WHEN** 读取 publication 时重新计算的 canonical hash 与保存值不一致、Runtime 投影与 Agent Publication 不一致或 schema version 不受支持
- **THEN** 系统拒绝解析、激活或返回其作为有效配置
- **AND** 记录不包含快照敏感内容的完整性失败审计

## ADDED Requirements

### Requirement: 应用必须通过Agent Publication选择Runtime
Business Application 管理 API 与前端 SHALL 允许管理员从有效 Agent Publication 中选择一个版本，并展示 Agent code、publication revision 和只读 runtime kind。发布新 Agent 不得自动切换任何应用；切换必须创建并发布新的应用 revision，并按现有规则显式激活。

#### Scenario: 应用选择Python Agent
- **WHEN** 管理员选择 `default-diagnostic-agent` 的有效 Publication
- **THEN** 应用页面显示 `python-v1`，后续新 Job 从该 Publication 固定 Python Runtime

#### Scenario: 应用选择TypeScript Agent
- **WHEN** 管理员选择 `typescript-diagnostic-agent` 的有效 Publication 并发布、激活应用
- **THEN** 后续新 Job 固定 `typescript-v1`，既有 Job 和未重新激活的应用版本不受影响

#### Scenario: Agent发布新版本
- **WHEN** 已被应用引用的 Agent 发布新 revision
- **THEN** 应用继续使用原 Agent Publication，直到管理员显式更新、发布并激活应用
