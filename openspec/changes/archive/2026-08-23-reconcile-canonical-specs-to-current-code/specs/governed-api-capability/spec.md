## MODIFIED Requirements

### Requirement: 外部身份与个人 API 凭据分离持久化
系统 SHALL 将 ONES 外部身份事实与用于当前用户只读 ONES 调用的个人 Credential 分表持久化。Credential MUST 使用平台 Master Key 进行用途绑定的认证加密，保存独立状态、revision、验证时间、使用时间和安全错误状态；API、前端、日志、审计、Job、Prompt 和 MCP payload MUST NOT 返回密码、Token、密文、nonce 或可恢复认证材料。

#### Scenario: 用户确认ONES绑定
- **WHEN** 用户确认有效 Challenge 和默认 Team
- **THEN** 系统原子创建或刷新外部身份以及 active 加密 Credential
- **AND** 本人状态只返回安全的 Credential 状态和 revision 等元数据

#### Scenario: Credential不存在或不可用
- **WHEN** 已绑定身份没有 active Credential 或 Credential 无法安全解析
- **THEN** ONES Tool 调用在访问 Provider 前失败关闭并提示重新验证
- **AND** 系统不从身份 metadata、请求参数或环境变量猜测个人凭据

### Requirement: ONES 自助验证分为 Challenge 两阶段
系统 SHALL 将 ONES 自助验证分为“登录验证并创建短期 Challenge”和“选择默认 Team 后确认绑定”两个阶段。Challenge MUST 具有短 TTL、单次消费和用户绑定，并 SHALL 仅保存用途绑定的加密登录材料与 Provider Token；消费、过期、替换或失效时 MUST 清除 Challenge 密文。任何响应、日志或审计不得返回这些认证材料。

#### Scenario: 登录验证成功
- **WHEN** 当前用户提交有效 ONES 登录信息
- **THEN** 系统返回 Challenge ID、过期时间、外部用户安全摘要和 Team 候选
- **AND** Challenge 只在受信存储中保存短期加密认证材料

#### Scenario: Challenge过期或重复确认
- **WHEN** 用户确认已过期、已消费或不属于自己的 Challenge
- **THEN** 系统拒绝写入身份与 Credential，并清理可清理的 Challenge 密文

### Requirement: 现有 ONES 身份记录非破坏迁移
系统 SHALL 保留现有 ONES 外部身份、Team、revision、状态和审计历史；当前只读 ONES Tool 需要 active 个人 Credential，历史身份缺少 Credential 时 MUST 保持身份事实但将业务调用视为不可用，直到本人重新验证生成 Credential。系统不得伪造、共享或从旧 metadata 反推密码与 Token。

#### Scenario: 历史身份没有Credential
- **WHEN** 迁移后用户存在 enabled ONES 身份但没有 active Credential
- **THEN** 身份摘要仍可查询，ONES Tool 调用失败关闭并提示本人重新验证
- **AND** 系统不删除身份或自动生成 Credential

### Requirement: Challenge 确认原子保存默认 Team 和身份
系统 MUST 在同一数据库事务中消费有效 Challenge、处理显式换绑、保存外部身份、完整 Team 候选和默认 Team，并创建或轮换对应 active 加密 Credential。任一步骤失败 MUST 回滚身份与 Credential 变更；Challenge 的失效与密文清理不得因后续失败而长期保留可用认证材料。

#### Scenario: 确认合法默认Team
- **WHEN** 用户提交属于未过期 Challenge 候选集合的 Team ID
- **THEN** 系统原子保存身份、Team 上下文和 active Credential
- **AND** 返回不含认证材料的最新本人状态

#### Scenario: 保存Credential失败
- **WHEN** 身份可写但 Credential 加密或持久化失败
- **THEN** 本次确认不产生部分绑定或部分换绑
- **AND** 用户收到安全的重新验证提示

### Requirement: 解绑和身份停用具有明确状态
本人解绑 ONES 身份时，系统 SHALL 软解绑当前身份并在同一事务中将其个人 Credential 标为 unbound；历史 revision 和审计继续保留。管理员对身份的停用不得暴露或复制 Credential，任何非 enabled 身份或非 active Credential MUST 在 Provider 调用前失败关闭。

#### Scenario: 用户解绑当前ONES账号
- **WHEN** 用户确认解绑
- **THEN** 系统软解绑当前身份并停用对应 Credential
- **AND** 页面不再把该身份或 Credential 作为当前可调用状态

#### Scenario: Credential已停用
- **WHEN** Job 尝试以非 active Credential 调用 ONES
- **THEN** MCP 服务在外部网络访问前拒绝并记录安全错误码

### Requirement: ONES 搜索使用固定只读 GraphQL POST
工作项搜索 MUST 使用代码拥有的固定 GraphQL document 和 Operation，以 POST 调用代码固定的 ONES GraphQL 路径。模型、Agent、Application、数据库和管理 API MUST NOT 修改 document、operation name、URL、Method、Header 模板或响应解析逻辑。

#### Scenario: 执行工作项搜索
- **WHEN** 已授权 Job 调用 `ones_work_item_search`
- **THEN** ONES MCP 使用代码固定 GraphQL document 和变量执行只读 POST
- **AND** 返回经过代码固定解析与限界的工作项摘要

#### Scenario: 输入尝试覆盖请求定义
- **WHEN** Tool 输入包含 GraphQL 文本、URL、Method、Header 或解析模板
- **THEN** 输入 schema 或 Operation 在发起外部请求前拒绝

### Requirement: ONES MCP 第一阶段只发布工作项查询
ONES MCP SHALL 只发布代码 Manifest 固定的两个只读 Tool：`ones_work_item_search` 与 `ones_list_project_role_members`。系统 MUST NOT 发布任意 GraphQL、任意 REST、写操作或数据库动态定义的 ONES Tool。

#### Scenario: 列出ONES MCP工具
- **WHEN** Runtime 为已授权 Job 请求 ONES MCP `tools/list`
- **THEN** 可见集合只能是该 Job 冻结且授权的上述两个 Tool 的子集

#### Scenario: 请求未注册ONES Tool
- **WHEN** 模型请求任意 GraphQL、任意 REST 或其它 ONES Tool 名称
- **THEN** 服务在 Provider 网络访问前拒绝

### Requirement: ONES MCP必须使用SDK v2无状态HTTP
ONES MCP SHALL 使用官方 MCP Python SDK v2 的无状态 Streamable HTTP transport，对外暴露固定的两个代码注册只读 Tool，并由部署固定路径提供无副作用健康检查。Tool 可见性与调用 MUST 绑定有效业务 Principal、当前 Job 冻结集合和发布授权。

#### Scenario: 平台启动ONES MCP
- **WHEN** 容器加载合法配置与代码 Manifest
- **THEN** 服务通过无状态 Streamable HTTP 暴露两个固定 Tool 和健康检查

#### Scenario: 请求不属于当前Job的Tool
- **WHEN** Principal 有效但请求 Tool 不在当前 Job 的 ONES 冻结集合
- **THEN** 服务在解析个人 Credential 或访问 Provider 前拒绝

### Requirement: ONES查询必须使用固定受控Provider请求
ONES 工作项搜索 MUST 使用代码拥有的固定 GraphQL POST Operation；项目角色人员查询 MUST 使用代码拥有的固定两步 REST GET Operation。所有路径、Method、请求字段、超时、响应解析和输出边界 MUST 由代码定义，模型与配置不得提供任意请求模板。

#### Scenario: 工作项搜索
- **WHEN** 调用 `ones_work_item_search`
- **THEN** Provider client 只执行固定 GraphQL Operation

#### Scenario: 查询项目角色人员
- **WHEN** 调用 `ones_list_project_role_members`
- **THEN** Provider client 按代码固定顺序执行项目角色与角色成员两步 GET
- **AND** 输出被规范化为有界角色摘要

#### Scenario: 尝试动态Provider请求
- **WHEN** 输入或配置包含任意 URL、Method、Header、GraphQL 或 REST 模板
- **THEN** 系统拒绝且不发起外部请求

### Requirement: 工作项搜索公开输入契约固定
`ones_work_item_search` Input Schema MUST 只公开 `keyword`、`issue_type` 和 `limit`；`issue_type` MUST 限定为 `demand`、`task`、`defect`，`limit` MUST 为 1 至 50 的整数。User ID、Team ID、Token、Origin、Path 和 GraphQL document MUST NOT 公开。

#### Scenario: Agent提交合法搜索
- **WHEN** Tool Input 包含合法 keyword、issue_type 和 limit
- **THEN** ONES MCP 接受输入并从当前已验证 Principal 与 Credential 注入 User、Team 和 Token

#### Scenario: limit超出范围
- **WHEN** Agent 提交 limit 为 0、51 或非整数
- **THEN** 系统在外部调用前拒绝并返回结构化输入错误

#### Scenario: Agent尝试覆盖Team
- **WHEN** Tool Input 包含 `team_id`、`user_id` 或认证字段
- **THEN** 系统按未知或禁止字段拒绝且不使用这些值

### Requirement: 工作项搜索公开输出契约固定
`ones_work_item_search` Output Schema MUST 返回有界工作项数组，每项只包含 `number`、`name`、`type`，并返回 `total` 和 `truncated`；所有字段 MUST 完整通过代码固定的类型和大小校验后才能交给模型。

#### Scenario: 返回有限搜索结果
- **WHEN** ONES 返回匹配工作项且 Operation 解析成功
- **THEN** 模型只收到契约字段、total 和 truncated 标记

#### Scenario: 单项缺少必填number
- **WHEN** 外部响应中的任一映射项无法产生合法 number
- **THEN** 整次调用按输出契约错误失败且不返回其他部分工作项

#### Scenario: 外部结果超过limit
- **WHEN** ONES 匹配数超过请求 limit
- **THEN** 规范化输出最多包含 limit 项，并通过 total/truncated 明确说明截断

### Requirement: V1 端到端验收覆盖正向发布链
交付验收 MUST 覆盖本人 ONES 绑定与默认 Team、加密 Credential、业务 Principal JWT、Agent 精确选择 `ones_work_item_search`、应用选择 Agent 与 MCP Tool 子集、角色 Tool grant、Python Runtime、`ones-mcp`、受控 ONES Mock 查询、Tool Call 和 MCP Operation Audit。真实外部 ONES 未经授权探测时，验收 MUST 明确标为未验证，不得用 Mock 结果代替。

#### Scenario: 完整Mock正向链成功
- **WHEN** 测试用户完成绑定且 Job 的 Agent、Application 和角色均授权 ONES 查询
- **THEN** Python Runtime 通过 `ones-mcp` 使用该用户的 User、Team 和 Credential 获得规范化 Mock 结果
- **AND** 审计关联入口、Job、Server/Tool/schema、JWT jti、Tool Call、Credential revision、Provider attempt 和结果且不含认证秘密

#### Scenario: 缺少真实外部证据
- **WHEN** 验收没有获得授权的真实 ONES 只读探测结果
- **THEN** 报告只确认本地代码与 Mock 链路
- **AND** 不宣称真实 Provider 端到端已经完成

### Requirement: V1 端到端验收覆盖失败关闭和回归
交付验收 MUST 证明 Tool 未选、角色未授权、JWT 缺失/伪造/过期、用户未绑定、Credential 缺失、401 刷新失败、Team 撤销和身份停用均失败关闭；同时 MUST 证明现有 `tool-mcp` 和未选择 ONES Tool 的历史 Agent/Application 保持原行为。

#### Scenario: 执行全部负向用例
- **WHEN** 测试分别触发发布、授权、JWT、身份、Credential、Team 和 Provider 故障
- **THEN** 每个用例在外部调用前或明确故障点安全失败且无主体或 Team 切换

#### Scenario: 回归旧应用
- **WHEN** 运行没有冻结任何 `ones-mcp` Tool 的历史 Agent/Application Publication
- **THEN** 原有内部只读 Tool、Job 和 Delivery 路径保持原行为

#### Scenario: 回归现有tool-mcp
- **WHEN** 运行只包含原有 `tool-mcp` Tool 的 Job
- **THEN** Runtime 不要求或发送业务 Principal JWT，原有只读 Tool、Job 和 Delivery 路径保持行为

## REMOVED Requirements

### Requirement: 测试 fixture 证明模型侧组合调用
**Reason**: 当前源码与测试没有这两个测试专用 Capability fixture；现有模型组合行为由真实代码注册 MCP Tool 和 Runtime Tool 循环覆盖。

**Migration**: 不创建兼容 fixture 或生产扩展点；使用现有 MCP Tool 合同测试组合调用。

## RENAMED Requirements

- FROM: `ONES MCP 第一阶段只发布工作项查询`
- TO: `ONES MCP只发布两个代码固定只读Tool`
