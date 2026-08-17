## MODIFIED Requirements

### Requirement: 发布前执行跨组件完整校验
系统 MUST 在创建 Business Application Publication 前校验应用状态、草稿完整性、Agent Publication、Workflow Publication、Channel Connector、Trigger、Actor、Delivery、MCP Tool 子集、业务范围和策略约束。所选 Agent Publication MUST 包含受支持且一致的 `python-v1` runtime kind；应用草稿不得保存 Runtime override、API Capability 或 Resource Mapping。历史 `typescript-v1` Application Publication 只可读取，不得用于创建新 Publication。

#### Scenario: 发布合法草稿
- **WHEN** enabled 应用引用有效 Python Agent Publication、Agent Envelope 内的 MCP Tool 子集和其它合法组件
- **THEN** 系统允许创建 Publication，Runtime 由 Agent Publication 唯一派生并固定为 `python-v1`

#### Scenario: 引用已禁用或不存在的组件
- **WHEN** 草稿引用不存在、已禁用、完整性失败或范围冲突的组件
- **THEN** 系统拒绝且不创建部分 Publication

#### Scenario: 未解析MCP Tool
- **WHEN** 草稿包含所选 Agent Publication Envelope 中不存在或 schema hash 不一致的 Tool
- **THEN** 系统拒绝并指出未解析 Tool，不映射为其它工具

#### Scenario: Agent Runtime不受支持
- **WHEN** 所选 Agent Publication runtime kind 缺失、为 `typescript-v1`、不受支持或与 Definition 不一致
- **THEN** 系统拒绝且不猜测或改写 Runtime

#### Scenario: 应用提交旧平台字段
- **WHEN** payload 提交 runtime override、API Capability、Handler、Connection 或 Resource Mapping 字段
- **THEN** 系统拒绝旧字段且不保存兼容数据

### Requirement: 历史publication可以显式重新激活
系统 SHALL 允许有权限的用户把仍然满足当前完整性校验且引用 Python Agent Publication 的历史 Application Publication 重新激活到环境以实现回退，并 MUST 支持显式停用环境 deployment。引用 `typescript-v1` Agent Publication 的历史版本 MUST 保持只读且不得重新激活。

#### Scenario: 回退到历史Python版本
- **WHEN** 用户选择一个通过当前完整性和依赖校验且 runtime kind 为 `python-v1` 的历史 publication 并激活
- **THEN** deployment 原子指向该历史 publication
- **AND** 系统记录旧、新 publication ID 和操作人

#### Scenario: 尝试激活历史TypeScript版本
- **WHEN** 用户选择仍引用 `typescript-v1` Agent Publication 的历史 Application Publication
- **THEN** 系统拒绝激活并提示创建引用 Python Agent Publication 的新 revision
- **AND** 当前 deployment 保持不变

#### Scenario: 停用环境部署
- **WHEN** 用户对当前 deployment 执行 deactivate 并提供正确 expected revision
- **THEN** 系统将该环境标记为未激活并移除活动路由投影
- **AND** publication 历史保持不变

### Requirement: 应用必须通过Agent Publication选择Runtime
Business Application 管理 API 与前端 SHALL 允许管理员从有效 Python Agent Publication 中选择一个版本，并展示 Agent code、publication revision 和只读 `python-v1` runtime kind。发布新 Agent 不得自动切换任何应用；切换必须创建并发布新的应用 revision，并按现有规则显式激活。历史 TypeScript Application Publication SHALL 保留原 runtime kind 供审计，但不得成为新草稿来源或重新激活目标。

#### Scenario: 应用选择Python Agent
- **WHEN** 管理员选择有效 Python Agent Publication
- **THEN** 应用页面显示 `python-v1`，后续新 Job 从该 Publication 固定 Python Runtime

#### Scenario: 活动应用从TypeScript迁移到Python
- **WHEN** 现有 deployment 引用历史 TypeScript Agent Publication
- **THEN** 管理员必须创建引用 Python Agent Publication 的新 Application revision、发布并显式激活
- **AND** 系统不修改旧 Application Publication、Agent Publication 或其 hash

#### Scenario: 应用选择TypeScript Agent
- **WHEN** 管理员或旧客户端尝试为新 revision 选择 `typescript-v1` Agent Publication
- **THEN** 系统拒绝发布且不自动替换为相似 Python Agent

#### Scenario: Agent发布新版本
- **WHEN** 已被应用引用的 Python Agent 发布新 revision
- **THEN** 应用继续使用原 Agent Publication，直到管理员显式更新、发布并激活应用
