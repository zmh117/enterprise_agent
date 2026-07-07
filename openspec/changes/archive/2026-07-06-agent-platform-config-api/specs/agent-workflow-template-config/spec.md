# agent-workflow-template-config Specification

## ADDED Requirements

### Requirement: Agent workflow templates are persisted
系统 SHALL 在 PostgreSQL 中持久化 Agent 诊断流程模板，并 MUST 支持草稿、已发布、禁用等状态。

#### Scenario: Create diagnostic workflow template
- **WHEN** 管理端创建一个订单诊断流程模板
- **THEN** 系统保存模板编码、名称、项目编码、状态、版本、入口节点和扩展设置

#### Scenario: Disable workflow template
- **WHEN** 管理端禁用一个流程模板
- **THEN** 后续运行时选择流程模板时 MUST 不使用该禁用模板

### Requirement: Workflow nodes and edges support drag-and-drop graph editing
系统 SHALL 持久化流程节点、节点位置、节点配置、边、端口和条件配置，以支持后续 Web 拖拽编排。

#### Scenario: Add tool call node
- **WHEN** 管理端在画布中添加一个 Loki 查询节点
- **THEN** 系统保存节点 key、节点类型、标题、画布位置和只读工具调用配置

#### Scenario: Connect two nodes
- **WHEN** 管理端把上下文检索节点连接到工具调用节点
- **THEN** 系统保存边 key、源节点、目标节点、端口和条件配置

### Requirement: Workflow graph is validated before save and publish
系统 SHALL 校验 workflow graph 的结构，至少包括入口节点存在、边引用的节点存在、节点 key 唯一、边 key 唯一和 MVP 只读工具边界。

#### Scenario: Edge references missing node
- **WHEN** 管理端保存一条指向不存在节点的边
- **THEN** 系统拒绝保存并返回图校验错误

#### Scenario: Workflow contains mutation node
- **WHEN** 管理端保存包含写库、删 Redis、重启服务或改代码动作的节点
- **THEN** 系统拒绝保存，因为第一版 workflow 只允许只读诊断流程

### Requirement: Workflow publication creates immutable snapshots
系统 SHALL 在发布流程模板时创建不可变发布快照，运行时后续 MUST 读取发布快照而不是读取正在编辑的草稿图。

#### Scenario: Publish workflow template
- **WHEN** 管理端发布一个合法流程模板
- **THEN** 系统创建新版本发布快照，保存完整 graph snapshot、配置 hash、发布人和发布时间

#### Scenario: Edit draft after publish
- **WHEN** 管理端在发布后继续编辑草稿节点
- **THEN** 已发布快照 MUST 保持不变，直到下一次发布生成新版本

### Requirement: Workflow templates remain configuration until explicitly wired to runtime
系统 SHALL 把 workflow 模板作为配置资产管理，第一版 MUST NOT 因保存或发布模板而自动改变 Agent job 执行链路。

#### Scenario: Save workflow template
- **WHEN** 管理端保存或发布流程模板
- **THEN** 系统只更新配置表和发布快照，不立即启动 Agent job 或执行工具调用
