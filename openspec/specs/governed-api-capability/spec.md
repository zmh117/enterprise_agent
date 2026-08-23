# governed-api-capability Specification

## Purpose
定义当前 ONES 外部身份凭据、代码固定只读 MCP Tool、Provider Operation、业务 Principal 与安全审计契约，并保留对已退役动态 API 平台对象的失败关闭边界。

## Requirements

<!-- Reconciled from mcp_new capability: `external-api-credential-binding` -->

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

### Requirement: 身份操作使用本人权限和受限管理员权限
本人验证、重新验证、选择 Team 和解绑 MUST 只作用于认证会话用户；管理员仅可按身份治理权限读取或停用，不得提交邮箱密码、代表用户重新验证或解绑 ONES。

#### Scenario: 管理员尝试代用户重新验证
- **WHEN** 管理员在他人上下文提交邮箱密码或验证请求
- **THEN** 系统拒绝且不访问 ONES 登录端点

### Requirement: 解绑和身份停用具有明确状态
本人解绑 ONES 身份时，系统 SHALL 软解绑当前身份并在同一事务中将其个人 Credential 标为 unbound；历史 revision 和审计继续保留。管理员对身份的停用不得暴露或复制 Credential，任何非 enabled 身份或非 active Credential MUST 在 Provider 调用前失败关闭。

#### Scenario: 用户解绑当前ONES账号
- **WHEN** 用户确认解绑
- **THEN** 系统软解绑当前身份并停用对应 Credential
- **AND** 页面不再把该身份或 Credential 作为当前可调用状态

#### Scenario: Credential已停用
- **WHEN** Job 尝试以非 active Credential 调用 ONES
- **THEN** MCP 服务在外部网络访问前拒绝并记录安全错误码


<!-- Reconciled from mcp_new capability: `ones-work-item-search` -->

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

### Requirement: ONES 搜索使用固定只读 GraphQL POST
工作项搜索 MUST 使用代码拥有的固定 GraphQL document 和 Operation，以 POST 调用代码固定的 ONES GraphQL 路径。模型、Agent、Application、数据库和管理 API MUST NOT 修改 document、operation name、URL、Method、Header 模板或响应解析逻辑。

#### Scenario: 执行工作项搜索
- **WHEN** 已授权 Job 调用 `ones_work_item_search`
- **THEN** ONES MCP 使用代码固定 GraphQL document 和变量执行只读 POST
- **AND** 返回经过代码固定解析与限界的工作项摘要

#### Scenario: 输入尝试覆盖请求定义
- **WHEN** Tool 输入包含 GraphQL 文本、URL、Method、Header 或解析模板
- **THEN** 输入 schema 或 Operation 在发起外部请求前拒绝

### Requirement: ONES 查询只使用当前发送人的执行主体
私聊和群聊中的 ONES 搜索 MUST 使用每条消息实际钉钉发送人映射的内部用户。Identity Service SHALL 从该用户的运行 Job 签发 `aud=ones-mcp` 的 Principal JWT；MCP SHALL 再解析该用户当前唯一启用的 ONES User ID、默认 Team 和 ACTIVE credential。系统 MUST NOT 使用管理员验证凭据、应用服务账号、群共享主体、其它用户身份或 Tool 参数提供的身份值。
#### Scenario: 群内两个用户先后查询
- **WHEN** 两条群消息分别来自已绑定用户甲和用户乙
- **THEN** 两个 Job 分别签发自己的 Principal JWT，并使用各自 User、Team 和 Token，结果不得串用
#### Scenario: 当前发送人未绑定ONES
- **WHEN** 钉钉用户可以访问应用但没有启用 ONES 身份或 ACTIVE credential
- **THEN** 系统不执行搜索，并返回安全中文绑定/重验提示
#### Scenario: Tool参数尝试冒充用户
- **WHEN** 模型输入包含 system user、ONES user、Team 或 Token
- **THEN** Tool schema 拒绝调用且不访问 Provider

### Requirement: ONES 错误不导致主体或 Team 回退
未绑定、credential 不可用、Team 权限撤销、403、Principal JWT/Tool 授权失效 MUST 返回安全失败并保持原 Job 平台主体；系统 MUST NOT 切换到管理员、服务账号、新绑定、其它用户或其它 Team。首次401只允许使用同一身份的加密登录材料自动登录并重试一次。
#### Scenario: Team被撤销
- **WHEN** 当前默认 Team 不再属于最新登录响应的 Team 集合
- **THEN** 系统拒绝更新 Token 和执行查询，并要求重新验证/选择 Team
#### Scenario: Token失效后刷新成功
- **WHEN** ONES 搜索首次返回401且当前登录材料仍有效
- **THEN** 系统验证同一 subject/Team、更新 Token 并重试一次，不使用共享 Token
#### Scenario: Token刷新失败
- **WHEN** 自动登录失败、subject/Team 变化或第二次查询仍401
- **THEN** 系统标记 REAUTH_REQUIRED 并要求当前用户本人重验，不回退身份或继续重试

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


<!-- Integrated from archived change: `2026-08-23-add-identity-aware-ones-mcp/specs/identity-aware-ones-mcp` -->

### Requirement: ONES MCP只发布两个代码固定只读Tool
ONES MCP SHALL 只发布代码 Manifest 固定的两个只读 Tool：`ones_work_item_search` 与 `ones_list_project_role_members`。系统 MUST NOT 发布任意 GraphQL、任意 REST、写操作或数据库动态定义的 ONES Tool。

#### Scenario: 列出ONES MCP工具
- **WHEN** Runtime 为已授权 Job 请求 ONES MCP `tools/list`
- **THEN** 可见集合只能是该 Job 冻结且授权的上述两个 Tool 的子集

#### Scenario: 请求未注册ONES Tool
- **WHEN** 模型请求任意 GraphQL、任意 REST 或其它 ONES Tool 名称
- **THEN** 服务在 Provider 网络访问前拒绝

<!-- Integrated from archived change: `2026-08-23-add-identity-aware-ones-mcp/specs/identity-aware-ones-mcp` -->

### Requirement: ONES MCP必须使用SDK v2无状态HTTP
ONES MCP SHALL 使用官方 MCP Python SDK v2 的无状态 Streamable HTTP transport，对外暴露固定的两个代码注册只读 Tool，并由部署固定路径提供无副作用健康检查。Tool 可见性与调用 MUST 绑定有效业务 Principal、当前 Job 冻结集合和发布授权。

#### Scenario: 平台启动ONES MCP
- **WHEN** 容器加载合法配置与代码 Manifest
- **THEN** 服务通过无状态 Streamable HTTP 暴露两个固定 Tool 和健康检查

#### Scenario: 请求不属于当前Job的Tool
- **WHEN** Principal 有效但请求 Tool 不在当前 Job 的 ONES 冻结集合
- **THEN** 服务在解析个人 Credential 或访问 Provider 前拒绝

<!-- Integrated from archived change: `2026-08-23-add-identity-aware-ones-mcp/specs/identity-aware-ones-mcp` -->

### Requirement: ONES查询公开输入输出必须有界
`ones_work_item_search` SHALL 只接受 `keyword`、`issue_type` 和 `limit`；`keyword` 长度为 1..200，`issue_type` 只允许 `demand|task|defect`，`limit` 为 1..50。输出 SHALL 只包含有界 `number/name/type` 列表、`total`、`truncated` 和 `untrusted_data=true`。

#### Scenario: 合法查询
- **WHEN** Agent 提交合法 keyword、issue type 和 limit
- **THEN** MCP 返回不超过 limit 的规范化工作项结果

#### Scenario: 输入尝试覆盖身份或GraphQL
- **WHEN** Tool Input 包含 user ID、Team、Token、URL、Header、query、document 或其它额外字段
- **THEN** 输入 schema 拒绝整个调用且不访问数据库凭据或 ONES

<!-- Integrated from archived change: `2026-08-23-add-identity-aware-ones-mcp/specs/identity-aware-ones-mcp` -->

### Requirement: ONES MCP必须从平台Principal解析业务身份
ONES MCP SHALL 使用 JWT `sub` 和 `job_id` 解析当前系统用户唯一启用的 ONES 身份、当前默认 Team 和 ACTIVE 凭据；Tool Input MUST NOT 决定这些值。

#### Scenario: 当前用户已绑定且凭据有效
- **WHEN** `sub` 对应启用用户、启用 ONES 身份、有效默认 Team 和 ACTIVE 凭据
- **THEN** MCP 使用该身份的 ONES User ID、Team 和 Token 调用查询

#### Scenario: 当前用户未重验旧绑定
- **WHEN** 用户存在 ONES 身份事实但没有本变更创建的 ACTIVE 加密凭据
- **THEN** MCP 返回需要本人重新验证的安全错误且不调用 ONES

#### Scenario: 多个当前ONES身份
- **WHEN** 同一用户出现多个未解绑 ONES 身份或默认 Team 不唯一
- **THEN** MCP 以身份数据不一致失败关闭，不任意选择记录

<!-- Integrated from archived change: `2026-08-23-add-identity-aware-ones-mcp/specs/identity-aware-ones-mcp` -->

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

<!-- Integrated from archived change: `2026-08-23-add-identity-aware-ones-mcp/specs/identity-aware-ones-mcp` -->

### Requirement: Token失效后必须自动重新登录一次
ONES MCP SHALL 在查询首次返回 401 后解析当前加密登录材料，调用固定登录端点并严格验证返回 subject 与 Team；成功后 MUST 以 credential revision 条件更新加密 Token，并最多重试原查询一次。

#### Scenario: 401后重新登录成功
- **WHEN** 缓存 Token 被 Mock 拒绝但加密邮箱和密码仍有效
- **THEN** MCP 登录取得新 Token、更新 credential revision、重试一次查询并返回成功结果

#### Scenario: 其它实例已经刷新Token
- **WHEN** MCP 处理 401 时发现数据库 credential revision 已变化
- **THEN** MCP 使用较新 Token 重试，不用旧 revision 覆盖数据库

#### Scenario: 重新登录身份变化
- **WHEN** 登录返回的 ONES User ID 与已绑定 subject 不同或默认 Team 不在返回 Team 集合
- **THEN** MCP 标记凭据为 `REAUTH_REQUIRED`、不更新身份事实并返回安全错误

#### Scenario: 重试仍然401
- **WHEN** 更新 Token 后原查询再次返回 401
- **THEN** MCP 不进行第二次登录，标记需要重验并失败关闭

<!-- Integrated from archived change: `2026-08-23-add-identity-aware-ones-mcp/specs/identity-aware-ones-mcp` -->

### Requirement: ONES认证秘密不得离开受信执行边界
ONES MCP MAY 在进程内短暂解密登录材料和 Token，但 MUST NOT 把密码、Token、Principal JWT、Authorization/Cookie、密文或 nonce 返回给 Runtime、模型或用户，也不得写入 Tool event、审计、日志、异常、metric label 或终端 ledger。ONES 邮箱/User ID 和完整有界查询业务载荷 SHALL 进入受权限和保留期控制的 MCP 操作审计。

#### Scenario: 扫描成功与失败证据
- **WHEN** 测试完成绑定、查询、401刷新和失败路径
- **THEN** MCP 操作审计包含预期邮箱/User ID 与完整有界查询业务载荷，数据库公开投影、所有审计、日志、Runtime 事件和 Tool 输出中都找不到密码、Token、Principal JWT、Authorization/Cookie、密文或 nonce

<!-- Integrated from archived change: `2026-08-23-add-identity-aware-ones-mcp/specs/identity-aware-ones-mcp` -->

### Requirement: 管理前端必须兼容代码注册的MCP Server Code
Agent 与 Application 管理前端 SHALL 使用共享的有界代码格式解析治理目录中的 `server_code`，MUST NOT 把当前 `tool-mcp`、`ones-mcp` 或未来 Server 名称硬编码为封闭枚举。该解析兼容性 MUST NOT 允许客户端提供 Server URL、Header、凭据或绕过后端 Manifest 与 Runtime 注册表。

#### Scenario: 治理目录增加新MCP Server
- **WHEN** 后端代码 Manifest 返回格式合法的新增 `server_code` 和只读 Tool 定义
- **THEN** Agent 详情与 Application Tool 选择页面正常解析并展示目录，不因未知 Server 名称停留在加载态

#### Scenario: 治理目录返回非法Server Code
- **WHEN** `server_code` 为空、超长、包含 URL 或不符合代码格式
- **THEN** 前端拒绝该响应并显示加载错误，不把该值用于 Runtime 地址解析

<!-- Integrated from archived change: `2026-08-23-add-identity-aware-ones-mcp/specs/ones-work-item-search` -->

### Requirement: 工作项搜索必须作为固定ONES MCP Tool发布
系统 SHALL 以代码 manifest 发布 `server_code=ones-mcp`、`tool_identifier=ones_work_item_search` 和固定 schema hash；只有 Agent Publication、Application Publication 子集和当前角色 Tool grant 同时包含该精确 Tool 时，Runtime 才能向模型暴露它。

#### Scenario: Agent和应用均选择Tool
- **WHEN** 已发布 Agent 包含该 Tool、应用选择其子集且角色授权
- **THEN** Job 快照冻结 server code、identifier 和 schema hash，Runtime 可向模型暴露精确 MCP Tool 名

#### Scenario: 应用未选择Tool
- **WHEN** Agent 包含查询 Tool 但 Application MCP Tool 子集不包含它
- **THEN** Job 快照和模型 Tool Catalog 均不包含该查询

#### Scenario: Schema drift
- **WHEN** Job 冻结 schema hash 与代码 manifest 不一致
- **THEN** Worker 或 MCP 在 Provider 调用前失败关闭并要求重新发布

<!-- Integrated from archived change: `2026-08-23-govern-reusable-ones-query-assets/specs/governed-api-capability` -->

### Requirement: 系统必须提供项目角色人员只读 Tool
系统 MUST 在 `ones-mcp` 代码 Manifest 中提供 `ones_list_project_role_members`，只查询当前 Principal 默认 Team 内指定项目的角色和人员。该 Tool MUST 为只读、`INTERNAL` 数据分级，MUST NOT 创建 API Capability、Handler、Release 或动态 HTTP 实现。

#### Scenario: Tool 在代码 Manifest 中暴露
- **WHEN** `ones-mcp` 使用完整且无冲突的 Tool Manifest 启动
- **THEN** `tools/list` 返回 `ones_list_project_role_members` 的稳定业务 schema，而不返回 REST URL、Header 或原始响应结构

<!-- Integrated from archived change: `2026-08-23-govern-reusable-ones-query-assets/specs/governed-api-capability` -->

### Requirement: 项目角色人员 Tool 输入必须只包含项目 UUID
`ones_list_project_role_members` Input Schema MUST 只接受非空且长度受限的 `project_uuid`。Team UUID、User ID、Token、URL、Method、Path、Header 和请求体 MUST NOT 由模型提供。

#### Scenario: 合法项目 UUID
- **WHEN** 已授权用户提交合法 `project_uuid`
- **THEN** Service 使用当前 Principal 的默认 Team 和该项目 UUID 构造固定 REST Path

#### Scenario: 调用方提交额外请求字段
- **WHEN** 输入包含 Team、用户、Token、URL、Method、Header 或 Body
- **THEN** Tool 在外部请求前拒绝调用

<!-- Integrated from archived change: `2026-08-23-govern-reusable-ones-query-assets/specs/governed-api-capability` -->

### Requirement: 项目角色人员 Tool 必须执行固定两步 REST 查询
Service MUST 先按已提供契约调用固定项目角色成员 GET，保留角色顺序并收集所有 member UUID；随后 MUST 去重 UUID 并按已提供契约调用固定 Team users POST；最后 MUST 以 UUID 将用户姓名映射回各角色。调用集合和顺序 MUST 由代码固定。

#### Scenario: 两步查询成功
- **WHEN** GET 返回合法角色/成员 UUID，POST 返回全部请求用户的 UUID/姓名
- **THEN** Tool 按原角色顺序返回每个角色及其成员 UUID/姓名

#### Scenario: 项目没有角色人员
- **WHEN** GET 按已提供空结果契约返回空角色列表或角色成员为空
- **THEN** Tool 返回合法空结果，不伪造人员且不执行无必要的用户查询

#### Scenario: 用户响应缺少成员
- **WHEN** POST 没有返回 GET 中引用的某个成员 UUID
- **THEN** Tool 按 Provider 响应不完整失败，不省略该成员或返回错误姓名

<!-- Integrated from archived change: `2026-08-23-govern-reusable-ones-query-assets/specs/governed-api-capability` -->

### Requirement: 项目角色人员 Tool 输出必须是有界角色摘要
Output Schema MUST 返回 `roles` 和 `untrusted_data: true`。每个角色只包含 `role_uuid`、`role_name` 和 `members`；每个 member 只包含 `uuid`、`name`。系统 MUST 限制角色数、每角色人数和字符串长度，MUST NOT 返回邮箱、电话、头像、部门、Token 或完整 Provider 响应。

#### Scenario: 输出角色与姓名
- **WHEN** 两个 Provider 请求均成功且响应符合契约
- **THEN** 模型只收到按角色组织的 UUID/名称摘要和不可信数据标记

#### Scenario: Provider 返回额外个人字段
- **WHEN** Team users 响应包含邮箱、电话、头像、部门或其它未声明字段
- **THEN** 响应解析器丢弃这些字段，Tool 输出和审计均不包含它们

<!-- Integrated from archived change: `2026-08-23-govern-reusable-ones-query-assets/specs/governed-api-capability` -->

### Requirement: 新 Tool 必须沿用当前用户身份与发布授权
`ones_list_project_role_members` MUST 使用 Principal JWT/JWKS 认证、当前用户活动 ONES Token/User ID 和默认 Team，并同时满足代码 Manifest、精确 invoke scope、Agent Publication、Application Publication、角色 Grant 和 Job 冻结 Tool/schema hash。旧 Publication、Grant 和 Job MUST NOT 因部署新代码自动获得新 Tool。

#### Scenario: 新发布显式授权
- **WHEN** 新 Agent/Application Publication、角色 Grant 和新 Job 均显式包含该 Tool
- **THEN** 当前用户可以查询其默认 Team 内有权访问的项目角色人员

#### Scenario: 旧 Job 调用新 Tool
- **WHEN** 调用来自未冻结该 Tool 的旧 Job
- **THEN** 系统在 ONES 请求前拒绝调用

#### Scenario: Provider 返回 401 或 403
- **WHEN** 当前用户 Token 失效或无权访问指定项目
- **THEN** 系统沿用现有一次受控 Token 刷新和失败关闭策略，且不切换用户、Team、管理员或服务账号

<!-- Integrated from archived change: `2026-08-23-govern-reusable-ones-query-assets/specs/governed-api-capability` -->

### Requirement: 现有工作项搜索契约必须保持不变
将工作项 GraphQL document 移入文件目录 MUST NOT 改变 `ones_work_item_search` 的 Tool identifier、input/output schema、固定 Path、variables、当前用户/默认 Team 绑定、授权、Token 刷新、审计或错误语义。

#### Scenario: 工作项迁移回归
- **WHEN** 对迁移前后的工作项 Operation 使用相同 Principal、输入和 Provider fixture
- **THEN** Provider 请求和规范化 Tool 输出保持契约等价

<!-- Integrated from archived change: `2026-08-23-govern-reusable-ones-query-assets/specs/ones-explicit-provider-interfaces` -->

### Requirement: 每个 ONES 接口必须由代码显式定义
系统 MUST 为每个获准 ONES 接口建立代码拥有的固定 Operation，并在 Operation 中明确 Method、相对 Path、固定 Header、动态 Header 来源、请求体构造和响应解析。系统 MUST 只实现用户提供完整接口契约的 Operation，MUST NOT 从其它接口猜测 URL、Method、Header、变量或响应结构。

#### Scenario: 完整接口契约被实现
- **WHEN** 用户已经提供固定 URL/Path、Method、Headers、请求报文、成功/空结果响应和主要错误状态
- **THEN** 系统按该报文建立单独 Operation 和脱敏契约测试

#### Scenario: 接口契约不完整
- **WHEN** 一个接口缺少会影响请求或解析的 URL、Method、Header、变量或响应字段
- **THEN** 系统不登记、不暴露也不调用该接口，并要求补齐契约而不是自行推断

<!-- Integrated from archived change: `2026-08-23-govern-reusable-ones-query-assets/specs/ones-explicit-provider-interfaces` -->

### Requirement: GraphQL document 必须独立存放并由 Operation 直接引用
系统 MUST 将 GraphQL document 保存于 `services/ones_mcp_server/provider/graphql/documents/`，由一个或多个代码拥有的 GraphQL Operation 直接引用。GraphQL 文件 MUST NOT 包含 Origin、Header、Token、User ID、Team ID 或其它凭据。Registry MUST 继续执行当前 code 唯一、固定相对 GraphQL Path 和只读 `query` 前缀检查，但本 change MUST NOT 增加 AST parser、document 指纹或反向依赖索引。

#### Scenario: Operation 加载 GraphQL 文件
- **WHEN** 已登记 Operation 引用存在且以只读 `query` 开头的 GraphQL 文件
- **THEN** 系统从该文件构造固定 GraphQL POST，并由 Operation 构造 variables 和解析响应

#### Scenario: 多个 Tool 使用同一 GraphQL 文件
- **WHEN** 两个业务 Tool 需要完全相同的 GraphQL document
- **THEN** 两个 Tool 可以直接引用同一文件，同时继续各自维护 Tool schema、授权和响应格式

<!-- Integrated from archived change: `2026-08-23-govern-reusable-ones-query-assets/specs/ones-explicit-provider-interfaces` -->

### Requirement: HTTP Client 只能执行 Operation 指定的固定 GET 或 POST
Provider HTTP Client MUST 复用当前固定 Provider origin、Host allowlist、超时、响应大小、禁止重定向、禁用环境代理、状态分类和 JSON 解析，并允许代码 Operation 选择 `GET` 或 `POST`。Path MUST 是代码构造的固定相对 Path；模型和管理端 MUST NOT 提交 Method、URL、Path、Header 模板或原始请求体。

#### Scenario: 固定 REST GET 被发送
- **WHEN** 已授权 Service 调用一个 Method 为 GET 的显式 Operation
- **THEN** Client 按该 Operation 的固定 Path、Headers 和请求体契约发送请求，其中项目角色成员 GET 固定发送空 JSON Body `{}`

#### Scenario: 固定 REST POST 被发送
- **WHEN** 已授权 Service 调用一个 Method 为 POST 的显式 Operation
- **THEN** Client 按该 Operation 构造的 JSON Body 和固定 Path/Headers 发送请求

#### Scenario: 调用方尝试改变请求目标
- **WHEN** Tool 输入包含 URL、Method、Path、Header、Token 或原始 Body 字段
- **THEN** Tool 输入校验在 Provider 请求前拒绝该调用

<!-- Integrated from archived change: `2026-08-23-govern-reusable-ones-query-assets/specs/ones-explicit-provider-interfaces` -->

### Requirement: 动态认证 Header 必须来自当前 Principal
所有 ONES Operation 的认证 Header 值 MUST 来自当前 Tool 调用解析出的活动个人 ONES 凭据和 User ID；Team UUID MUST 来自当前 Principal 的默认 Team。用户提供报文中的 Token/User ID 只能用于说明 Header 形状，MUST NOT 写入源码、配置样例、fixture、日志、审计或 Tool 输入。

#### Scenario: 当前用户身份被注入
- **WHEN** 已绑定用户调用一个显式 ONES Tool
- **THEN** Operation 使用该用户当前活动 Token/User ID 和默认 Team 构造请求，不使用示例值、管理员或服务账号

#### Scenario: 凭据不可用
- **WHEN** 当前用户没有活动凭据、默认 Team 或精确 Tool 授权
- **THEN** 系统在 Provider 请求前失败关闭

<!-- Integrated from archived change: `2026-08-23-govern-reusable-ones-query-assets/specs/ones-explicit-provider-interfaces` -->

### Requirement: Service 编排必须固定写在业务代码中
当一个 Tool 需要多个接口时，Service MUST 以代码固定调用 Operation 的集合、顺序和数据映射。系统 MUST NOT 提供流程 DSL、数据库动态编排、模型选择 Operation 或运行时替换接口。

#### Scenario: Tool 固定调用两个 REST Operation
- **WHEN** 项目角色人员 Tool 完成角色成员查询并需要查询成员姓名
- **THEN** Service 按代码固定顺序调用角色成员 GET 和用户 POST，模型不能跳过、增加、替换或重排调用

<!-- Integrated from archived change: `2026-08-23-govern-reusable-ones-query-assets/specs/ones-explicit-provider-interfaces` -->

### Requirement: Provider 响应必须按接口契约解析并有界输出
每个 Operation MUST 按用户提供的响应报文校验必需容器、字段、类型和关联键，并由业务 Service 只返回 Tool Output Schema 允许的有界字段。系统 MUST NOT 将完整 Provider 响应返回模型或写入日志/审计。

#### Scenario: 合法响应被映射
- **WHEN** Provider 返回符合该 Operation 契约的 JSON
- **THEN** Service 只输出 Tool 声明的业务字段并标记上游内容为不可信数据

#### Scenario: 响应缺少关联对象
- **WHEN** 第二个接口没有返回第一个接口所请求的全部关联 UUID
- **THEN** 整次 Tool 调用按 Provider 响应不完整失败，不静默省略、错配或返回半成品
