# ones-work-item-search Specification

## Purpose
TBD - created by archiving change add-governed-api-capability-handlers. Update Purpose after archive.
## Requirements
### Requirement: 第一版只发布一个生产 ONES 查询 Capability
第一版生产范围 MUST 只包含 `cap__ones__work_item__search`，其 `operation_semantics` MUST 为 `QUERY`，数据分级 MUST 为 `INTERNAL`；系统 MUST NOT 在本变更发布 ONES 写入、详情、跨 Team 或其他 Provider Capability。

#### Scenario: 发布工作项搜索
- **WHEN** 管理员完成完整验证和发布
- **THEN** 系统创建稳定 Identifier 下的 QUERY/INTERNAL Release

#### Scenario: 配置 ONES 写操作
- **WHEN** 管理员尝试在第一版使用相同框架发布创建或更新工作项
- **THEN** 发布校验拒绝该操作语义

### Requirement: 工作项搜索公开输入契约固定
`cap__ones__work_item__search` Input Schema MUST 只公开 `keyword`、`issue_type` 和 `limit`；`issue_type` MUST 限定为 `demand`、`task`、`defect`，`limit` MUST 为 1 至 50 的整数。User ID、Team ID、Token、Origin、Path 和 GraphQL document MUST NOT 公开。

#### Scenario: Agent 提交合法搜索
- **WHEN** Tool Input 包含合法 keyword、issue_type 和 limit
- **THEN** 系统接受输入并由平台注入当前 Job快照 User/Team及当前Token

#### Scenario: limit 超出范围
- **WHEN** Agent提交 limit 为 0、51 或非整数
- **THEN** 系统在外部调用前拒绝并返回结构化输入错误

#### Scenario: Agent 尝试覆盖 Team
- **WHEN** Tool Input包含 `team_id`、`user_id`或认证字段
- **THEN** 系统按未知/禁止字段拒绝，且不使用这些值

### Requirement: 工作项搜索公开输出契约固定
Capability Output Schema MUST 返回有界工作项数组，每项只包含 `number`、`name`、`type`，并返回 `total` 和 `truncated`；所有字段 MUST 完整通过类型和大小校验后才能交给模型。

#### Scenario: 返回有限搜索结果
- **WHEN** ONES 返回匹配工作项且 Mapping 成功
- **THEN** 模型只收到契约字段、total和truncated标记

#### Scenario: 单项缺少必填 number
- **WHEN** 外部响应中的任一映射项无法产生合法 number
- **THEN** 整次调用按输出契约错误失败，不返回其他部分工作项

#### Scenario: 外部结果超过 limit
- **WHEN** ONES匹配数超过请求 limit
- **THEN** 规范化输出最多包含 limit 项，并通过 total/truncated明确说明截断

### Requirement: ONES 搜索使用固定只读 GraphQL POST
Handler MUST 使用固定 GraphQL POST document执行搜索，并 MUST 在 Draft验证和发布时解析或检查该 document 为 query；任何 mutation、动态 document 或 Agent提供的 GraphQL文本 MUST 被拒绝。

#### Scenario: 固定 query 通过验证
- **WHEN** Handler配置受支持的只读搜索 query
- **THEN** 系统将该 document冻结在 Handler Revision中

#### Scenario: GraphQL document包含 mutation
- **WHEN** 管理员或客户端提交 mutation operation
- **THEN** 系统拒绝验证和发布，不向 ONES 发起请求

#### Scenario: Agent输入 GraphQL文本
- **WHEN** Tool Input额外包含 query或document字段
- **THEN** Input Schema拒绝该字段，固定 document不受影响

### Requirement: ONES 查询只使用当前发送人的执行主体
私聊和群聊中的 ONES搜索 MUST 使用每条消息实际钉钉发送人映射的内部用户、该用户的外部 User ID、Job冻结default Team和当前有效个人Token；系统 MUST NOT 使用管理员验证凭据、应用服务账号、群共享主体或其他用户身份。

#### Scenario: 群内两个用户先后查询
- **WHEN** 两条群消息分别来自已绑定用户甲和用户乙
- **THEN** 两个 Job分别冻结并使用各自 User、Team和Token，结果不得串用

#### Scenario: 当前发送人未绑定 ONES
- **WHEN** 钉钉用户可以访问应用但没有可用 ONES凭据
- **THEN** 系统不暴露或不执行搜索，并返回安全中文绑定提示

### Requirement: 完整发布链决定搜索可用性
工作项搜索 MUST 只有在 Published Connection、可运行 Capability Release（`ACTIVE`，或被既有 Application Publication 冻结的 `DEPRECATED`）、包含该精确 Release的 Agent Publication、包含其子集的活动 Application Publication以及当前用户个人绑定均有效时才能调用。

#### Scenario: Agent 未配置 Capability
- **WHEN** 应用选择的 Agent Publication不包含搜索 Release
- **THEN** 应用不能选择该能力，模型也不能调用

#### Scenario: 应用未配置 Capability
- **WHEN** Agent包含搜索 Release但Application Allowlist为空
- **THEN** 模型 Tool Catalog不包含搜索能力

#### Scenario: Release 被紧急禁用
- **WHEN** 运行中的应用仍引用搜索 Release但该 Release变为DISABLED
- **THEN** 所有新搜索调用失败关闭，不自动回退到其他 Release

### Requirement: ONES 错误不导致主体或 Team 回退
未绑定、Token无效、Team权限撤销、403或Release禁用 MUST 返回安全失败并保持原Job主体快照；系统 MUST NOT 切换到管理员、服务账号、新绑定或其他Team。

#### Scenario: Token失效
- **WHEN** ONES搜索返回401
- **THEN** 系统使当前用户凭据失效并提示重新验证，不重试或使用共享Token

#### Scenario: Team被撤销
- **WHEN** Job快照Team不再属于用户最新验证集合
- **THEN** 系统在HTTP请求前拒绝并要求重新发起任务

### Requirement: V1 端到端验收覆盖正向发布链
交付验收 MUST 覆盖管理员首连接启动验证与发布、管理员正式自助绑定和选择默认Team、Capability配置/测试/验证/发布、Agent精确选择并发布、应用选择Agent与能力子集并绑定钉钉应用发布、普通用户自助绑定后从钉钉查询并使用自己的User/Team/Token获得规范化结果。

#### Scenario: 完整正向链成功
- **WHEN** 所有控制面步骤和普通用户绑定均按顺序完成
- **THEN** 钉钉用户收到符合公开Output Schema的工作项结果，审计能关联路由、Job、Release、主体快照、Tool Call和Delivery且不含凭据或原始响应

### Requirement: V1 端到端验收覆盖失败关闭和回归
交付验收 MUST 证明Agent未选时应用不能配置、应用未选时模型不能调用，且未绑定、Token失效、Team撤销和Release禁用均失败关闭；同时 MUST 证明现有内部Tool和未升级Agent/Application Publication行为不变。

#### Scenario: 执行全部负向用例
- **WHEN** 测试分别触发发布链缺口和用户凭据/Team/Release故障
- **THEN** 每个用例在外部调用前或明确故障点安全失败，且无主体或Team切换

#### Scenario: 回归旧应用
- **WHEN** 运行未升级且Capability集合为空的历史Agent/Application Publication
- **THEN** 原有内部只读Tool、Job和Delivery路径保持原行为

### Requirement: 测试 fixture 证明模型侧组合调用
测试环境 MUST 提供两个只读、受治理的测试专用 Capability fixture，用于证明模型可以把第一个Capability的规范化输出组织为第二个Capability输入；fixture MUST NOT 成为生产可选能力或隐式服务端管道。

#### Scenario: 双 Capability组合成功
- **WHEN** 测试Agent依次调用fixture A和fixture B，并用A的公开输出构造B输入
- **THEN** 两次调用分别通过独立治理校验并留下独立Tool Call记录

#### Scenario: fixture出现在生产目录
- **WHEN** 生产环境构建Capability候选目录
- **THEN** 系统排除所有测试专用fixture

