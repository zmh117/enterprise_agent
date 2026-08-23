## ADDED Requirements

### Requirement: ONES 身份绑定不得自动授予业务 MCP 能力
ONES 身份绑定 SHALL 只建立当前内部用户的外部主体、Team 与加密个人 Credential 事实，不得自动创建角色、Business Application Tool 授权、Job 或业务 MCP Principal。只有经 Agent/Application 发布交集和角色 Tool 授权的 ONES Tool 被当前 RUNNING Job 冻结后，平台才可为该 Job 签发 `ones-mcp` 短时 Principal；MCP 服务再按已验证主体解析对应个人 Credential。

#### Scenario: 完成ONES身份绑定
- **WHEN** 用户完成绑定或重新验证但没有经 Business Application 发布、角色授权并冻结到 Job 的 ONES Tool
- **THEN** 系统只更新身份与 Credential 事实
- **AND** 不授予、不签发也不触发任何 ONES 业务调用能力

#### Scenario: 已绑定用户执行授权ONES Job
- **WHEN** 用户身份有效且当前 RUNNING Job 冻结了经发布和授权的 `ones-mcp` Tool
- **THEN** 身份服务可按业务 MCP 规范为该 Job 签发短时 Principal
- **AND** 该签发不得反向改变用户绑定、内部角色或数据范围

## MODIFIED Requirements

### Requirement: Tool access is policy checked
系统 SHALL 在执行前校验 Tool allowlist、只读或受控写策略、Agent Publication Envelope、Business Application MCP Tool 子集、当前角色 Tool grant、Job 冻结的 Tool/schema、资源范围以及目标 MCP Server 的身份策略。业务 MCP Tool MUST 同时满足发布交集、当前角色授权、有效 Job Principal 和 Provider 身份/Credential 前置条件；任一维度不得成为其它维度的替代或扩大授权。

#### Scenario: Allowed read-only tool call
- **WHEN** Agent 请求的 Tool 位于 Job 冻结快照、两个 Publication 交集和当前角色 Tool grant 内，且资源范围与 MCP 身份校验均通过
- **THEN** 系统执行调用并记录各授权维度的决策

#### Scenario: Disallowed tool call
- **WHEN** Tool 已禁用、超出资源范围、不在任一发布集合、不在当前角色 grant、schema 漂移或身份前置条件失败
- **THEN** 系统在目标操作前拒绝并记录安全决策

#### Scenario: Application did not allow Tool
- **WHEN** Agent Publication Envelope 包含 Tool 但 Business Application 未选择它
- **THEN** 系统在 MCP 或 Provider 网络访问前拒绝

#### Scenario: Role did not grant Tool
- **WHEN** 两个 Publication 都包含 Tool 但当前用户的有效角色没有对应 Tool grant
- **THEN** 系统拒绝签发或调用且不得因身份已绑定而放行

### Requirement: ONES 身份与凭据状态分别治理
ONES 身份页面 SHALL 分别治理身份绑定状态与个人业务调用 Credential 状态。本人和管理员的安全投影 MUST 可以展示 `configured`、Credential status、revision、verified time、token refresh time、last used time 以及 reauth/disabled/unbound 时间；不得返回登录邮箱、密码、Token、密文、nonce、认证 Header 或可恢复认证材料。Credential 缺失或非 active 时，身份事实仍可查询，但 ONES Tool 调用 MUST 失败关闭并提示本人重新验证。

#### Scenario: 身份已启用且Credential可用
- **WHEN** 当前 ONES 身份已启用、具有已验证 Team 且 Credential 为 active
- **THEN** 本人摘要显示身份和安全 Credential 状态
- **AND** 不显示任何认证材料

#### Scenario: 身份存在但Credential不可用
- **WHEN** 当前身份存在但 Credential 缺失、需重新认证、已停用或已解绑
- **THEN** 页面保留身份事实并显示安全状态
- **AND** 新 ONES Tool 调用在 Provider 访问前失败关闭

### Requirement: ONES 默认摘要只展示业务字段
ONES 本人与治理摘要 SHALL 展示用户名称、身份状态、默认 Team、最近验证、适用操作和个人 Credential 的安全状态元数据；MUST NOT 展示 API Connection、登录邮箱、密码、Token、密文、nonce、完整认证错误正文或任意 Provider 原始响应。

#### Scenario: ONES身份已绑定
- **WHEN** 页面加载具有默认 Team 和 Credential 的当前身份
- **THEN** 默认卡展示身份、Team、Credential status、revision 和安全时间事实
- **AND** 不展示可用于认证或恢复 Credential 的材料

### Requirement: ONES 账户详情按本人和管理员划分
系统 SHALL 允许本人查看自己的 ONES User ID、全部已验证 Team 和个人 Credential 安全状态；管理员治理详情 SHALL 展示身份记录 ID、revision、状态、验证时间以及同样的安全 Credential 元数据，但 MUST NOT 显示登录邮箱、密码、Token、密文、认证 Header 或代用户填写凭据的入口。重新验证只能由本人会话发起。

#### Scenario: 本人展开ONES详情
- **WHEN** 当前用户查看自己的 ONES 身份
- **THEN** 系统返回 User ID、Team 候选和 Credential 安全状态
- **AND** 不返回任何认证材料

#### Scenario: 管理员展开ONES技术详情
- **WHEN** 具备身份治理权限的管理员查看他人 ONES 身份
- **THEN** 系统只返回允许的身份、Credential 安全元数据和审计事实
- **AND** 不提供代用户重新验证或读取 Credential 的能力

### Requirement: 一个内部自然人可以关联多个Provider身份
系统 SHALL 允许同一启用自然人关联不同 provider 与 tenant 范围的外部身份，并 MUST 禁止服务账号绑定个人外部身份。当前 ONES 自助绑定在代码固定实例内每个用户最多只有一个非 unbound 身份；换绑必须通过本人重新验证和显式确认完成。

#### Scenario: 用户同时关联钉钉和ONES
- **WHEN** 同一内部用户拥有已验证钉钉身份和已验证 ONES 身份
- **THEN** 两个外部身份都指向同一个内部用户 ID
- **AND** 各自保留独立 provider、tenant、subject、状态和用途

#### Scenario: 用户换绑ONES账号
- **WHEN** 用户验证的 ONES subject 与当前非 unbound ONES 身份不同
- **THEN** 系统要求显式换绑确认并原子软解绑旧身份与 Credential
- **AND** 每个用户继续只有一个当前 ONES 身份

#### Scenario: 服务账号尝试绑定
- **WHEN** 服务账号尝试进行 ONES 自助绑定
- **THEN** 系统拒绝操作并记录安全审计

### Requirement: 外部主体在受信范围内唯一绑定
系统 MUST 使用 `provider + tenant_code + external_subject_id` 唯一识别外部身份，DingTalk 身份可以另外保存受控 connector 引用；系统 MUST NOT 依据姓名、昵称、邮箱或手机号自动关联，也不得引入不存在的 Connection 或 Claim 作为授权事实。

#### Scenario: 唯一外部主体首次绑定
- **WHEN** 验证结果中的 subject 在该 provider 和 tenant 范围内尚未绑定
- **THEN** 系统原子创建指向目标内部用户的身份

#### Scenario: 相同主体绑定同一用户
- **WHEN** 同一用户再次验证已经属于自己的外部主体
- **THEN** 系统幂等刷新验证时间和受控 provider 上下文
- **AND** 不创建重复身份

#### Scenario: 相同主体属于另一个用户
- **WHEN** provider、tenant 和 subject 唯一键已经属于其它内部用户
- **THEN** 系统保留原身份并拒绝当前绑定
- **AND** 不依据显示字段自动覆盖、合并或转移身份

### Requirement: 身份可用状态和验证状态分别治理
系统 SHALL 在 `user_external_identity` 上保存 `enabled`、`disabled` 或 `unbound` 状态、revision 与 `verified_at`，并结合内部用户状态以及 provider 所需的当前上下文判断身份是否可用。ONES 个人 Credential SHALL 使用独立生命周期状态；系统不得声称当前存在通用 pending/conflict/revoked Claim 状态机或 Connection 状态机。

#### Scenario: enabled身份
- **WHEN** 内部用户启用、外部身份为 enabled 且 provider 所需前置条件有效
- **THEN** 系统可以把该身份用于对应受控主体解析

#### Scenario: 身份被禁用或解绑
- **WHEN** 外部身份状态为 disabled 或 unbound
- **THEN** 该身份停止解析新请求
- **AND** 其它身份、内部用户和历史记录不受影响

#### Scenario: ONES Credential不可用
- **WHEN** ONES 身份 enabled 但个人 Credential 非 active
- **THEN** 身份事实仍可查询但 ONES Tool 调用失败关闭

### Requirement: 冲突处理不得一键强制转移身份
系统 MUST 依赖 provider、tenant 与 subject 唯一约束阻止外部主体跨用户覆盖。当前 ONES 用户更换自己的账号时，系统 SHALL 要求新登录验证和显式 `replace_existing` 确认，并在一个事务中软解绑该用户旧身份与 Credential 后保存新绑定；系统不得提供管理员一键绕过唯一约束的强制转移命令。

#### Scenario: 外部主体已属于另一个用户
- **WHEN** 新绑定命中已属于其它内部用户的唯一外部主体
- **THEN** 系统拒绝绑定并保留原身份

#### Scenario: 本人换绑另一个ONES主体
- **WHEN** 用户完成新主体验证但未显式确认替换
- **THEN** 系统返回稳定的换绑确认要求且不改变当前身份

#### Scenario: 本人确认换绑
- **WHEN** 同一用户提交有效 Challenge 并显式确认替换当前 ONES 身份
- **THEN** 系统原子软解绑旧身份和 Credential 并保存新身份与 Credential

### Requirement: 身份管理API与Web使用真实数据和细粒度权限
系统 SHALL 提供真实用户外部身份的当前与历史查询，以及当前实现的 ONES 本人验证、确认、解绑和管理员安全查看能力；DingTalk 身份绑定与换绑继续使用其受限管理员权限。API 与页面 MUST 根据本人或身份治理权限限制范围，并 MUST NOT 暴露不存在的 Connection、Claim 或 Conflict 管理入口。

#### Scenario: 管理员查看用户详情
- **WHEN** 有用户与身份管理权限的管理员查看内部用户
- **THEN** 页面显示角色摘要、外部身份、provider/tenant、最近验证、Team、状态和允许的 Credential 安全元数据
- **AND** 不显示 Secret 或完整 provider 响应

#### Scenario: 用户查看自己的身份
- **WHEN** 普通用户进入“我的外部身份”
- **THEN** 页面只返回当前用户的真实外部身份及允许的本人操作
- **AND** 用户不能通过修改路径或请求体读取其它用户

#### Scenario: 本人操作revision冲突
- **WHEN** 身份或 Credential 写入基于过期 revision
- **THEN** API 返回稳定冲突并要求重新读取当前状态
- **AND** 不静默覆盖服务器事实

### Requirement: 导航展示与后端能力保持一致
系统 SHALL 根据当前用户能力展示用户、外部身份和其它真实管理入口，但 MUST NOT 把前端隐藏导航作为授权机制，也不得展示当前没有 API 与页面的通用 Connection、Claim 或冲突治理入口。

#### Scenario: 身份管理员登录
- **WHEN** 用户具有 identity 管理权限但没有其它平台管理权限
- **THEN** 前端显示允许的用户与外部身份入口并隐藏无权限命令
- **AND** 后端仍对每个请求执行对象级 RBAC

#### Scenario: 普通用户登录
- **WHEN** 用户只有自己的安全设置和外部身份自助验证权限
- **THEN** 前端只显示个人安全与“我的外部身份”
- **AND** 不显示其它用户或不存在的 Connection、Claim 与冲突治理页面

### Requirement: Tool calls are recorded with safe summaries
系统 SHALL 持久化 Tool Call 的脱敏请求摘要、有界规范化响应摘要、状态、耗时、风险级别、审计关联以及实际 MCP Server、Tool identifier、schema hash、资源或 Provider attempt 事实。系统 MUST NOT 持久化认证材料、原始 HTTP 请求/响应正文或无界外部内容，也不得记录已删除的 Capability Release 或 Handler 作为当前执行来源。

#### Scenario: Database tool succeeds
- **WHEN** `query_database` 通过 `tool-mcp` 返回证据
- **THEN** 系统记录 Tool identifier/schema hash、脱敏请求摘要、有界响应摘要、耗时、状态、风险级别、审计事件和实际 Resource Revision 元数据

#### Scenario: Tool call returns sensitive or large data
- **WHEN** Tool 响应包含敏感字段或超过内联存储上限
- **THEN** 系统在 PostgreSQL 中只保存掩码或摘要结果
- **AND** 不在 Tool Call 行保存原始敏感载荷

#### Scenario: Tool MCP rejects a call
- **WHEN** `tool-mcp` 因 Job 来源、授权、资源解析、数据源策略、查询策略或参数错误拒绝调用
- **THEN** 系统记录安全拒绝原因、耗时、风险级别和审计事件且不暴露资源 Secret

#### Scenario: Business MCP call succeeds after retry
- **WHEN** 代码固定业务 MCP Tool 在一次或多次 Provider attempt 后成功
- **THEN** 系统记录一条关联 Tool Call 和独立安全 attempt 事实
- **AND** 事实包含 Server/Tool/schema、分类、耗时、大小与状态但不含原始正文、Token、Cookie 或认证 Header

### Requirement: 重建保留跨域运行历史
钉钉测试数据重建 MUST 保留平台人员、角色、登录会话、ONES 身份与个人 Credential、Agent、业务应用与 MCP Tool 发布配置，以及全部 Agent Job、Tool Call 结果和 Delivery 记录；历史 Publication 中的旧 connector 引用 SHALL 只标记为不可运行历史来源，不得被静默改写到新 connector。

#### Scenario: 清理存在历史Job的旧连接
- **WHEN** 待清理钉钉 connector 已经产生 Agent Job、Tool Call 和 Delivery 记录
- **THEN** 系统保留这些运行记录，使其旧 connector 来源可审计但不可继续路由

#### Scenario: 清理后重新接入
- **WHEN** 重建成功后管理员创建企业和新应用 connector
- **THEN** 既有业务应用主体仍存在，但必须显式选择新 connector 并重新发布
- **AND** 不得自动把历史 Publication 改指新 connector

### Requirement: 身份关联不授予额外业务权限
系统 MUST 把外部身份映射仅作为可信主体解析，MUST NOT 因为成功关联钉钉、ONES 或其它 provider 而自动创建角色、平台数据范围、Business Application 访问或 MCP Tool grant。

#### Scenario: ONES身份验证成功
- **WHEN** 用户成功关联 ONES 账号
- **THEN** 用户的内部角色、应用访问和 MCP Tool grant 保持原样
- **AND** ONES 原生项目权限仍由 ONES Provider 判断

#### Scenario: 群聊成员身份不同
- **WHEN** 同一钉钉群中的两名发送人关联不同内部用户和 ONES 身份
- **THEN** 系统按每条消息的发送人解析主体
- **AND** 不创建群级共享 ONES 身份或权限

### Requirement: 外部身份管理不得暴露凭据和敏感载荷
系统 MUST 在 API、页面、Prompt、RabbitMQ、日志、审计和错误中排除密码、Session Token、CSRF 值、Provider Token、AppSecret、完整 Webhook URL、Principal JWT、Authorization/Cookie、私钥、密文和 nonce。数据库 MAY 只在专用 Credential 与短期 Challenge 表中保存使用平台主密钥用途绑定加密的 Provider 登录材料与 Token，不得把明文或密文复制到 Identity metadata、公开投影或审计。受 `audit:*:read` 和保留期保护的审计 MAY 原样保存邮箱/User ID 及有界 Provider 业务请求/响应，但不得保存 Provider 认证请求/响应原文。

#### Scenario: 查看身份与验证状态
- **WHEN** 用户或管理员查看 Identity、Challenge 公开结果或 Credential 安全状态
- **THEN** 系统只返回 provider、tenant、subject、受控上下文、配置状态、revision 和安全时间
- **AND** 不返回明文、密文、nonce、key ID、Authorization Header 或任何可重放认证材料

#### Scenario: 检查数据库明文
- **WHEN** ONES 本人绑定、查询和 Token 自动刷新完成
- **THEN** 密码与 Token 只存在于 AES-GCM 密文列且不出现在其它业务表或 JSON metadata
- **AND** 登录邮箱只可作为受控身份事实进入授权审计字段

### Requirement: ONES验证只通过受信Connection发起
ONES 身份验证 SHALL 只通过服务端固定的身份 Provider 配置发起。系统 MUST 使用固定 Base URL、代码内固定登录 Path 和主机 allowlist，不接受浏览器或请求体提供 URL、Method、Path、Header、代理、旧 API Connection Revision 或 MCP Server。

#### Scenario: 身份提供方未配置
- **WHEN** 固定 ONES 身份 Provider 配置不可用
- **THEN** 系统拒绝验证且不尝试旧 API Connection 或任意 MCP 地址

#### Scenario: 请求尝试覆盖Provider
- **WHEN** 浏览器请求包含 URL、Path、Method、Header 或代理配置
- **THEN** 严格请求 schema 拒绝未知字段且不发起外部请求

### Requirement: ONES网络访问执行出站安全策略
系统 MUST 校验固定 ONES 身份 Provider Base URL 的 scheme、Host 和 allowlist，禁止重定向和环境代理继承，并 SHALL 应用连接超时、读取超时与响应上限。

#### Scenario: 生产HTTPS配置
- **WHEN** 生产环境使用 allowlist 中的 HTTPS Host
- **THEN** 系统允许代码固定登录请求并执行证书校验

#### Scenario: 生产HTTP配置
- **WHEN** 生产环境配置 HTTP 或 Host 不在 allowlist
- **THEN** 系统拒绝初始化该 Provider 且不发起调用

#### Scenario: 本地Mock配置
- **WHEN** 开发环境显式允许 insecure local 且 Host 命中本地开发 allowlist
- **THEN** 系统可以调用独立 ONES Mock
- **AND** 该例外不能在生产配置中默认启用

#### Scenario: 上游重定向
- **WHEN** ONES 登录端点返回重定向
- **THEN** Provider adapter 拒绝跟随并返回安全连接错误

### Requirement: 成功验证原子绑定ONES身份
系统 MUST 先验证 ONES 登录并创建包含用途绑定加密认证材料的短时单次 Challenge；确认默认 Team 时 MUST 原子校验当前用户、唯一 subject、候选 Team 和现有 Identity，然后创建或刷新 Identity、创建或轮换 active 个人 Credential 并消费 Challenge。

#### Scenario: 新ONES主体验证成功
- **WHEN** 当前用户确认合法 Challenge 和候选 Team
- **THEN** 系统创建 enabled Identity、保存最新 Team、默认 Team 和验证时间，并创建 active 加密 Credential

#### Scenario: 换绑需要显式确认
- **WHEN** Challenge subject 与当前 ONES 身份不同且请求未设置 `replace_existing`
- **THEN** 系统拒绝确认并保留当前 Identity 与 Credential

#### Scenario: Credential保存失败
- **WHEN** Identity 可写但 Credential 加密或持久化失败
- **THEN** 绑定事务回滚且不产生部分身份或部分 Credential

### Requirement: 未绑定钉钉消息形成安全发现候选
系统 SHALL 只为通过渠道认证和规范化、已持久化且明确因钉钉身份从未绑定、身份已停用或解绑、或所属用户已停用而被拒绝的新消息创建发现候选，并 MUST NOT 因此创建 Agent Job、发布 Job 消息、调用模型或调用任意 MCP Tool。

#### Scenario: 从未绑定用户发送私聊消息
- **WHEN** 一个没有历史钉钉身份的用户向已启用机器人发送私聊消息
- **THEN** 系统返回现有未授权提示、创建或更新该用户的发现候选且不得创建 Agent Job

#### Scenario: 从未绑定用户发送群聊消息
- **WHEN** 一个没有历史钉钉身份的用户在群聊中向已启用机器人发送消息
- **THEN** 系统创建或更新同一身份候选并记录安全群会话标识且不得触发 Agent 执行

#### Scenario: 不符合身份发现条件的入口失败
- **WHEN** 钉钉事件因 connector 认证失败、格式错误、缺少 `senderStaffId` 或非身份授权原因被拒绝
- **THEN** 系统 MUST NOT 创建身份发现候选且不得泄露事件是否对应现有人员

## REMOVED Requirements

### Requirement: 重置只能通过受控运维入口执行
**Reason**: 当前代码没有身份与授权全量重置 CLI、服务或 API，该正向能力未实现。

**Migration**: 不执行重置；需要该能力时必须另建 change，并在实现与破坏性验收完成后进入 canonical。

### Requirement: 重置范围必须明确且完整
**Reason**: 当前不存在对应影响清单和批量删除实现。

**Migration**: 保留现有身份、授权与历史事实，不执行删除。

### Requirement: 引用旧主体的依赖必须先安全改写
**Reason**: 当前不存在该重置依赖改写流程或替代服务账号生成器。

**Migration**: 现有引用继续由当前领域生命周期治理。

### Requirement: 执行前必须创建并验证可恢复备份
**Reason**: 当前不存在与身份重置绑定的备份准备阶段和操作台账。

**Migration**: 不声称具备该工作流；常规数据库备份规则不受影响。

### Requirement: 重置采用两阶段确认和全局维护锁
**Reason**: 当前不存在重置 operation、两阶段确认或全局维护锁模型。

**Migration**: 不执行兼容模拟；未来实现必须另建 change。

### Requirement: 身份与授权重置必须原子提交
**Reason**: 当前不存在对应事务服务。

**Migration**: 不执行部分或完整重置。

### Requirement: 初始化唯一的平台管理员
**Reason**: 当前 bootstrap 能力不属于所描述的全量重置事务，且没有该唯一管理员不变量实现。

**Migration**: 继续使用现有管理员 bootstrap 合同，不将其描述为全量重置结果。

### Requirement: 初始凭据必须一次性安全交付
**Reason**: 当前不存在该重置专用凭据文件交付流程。

**Migration**: 不生成或写出任何重置凭据文件。

### Requirement: 首次登录必须修改初始密码
**Reason**: 当前 schema 与登录服务没有 `must_change_password` 或等价重置状态。

**Migration**: 继续使用当前密码与 Session 合同；未来首次改密能力必须单独实现。

### Requirement: 重置完成后只允许严格角色授权
**Reason**: 当前不存在重置后切换 `strict_application_role` 模式的实现。

**Migration**: 当前授权仍按现行角色、应用和 Tool grant 合同执行。

### Requirement: 重置必须具有可验证台账和安全审计
**Reason**: 当前数据库没有重置 operation ledger 或对应审计服务。

**Migration**: 不伪造台账；现有身份与授权变更继续写入通用审计。

### Requirement: 成功后的恢复必须遵循显式手册
**Reason**: 当前不存在可成功执行的身份重置，因此也不存在与其绑定的恢复命令。

**Migration**: 常规备份恢复文档不受影响；未来重置实现必须同时提供恢复验收。

### Requirement: 所有运维与用户可见提示使用中文
**Reason**: 该条款仅约束未实现的身份重置工作流，脱离该工作流没有独立当前调用方。

**Migration**: 现有各领域的安全中文提示要求继续保留。

### Requirement: 外部身份Connection定义受信Provider实例
**Reason**: 当前 schema、repository、API 和页面没有通用 External Identity Connection 聚合；provider/tenant 直接保存在外部身份上，DingTalk 使用 Connector。

**Migration**: 使用 `provider + tenant_code + external_subject_id` 身份模型和现有 DingTalk Connector；不创建兼容 Connection。

### Requirement: Claim承载待验证和冲突流程
**Reason**: 当前 schema、repository、API 和页面没有通用 Identity Claim 实体或状态机。

**Migration**: ONES 使用短期 Verification Challenge，唯一性冲突由数据库约束和显式换绑确认处理。

### Requirement: 现有钉钉绑定平滑迁移到通用模型
**Reason**: 当前没有通用 Connection/Claim 模型，也没有该迁移流程；现有钉钉身份已经直接使用 provider、tenant、subject 和 connector 事实。

**Migration**: 保持当前钉钉身份记录与解析语义，不执行虚构的 Connection 迁移。

### Requirement: 本阶段不接入 ONES 业务能力
**Reason**: 当前已经实现并发布两个 `ones-mcp` 业务 Tool，并为授权 Job 签发业务 Principal；旧标题和“无长期业务调用 Token”描述与代码事实冲突。

**Migration**: 由“ONES 身份绑定不得自动授予业务 MCP 能力”替代，保留绑定与 Tool 授权分离边界。

### Requirement: ONES验证具备限流和安全失败分类
**Reason**: 当前 ONES 本人验证路径具有安全错误分类，但没有按用户、来源地址或 Provider 的验证限流器；该 Requirement 把未实现的限流写成现行合同。

**Migration**: 保留现有 Provider 超时和安全错误映射；未来需要 ONES 验证限流时必须单独实现并测试。

## RENAMED Requirements

- FROM: `身份可用状态和验证状态分别治理`
- TO: `外部身份状态与ONES凭据状态分别治理`
- FROM: `ONES验证只通过受信Connection发起`
- TO: `ONES验证只通过服务端固定身份Provider发起`
