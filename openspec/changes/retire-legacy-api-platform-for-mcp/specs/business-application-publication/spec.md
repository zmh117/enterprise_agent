## MODIFIED Requirements

### Requirement: 发布前执行跨组件完整校验
系统 MUST 在创建 Business Application Publication 前校验应用状态、草稿完整性、Agent Publication、Workflow Publication、Channel Connector、Trigger、Actor、Delivery、MCP Tool 子集、业务范围和策略约束。所选 Agent Publication MUST 包含受支持且一致的 runtime kind；应用草稿不得保存 Runtime override、API Capability 或 Resource Mapping。

#### Scenario: 发布合法草稿
- **WHEN** enabled 应用引用有效 Python/TypeScript Agent Publication、Agent Envelope 内的 MCP Tool 子集和其它合法组件
- **THEN** 系统允许创建 Publication，Runtime 由 Agent Publication 唯一派生

#### Scenario: 引用已禁用或不存在的组件
- **WHEN** 草稿引用不存在、已禁用、完整性失败或范围冲突的组件
- **THEN** 系统拒绝且不创建部分 Publication

#### Scenario: 未解析MCP Tool
- **WHEN** 草稿包含所选 Agent Publication Envelope 中不存在或 schema hash 不一致的 Tool
- **THEN** 系统拒绝并指出未解析 Tool，不映射为其它工具

#### Scenario: Agent Runtime不受支持
- **WHEN** 所选 Agent Publication runtime kind 缺失、不受支持或与 Definition 不一致
- **THEN** 系统拒绝且不猜测 Runtime

#### Scenario: 应用提交旧平台字段
- **WHEN** payload 提交 runtime override、API Capability、Handler、Connection 或 Resource Mapping 字段
- **THEN** 系统拒绝旧字段且不保存兼容数据

### Requirement: 发布创建不可变且可验证的应用快照
系统 SHALL 为每次成功发布创建不可变 snapshot，冻结应用元数据、组件 Publication ID/revision/hash、Agent runtime kind、Trigger、Delivery、精确 MCP Tool 子集、业务范围和策略，并保存 schema version 与 canonical SHA-256。Snapshot MUST NOT 包含 API Capability、Handler、API Connection 或 Resource Mapping。

#### Scenario: 创建应用发布快照
- **WHEN** 合法 revision 首次发布
- **THEN** 系统在单一事务中创建 Publication、Snapshot、hash 和审计

#### Scenario: 组件后续产生新版本
- **WHEN** Agent、Workflow 或 Tool Manifest 后续变化
- **THEN** 已有 Publication 仍使用冻结版本；只有新应用 Revision 可采用新值

#### Scenario: 检测快照篡改
- **WHEN** canonical hash、Runtime 投影或 Tool schema hash 不一致
- **THEN** 系统拒绝解析和激活并记录安全审计

### Requirement: Resolver确定性读取活动应用
系统 SHALL 按 application/environment 或规范化 Trigger 键解析唯一活动 Publication，并返回 Agent/Workflow、Trigger、Delivery、MCP Tool 子集、业务范围、策略和完整性摘要；MUST NOT 返回旧 Capability/Resource Mapping 或 Secret。

#### Scenario: 按应用解析活动发布
- **WHEN** 查询 enabled 应用在 test 环境的有效配置
- **THEN** Resolver 返回唯一 Publication 与 MCP Tool 子集且不含 Secret

#### Scenario: 按Trigger解析活动应用
- **WHEN** 使用唯一 environment、trigger type、connector ID 和 routing key 查询
- **THEN** Resolver 返回唯一业务应用及活动 Publication

#### Scenario: 没有有效部署
- **WHEN** 应用未激活、已停用或完整性失败
- **THEN** Resolver 返回非重试配置错误且不回退

