# governed-api-capability Specification

## Purpose
定义外部 API Connection、认证配置、个人凭据、Capability、Handler、Release 及 ONES 能力的治理契约。

## Requirements

<!-- Reconciled from mcp_new capability: `external-api-credential-binding` -->

### Requirement: 外部身份与个人 API 凭据分离持久化
系统 MUST 保留 ONES External Identity 证明外部主体，并 MUST 删除仅服务于旧 API Connection/Capability 的长期 External API Credential。邮箱和密码只存在于单次身份验证请求；登录 Token、密码、邮箱和原始响应 MUST NOT 持久化。身份记录只保存 ONES User ID、显示名称、已验证 Team、默认 Team 和验证时间。

#### Scenario: 用户完成 ONES 身份绑定
- **WHEN** 两阶段身份验证成功并选择默认 Team
- **THEN** 系统只保存身份与 Team 事实，不创建个人业务调用 Token 或 Connection Revision 关联

#### Scenario: 管理员查看用户绑定
- **WHEN** 管理员读取他人的 ONES 外部身份
- **THEN** API 只返回允许的身份、Team、状态和验证时间，不返回邮箱、密码、Token 或可逆密文

### Requirement: ONES 自助验证分为 Challenge 两阶段
ONES 自助绑定第一阶段 MUST 从认证会话确定当前内部用户，使用服务端固定的 ONES 身份验证配置调用固定登录端点，并创建与当前用户绑定的短时单次身份 Challenge。Challenge 只可包含已验证 ONES User ID、显示名称、Team 候选、过期时间和状态；MUST NOT 保存邮箱、密码、登录 Token、API Connection 或 MCP 配置。

#### Scenario: 第一阶段验证成功
- **WHEN** 当前用户提交有效邮箱密码
- **THEN** 系统在当前请求内丢弃邮箱、密码、Token 和原始响应，并返回 Challenge ID 与安全 Team 候选

#### Scenario: 第一阶段验证失败
- **WHEN** ONES 拒绝凭据或响应不符合固定身份协议
- **THEN** 系统不创建 Challenge 或身份，并返回不泄露账号与认证材料的安全错误

### Requirement: 切换默认 Team 必须重新验证
用户切换 ONES 默认 Team MUST 重新提交邮箱密码并创建新身份 Challenge，以 ONES 当前返回的 Team 集合为准；系统 MUST NOT 允许直接从历史 Team 集合切换。

#### Scenario: 历史 Team 已被撤销
- **WHEN** 旧绑定包含某 Team 但新验证响应不再包含它
- **THEN** 系统不得允许选择该 Team，并以最新集合整体替换旧集合

### Requirement: 第一版每个用户只有一个有效 ONES 账号
每个内部用户最多一个当前有效 ONES Identity 和一个默认 Team；界面和 API MUST NOT 提供任意实例、Connection、MCP Server 或账号选择器。

#### Scenario: 用户尝试绑定不同 ONES 主体
- **WHEN** 当前用户已有有效主体却确认另一个 User ID
- **THEN** 系统要求显式换绑确认并原子软解绑旧主体，不得同时保留两个当前账号

#### Scenario: 外部主体已属于其他内部用户
- **WHEN** 经验证 ONES User ID 已绑定另一个启用内部用户
- **THEN** 系统返回冲突，不自动迁移或共享身份

### Requirement: 本人和管理员复用外部身份面板
`ExternalIdentityPanel` SHALL 支持本人模式与管理员治理模式。“我的外部身份”允许绑定、重新验证、选择默认 Team 和解绑本人 ONES；人员管理中的 ONES 治理模式只允许查看、停用和审计，不得显示 ONES 邮箱密码表单，不得代用户验证或解绑。

#### Scenario: 管理员查看本人
- **WHEN** 管理员在人员详情查看自己的记录
- **THEN** 面板仍使用治理模式且不得调用本人验证接口

### Requirement: 当前身份与历史记录明确分层
本人模式 MUST 只返回当前绑定；治理模式 MUST 分开当前身份与默认折叠的 `unbound` 历史。历史记录不得伪装成当前绑定。

#### Scenario: 用户存在旧 ONES 历史和当前绑定
- **WHEN** 同一用户同时存在历史和当前 ONES 身份
- **THEN** 本人只看当前身份，管理员只在历史区域查看旧记录

### Requirement: 现有 ONES 身份记录非破坏迁移
已有 ONES User ID、Team 和验证时间 MUST 保留；已经执行删除个人 API Credential 的数据库 MUST 通过向前迁移恢复身份专用 Challenge，而不是恢复旧 Credential 表或 Token。

#### Scenario: 旧用户打开外部身份面板
- **WHEN** 用户存在 ONES 身份元数据但没有个人 API Credential
- **THEN** 面板正常展示身份与 Team，并允许本人重新验证，不提示缺少业务调用 Token

### Requirement: Challenge 确认原子保存默认 Team 和身份
第二阶段 MUST 校验 Challenge 属于当前用户、未过期且未消费，并只允许选择 Challenge 候选中的 Team。成功后 MUST 在一个事务中保存或更新 ONES User ID、显示名称、最新 Team 集合、默认 Team 和验证时间，并将 Challenge 标记为已消费；不得创建业务调用 Credential。

#### Scenario: 用户选择合法默认 Team
- **WHEN** 当前用户提交有效 Challenge 和候选中的 Team ID
- **THEN** 系统原子更新身份事实，且后续重复消费同一 Challenge 被拒绝

#### Scenario: 用户选择候选外 Team
- **WHEN** 提交 Team ID 不在本次已验证候选集合中
- **THEN** 系统拒绝确认且不改变现有身份

### Requirement: 身份操作使用本人权限和受限管理员权限
本人验证、重新验证、选择 Team 和解绑 MUST 只作用于认证会话用户；管理员仅可按身份治理权限读取或停用，不得提交邮箱密码、代表用户重新验证或解绑 ONES。

#### Scenario: 管理员尝试代用户重新验证
- **WHEN** 管理员在他人上下文提交邮箱密码或验证请求
- **THEN** 系统拒绝且不访问 ONES 登录端点

### Requirement: 解绑和身份停用具有明确状态
本人解绑 MUST 软解绑身份；管理员停用 MUST 只改变身份状态，且管理员解绑 ONES MUST 被拒绝。状态变更保留审计，不触发 API Credential、Capability 或 MCP 变更。

#### Scenario: 用户解绑 ONES
- **WHEN** 本人确认解绑
- **THEN** 系统软解绑当前身份并保留历史事实


<!-- Reconciled from mcp_new capability: `ones-work-item-search` -->

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
