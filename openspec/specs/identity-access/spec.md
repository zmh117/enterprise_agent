# identity-access Specification

## Purpose
定义内部用户、管理端认证、角色授权、钉钉企业身份、ONES 个人凭据及平台 Principal 的当前领域契约。内部用户是权限主体；外部身份、个人凭据、管理能力、业务应用访问、Tool 使用和数据范围分别建立与复核，不互相授予。

本文件负责身份和授权事实。业务应用发布见 `business-application`，渠道接收与会话见 `channel-conversation`，具体外部 Tool 合同见 `governed-api-capability`，操作确认状态机见 `execution-delivery`，文件操作授权见 `task-file-workspace`。

## Requirements

### Requirement: 内部用户是跨入口唯一权限主体
系统 SHALL 使用持久化内部用户 ID 作为管理 Web、钉钉、Webhook Job、Tool 和审计的权限主体。外部 provider、企业或 tenant、subject 只能在受信解析后关联内部用户，MUST NOT 以群 ID、昵称、邮箱、手机号、发布管理员或客户端 actor 字段代替内部用户。

#### Scenario: 同一用户从不同入口访问
- **WHEN** 已启用自然人从有效 Web Session 或已绑定钉钉身份进入
- **THEN** 系统解析同一内部用户，并按本次入口、角色和应用独立授权

#### Scenario: 服务账号触发 Webhook
- **WHEN** 已发布 Trigger 接收合法事件
- **THEN** Job 和下游审计使用 Trigger 固定的服务账号，保留 Trigger、Publication 和 correlation 关联

### Requirement: 用户目录使用真实数据和并发控制
用户管理 SHALL 提供真实分页列表、查询、详情、创建、编辑和启停，支持用户名、显示名称及外部身份展示名查询。用户名 MUST 唯一，写入 MUST 使用当前 revision、统一管理权限、CSRF 和审计；密码只保存安全哈希，响应不得包含密码、哈希或认证令牌。

#### Scenario: 并发编辑同一用户
- **WHEN** 管理员提交过期 `expected_revision`
- **THEN** 系统返回可识别的版本冲突，不覆盖新资料

#### Scenario: 停用再启用用户
- **WHEN** 管理员停用用户后重新启用
- **THEN** 停用使现有 Web Session 失效并阻止新请求；重新启用允许重新认证，但不自动恢复已停用外部身份或角色成员关系

#### Scenario: 请求不存在用户
- **WHEN** 授权管理员请求不存在的用户
- **THEN** 系统返回未找到，不创建占位或演示用户

### Requirement: 服务账号与人类账号分离
系统 SHALL 区分 `human` 与 `service`。服务账号可持有明确的业务角色，MUST NOT 创建个人密码凭据、交互式 Web Session、个人钉钉或 ONES 身份，亦不得加入包含管理后台能力的角色。新建 Trigger 的专用服务账号不得自动获得业务权限。

#### Scenario: 服务账号登录管理端
- **WHEN** 使用服务账号提交用户名密码
- **THEN** 认证失败且不创建 Session

#### Scenario: 给服务账号分配管理角色
- **WHEN** 目标角色包含管理能力
- **THEN** 系统拒绝成员写入，业务角色分配仍按目标角色委派权限处理

### Requirement: 管理面原子启用认证和授权
管理 Web、管理 API、统一用户、Web Session 和 RBAC SHALL 作为同一管理面能力启用。`FEATURE_WEB_ADMIN` 关闭时不暴露管理面；开启时不得降级为无身份或无 RBAC。受保护接口 MUST 先确定主体再授权，已有 Channel 和 Runtime 的运行不因管理面关闭而自动停止。

#### Scenario: 未认证读取管理资源
- **WHEN** 请求未携带有效 Session
- **THEN** 后端返回 401，前端不短暂展示管理数据并跳转登录页

#### Scenario: 已认证但权限不足
- **WHEN** 有效用户缺少目标管理能力
- **THEN** 后端返回 403；修改请求仍须通过 CSRF、revision 与业务校验

#### Scenario: 生产请求伪造 actor Header
- **WHEN** 请求只提供 `X-Admin-User-Id` 或 `X-Agent-User-Id`
- **THEN** 系统不将其视为认证主体；测试 Header 仅可由 local/test/testing 的显式测试适配器启用

### Requirement: 管理登录使用可撤销服务端 Session
系统 SHALL 对已启用自然人校验本地安全密码哈希，以高熵随机令牌建立服务端 Session，并只持久化 Session/CSRF 哈希、闲置与绝对过期时间。浏览器 MUST 通过受控 Cookie 和 `/api/auth/me` 恢复状态，不得把 Session Token 写入 Local Storage、Session Storage、URL 或前端持久状态。

#### Scenario: 登录失败
- **WHEN** 用户名未知、密码错误、账号停用或账号为服务账号
- **THEN** 返回统一中文登录失败信息，不暴露账号存在性或具体认证字段

#### Scenario: Session 过期或被撤销
- **WHEN** 请求使用超过闲置或绝对时限、已撤销或用户已停用的 Session
- **THEN** 系统拒绝认证，前端清理认证与管理数据缓存，要求重新登录

#### Scenario: 安全返回原页面
- **WHEN** 登录页包含返回路径
- **THEN** 只接受安全站内路径，忽略绝对或协议相对站外 URL

### Requirement: Cookie 写请求执行 CSRF 和来源校验
Cookie Session 的状态变更请求 MUST 同时使用匹配的 CSRF Cookie、`X-CSRF-Token` 和服务端 CSRF 哈希，并校验允许 Origin；生产请求缺少 Origin 不得通过。Session Cookie SHALL 使用 HttpOnly、适当 SameSite 和生产 Secure 属性，前端 API client 使用同源 Cookie 请求。

#### Scenario: CSRF 或 Origin 无效
- **WHEN** 写请求缺少有效 CSRF、Cookie 与 Header 不一致或 Origin 不允许
- **THEN** 返回 403 且不修改业务数据

#### Scenario: 认证状态尚未确定
- **WHEN** 管理页面等待当前用户接口
- **THEN** 受保护内容不发起依赖用户权限的数据读取

### Requirement: 本人可以退出修改密码和撤销自己的 Session
系统 SHALL 允许本人安全退出、校验当前密码后修改密码、查看与撤销自己的 Session。改密 MUST 撤销该用户全部现有 Session；本人会话管理不得操作其他用户 Session，写操作执行 CSRF 与安全审计。

#### Scenario: 修改密码成功
- **WHEN** 本人提供正确当前密码和合规新密码
- **THEN** 系统原子更新密码哈希、撤销全部现有 Session 并要求重新登录

#### Scenario: 撤销他人 Session
- **WHEN** 本人入口收到属于另一用户的 Session ID
- **THEN** 系统拒绝操作且不泄露其会话材料

### Requirement: 管理能力来自代码注册目录
管理能力 SHALL 由后端唯一目录以稳定编码、中文名称、模块、动作、风险、依赖和支持的资源范围定义。前端导航和动作与后端 API MUST 映射同一能力；系统不得接受任意能力编码或以组件、按钮、路由文本作为授权事实。

#### Scenario: 勾选高级管理动作
- **WHEN** 为角色选择编辑、发布、激活或分配能力
- **THEN** 系统补足对应查看依赖但不自动授予其他高级动作；取消查看时须同时移除依赖动作

#### Scenario: 新版本增加能力
- **WHEN** 代码目录注册新管理能力
- **THEN** `platform-admin` 自动具有该管理能力，其他角色不自动获得

#### Scenario: 仅有指定资源编辑权
- **WHEN** 用户角色只允许编辑一个 Agent 或业务应用
- **THEN** 修改其他资源被后端拒绝，即使绕过前端隐藏入口也不例外

### Requirement: 统一 RBAC 是唯一授权事实源
系统 MUST 以现行 `rbac_*` 角色、成员、管理能力、应用访问、MCP Tool grant、数据范围及受管显式拒绝计算权限，不得读取旧 `permission_policy`、`platform_access_grant` 或从历史数据自动回填权限。用户、角色和成员关系必须启用，成员关系过期后不再参与新决策。

#### Scenario: 旧策略允许但现行角色未授权
- **WHEN** 用户没有当前有效应用或 Tool grant
- **THEN** 系统拒绝业务访问，不执行兼容 fallback

#### Scenario: 多个业务角色重叠
- **WHEN** 有效角色提供多个允许范围且某目标命中显式拒绝
- **THEN** 允许范围取并集，命中的显式拒绝优先，并保留安全来源解释

### Requirement: 角色分别配置管理和业务授权
自定义角色 SHALL 统一承载管理能力、业务应用访问、稳定 MCP Tool Identifier 与逻辑数据范围，并分区展示基本信息、成员、管理授权和业务授权。每个授权区 MUST 独立并发控制、预览后原子保存；角色编码创建后不可更改，自定义角色只启停并保留历史，受保护系统角色不得删除或停用。

#### Scenario: 两人修改不同授权区
- **WHEN** 两名管理员分别提交管理授权和业务授权
- **THEN** 各自按对应 revision 保存，不覆盖无权编辑的其他区域

#### Scenario: 授权字段使用退役对象
- **WHEN** 请求提交 API Capability、Handler、API Connection、Resource Mapping 或 Resource Revision grant
- **THEN** 系统拒绝旧模型字段，不创建兼容权限

#### Scenario: 角色保存后运行
- **WHEN** 管理员撤销成员或更改业务 grant
- **THEN** 后续授权使用新事实，无需重新发布 Agent 或业务应用；在途业务调用仍按执行前复核契约处理

### Requirement: 授权委派不得导致自我提权
系统 SHALL 分开运行使用权限、授权编辑范围和目标角色成员分配权。非平台管理员只能配置明确委派的能力、应用与资源，复制或创建角色也不能超出该范围。高风险管理能力、生产范围扩大和显式拒绝修改 MUST 要求现有二次确认与变更原因；自定义角色不得跨模块一键全选高风险能力。

#### Scenario: 人员管理员分配未委派角色
- **WHEN** 操作者仅有人员管理权而没有目标角色的成员分配权
- **THEN** 系统拒绝分配，不因其可编辑用户而授予角色管理权

#### Scenario: 候选绑定同时指定初始角色
- **WHEN** 管理员绑定钉钉候选并选择获准分配的初始角色
- **THEN** 身份与成员关系在同一事务保存；任一角色越权或失败时整体回滚

#### Scenario: 预览有效权限
- **WHEN** 有权管理员模拟某用户对应用和目标的权限
- **THEN** 系统返回无副作用的安全授权结果和来源，不执行业务 Tool 或暴露凭据

### Requirement: 平台管理员不自动获得业务数据权限
`platform-admin` SHALL 自动获得当前与未来全部代码注册管理能力，但 MUST NOT 因系统角色跳过业务应用、Tool、数据范围或 Provider 权限。减少已验证人类平台管理员的操作 MUST 在事务锁内校验，拒绝使其少于两人。

#### Scenario: 仅有平台管理员角色的用户运行业务应用
- **WHEN** 用户没有应用业务 grant
- **THEN** 系统拒绝业务访问，仍允许其进入授权管理

#### Scenario: 从两名已验证管理员中移除一人
- **WHEN** 停用、删除用户或修改成员关系会减少有效人数至一人
- **THEN** 操作整体拒绝并审计 `platform_admin_invariant`；计数只含启用的人类用户、有效角色成员、密码凭据和既有登录 Session 记录

#### Scenario: 首次 bootstrap
- **WHEN** 系统没有启用人类平台管理员且显式 bootstrap 配置有效
- **THEN** 系统以串行事务创建首名管理员，不把“至少两人”解释为无法初始化；已有管理员时不重设其密码

#### Scenario: 合法撤销本人平台管理员成员关系
- **WHEN** 二次确认后有效人数仍满足要求
- **THEN** 系统保存撤销并使本人现有会话失效，不能继续使用旧管理权限

### Requirement: 应用 Tool 和数据范围共同授权
业务访问 MUST 同时满足当前用户状态、应用访问、稳定 MCP Tool grant、Agent/Application Publication 的工具交集及冻结 Job Snapshot；需要平台数据目标的 Tool 还须通过实际 Environment、可选 Base、可选 Workshop 的范围检查。`cloud`、`edge`、role label 和 replica 是资源部署信息，MUST NOT 成为用户或角色授权维度。

#### Scenario: Tool 已授权但数据目标不允许
- **WHEN** 用户可以调用数据库 Tool，但请求目标不在应用角色范围内
- **THEN** 系统在访问资源前拒绝，资源 placement 不扩大范围

#### Scenario: 应用分配 Tool 但用户无权
- **WHEN** Publication 包含 Tool 而当前用户没有其 grant
- **THEN** Tool 不进入可调用授权集合

#### Scenario: 保存当前全部范围
- **WHEN** 管理员选择“当前全部环境、基地或车间”
- **THEN** 系统展开为当时存在且有权授予的明确 ID；未来新增资源不自动加入

### Requirement: 钉钉企业以受信 Corp ID 建立命名空间
钉钉企业 SHALL 使用独立内部 ID 和 `PENDING_VERIFICATION`、`ACTIVE`、`DISABLED`、`ARCHIVED` 状态。初始 Corp ID 为空，仅可由同一条受信 Stream 消息中非空相等的 `senderCorpId` 与 `chatbotCorpId` 固化；验证后 Corp ID 不可编辑。企业名称可在 revision 与审计保护下修改，多个应用 Connector 可以引用同一企业。

#### Scenario: 首条测试消息完成企业验证
- **WHEN** 待验证企业收到满足条件且 Corp ID 无冲突的受信消息
- **THEN** 原子固化企业与验证审计，该消息只用于验证，不产生业务 Job、候选或正式身份观察

#### Scenario: 企业字段缺失冲突或跨企业
- **WHEN** 消息 Corp ID 缺失、两字段不一致或不匹配既有企业
- **THEN** 系统失败关闭，不自动改绑 Connector、不改写 Corp ID，并产生安全治理错误

#### Scenario: 停用和恢复企业
- **WHEN** 企业被停用、归档或申请恢复
- **THEN** 非活动企业不处理业务；恢复须重连并复验原 Corp ID；仍有启用应用时不能归档

### Requirement: 钉钉身份按企业唯一且保留原人员历史归属
系统 MUST 以钉钉企业和 `senderStaffId` 唯一识别外部身份，每个内部用户在每个企业至多一个 `enabled` 或 `disabled` 当前身份。新绑定只能来自有效受信候选；同企业换绑需要显式确认并原子软解绑旧身份。钉钉 `unbound` 历史仍归原人员，不能被其他人员重新占用。

#### Scenario: 同一身份来自两个应用
- **WHEN** 同一企业相同 Staff ID 通过不同 Connector 发消息
- **THEN** 解析同一外部身份，不复制身份或授权

#### Scenario: 历史钉钉身份重新出现
- **WHEN** 软解绑身份形成新候选
- **THEN** 仅允许原人员恢复，不允许转移到其他用户

#### Scenario: 客户端手工指定身份
- **WHEN** 绑定请求试图提交 Staff ID、Corp ID、昵称或 Connector 以替代候选事实
- **THEN** 后端拒绝或排除该输入，并重新核对候选、企业、来源 Connector、目标人类用户和 revision

### Requirement: 身份观察和昵称更新先于业务执行
已绑定钉钉消息 SHALL 在 Job 创建前原子完成企业与用户检查、身份最近使用、按“身份 + 应用”幂等观察及昵称更新。昵称只取受信非空 `senderNick`，按有效事件时间和稳定事件 ID 单调更新；无效外部时钟回退服务端接收时间。观察不表示应用授权，身份启停与解绑作用于企业全部应用。

#### Scenario: 旧消息晚到或事件重试
- **WHEN** 已保存更新昵称后收到旧游标或重复事件
- **THEN** 不回滚昵称、不重复观察或昵称变化审计

#### Scenario: 正式观察写入失败
- **WHEN** 必要身份事实无法持久化
- **THEN** 不创建或分发 Job，不把持久化失败当作可跳过步骤

#### Scenario: 用户没有 ONES Credential
- **WHEN** 钉钉身份和应用访问有效但 ONES 未绑定或凭据不可用
- **THEN** 不因此拒绝钉钉应用访问；仅在需要 ONES Tool 时按 ONES 身份边界失败关闭

### Requirement: 未绑定钉钉用户发现有界且不触发 Agent
只有已认证、已持久化且因身份从未绑定、停用、解绑或所属用户停用而拒绝的新钉钉事件 SHALL 形成候选。候选按企业和 Staff ID 聚合、按来源事件幂等，最多保留最近 20 条消息投影和每条 1,000 字符安全纯文本摘要；附件仅保留安全类型、名称、大小，不下载或解析内容。

#### Scenario: 未绑定用户发送业务问题
- **WHEN** 合法事件进入身份拒绝分支
- **THEN** 保存安全候选并返回身份提示，不创建 Agent Session、用户消息、Job 或调用模型、MCP Tool

#### Scenario: 不属于身份拒绝
- **WHEN** 事件因认证、Corp ID、格式或缺少 Staff ID 失败
- **THEN** 不生成身份发现候选

#### Scenario: 发现投影保存失败
- **WHEN** 身份拒绝事实无法安全持久化
- **THEN** 保持拒绝执行并返回安全的可重试接收错误，不创建 Job

### Requirement: 候选治理只恢复身份不回放历史消息
发现列表 SHALL 使用真实授权数据、稳定分页和服务端接收时间排序，仅展示最近 30 天活动且当前仍不可用的候选。管理员通过候选 ID 进入人员管理绑定或恢复，MUST 使用 `identity:manage`、CSRF、revision 和审计；绑定或恢复后立即从列表和计数隐藏，不回放任何旧消息。

#### Scenario: 候选超过保留期
- **WHEN** 最近服务端接收时间超过 30 天
- **THEN** 查询排除该候选，清理仅删除发现投影，不清理原事件或运行历史

#### Scenario: 新建人员后绑定失败
- **WHEN** 人员已创建而绑定因冲突失败
- **THEN** 保留人员和候选上下文，返回中文错误，不秘密删除人员

#### Scenario: 管理端查看候选
- **WHEN** 有权管理员查看或筛选候选
- **THEN** 仅按纯文本展示白名单摘要；前台页面和徽标分别有界轮询，后台暂停，不提供回复、忽略、人工删除或批量处置

### Requirement: ONES 本人验证使用固定 Provider 与短期 Challenge
ONES 绑定 SHALL 仅由已认证启用自然人本人发起，调用服务端固定 `/project/api/project/auth/login` 验证邮箱密码，严格校验用户 UUID、Token 与 Team 响应，再创建用户绑定、短 TTL、单次消费的加密 Challenge。客户端不得指定 ONES UUID、Token、Team 集合、目标 URL、Header 或 Provider 配置，管理员不得代验证。

#### Scenario: 本人登录验证成功
- **WHEN** 固定 Provider 返回合法身份与非空 Team 候选
- **THEN** 返回 Challenge ID、到期时间、身份安全摘要与 Team 候选，不返回登录材料或 Token

#### Scenario: Challenge 过期重复或属于他人
- **WHEN** 确认请求使用不可用 Challenge
- **THEN** 拒绝身份和 Credential 写入，并清理可清理的 Challenge 密文

#### Scenario: Provider 网络配置不合规
- **WHEN** 基址不在显式 host allowlist、包含 URL 凭据或 query/fragment、试图重定向，或使用 HTTP 但未显式允许
- **THEN** 验证失败关闭；固定客户端禁用代理继承、限制超时和响应大小

#### Scenario: 受信网络中的生产 ONES 仅提供 HTTP
- **WHEN** 生产配置固定 ONES HTTP 基址、精确 host allowlist 且显式允许 HTTP
- **THEN** 本人验证和 ONES MCP 的受控凭据刷新可访问该基址，不因生产环境强制 HTTPS 而拒绝；部署方承担 HTTP 明文传输风险

### Requirement: ONES 身份和个人 Credential 原子绑定且分别治理
系统 SHALL 分表保存 ONES 身份及用途绑定认证加密的个人 Credential。确认 Challenge 时 MUST 原子保存唯一当前账号、最新完整 Team 候选、单一默认 Team 与 active Credential，清除被消费 Challenge；切换默认 Team 必须重新验证，不能选择已撤销历史 Team。Credential 保留独立状态、revision 和安全时间元数据。

#### Scenario: 确认有效 Team
- **WHEN** 本人从当前 Challenge 候选选择默认 Team
- **THEN** 原子保存身份、Team 与 Credential，最新候选整体替换旧集合，名称仅来自 Provider 验证结果

#### Scenario: 持久化 Credential 失败
- **WHEN** 身份可写但加密或 Credential 保存失败
- **THEN** 不留下部分绑定或部分换绑；失效 Challenge 不得长期保留可用认证材料

#### Scenario: 历史身份没有 Credential
- **WHEN** 身份存在而 Credential 缺失或非 active
- **THEN** 保留身份事实，业务调用在 Provider 前拒绝并提示本人重新验证，不猜测或共享个人凭据

### Requirement: ONES 解绑结束绑定周期并释放当前主体归属
系统 MUST 保证同一 ONES `provider + tenant_code + external_subject_id` 至多一个 `enabled` 或 `disabled` 当前身份；`unbound` 只表示历史周期。本人解绑时原子软解绑身份和 Credential、清除可逆材料并保留原 `user_id` 与审计。管理员只可查看、停用和审计，不得启用、代解绑或代验证 ONES。

#### Scenario: ONES 当前身份仍属于其他用户
- **WHEN** 新验证命中他人的 enabled 或 disabled 身份
- **THEN** 系统返回冲突，不覆盖、共享或转移；disabled 仍占用当前主体归属

#### Scenario: ONES 主体只有解绑历史
- **WHEN** 当前用户完成新登录验证，主体仅存在他人的 unbound 历史
- **THEN** 可以创建新的当前身份和 Credential，不改写历史归属或恢复历史 Credential

#### Scenario: 两人并发绑定已释放主体
- **WHEN** 两个用户并发确认同一只有历史记录的主体
- **THEN** 数据库唯一约束只允许一个当前身份，失败方得到安全冲突且不留下活动 Credential

#### Scenario: 本人改绑另一个 ONES 账号
- **WHEN** 本人完成新验证并显式提交 `replace_existing`
- **THEN** 同一事务软解绑旧身份和 Credential 后保存新当前绑定；未确认替换则不修改现有身份

### Requirement: Provider Credential 受控刷新且不进入平台 Principal
个人密码和 Token SHALL 只在用途绑定加密 Challenge/Credential 存储和固定 Provider 客户端内使用。ONES Token 失效时可使用同一身份的受控登录材料执行有界刷新，验证返回主体一致后按 revision 轮换；无法刷新则标记需重新认证。凭据停用、解绑或身份变化后不得自动切换账号继续调用。

#### Scenario: 同一身份的 Token 正常刷新
- **WHEN** Provider 返回可分类认证失效且保存的登录材料仍有效
- **THEN** 系统受控刷新同一用户 Token，更新安全时间和 revision，不复制凭据到 Job、Prompt、卡片、日志或审计

#### Scenario: 重新登录返回不同主体
- **WHEN** 刷新结果与保存的外部主体不一致
- **THEN** 系统失败关闭并要求本人重新验证，不自动改绑

### Requirement: 身份响应使用本人和治理白名单投影
本人接口 SHALL 只从认证 Session 确定用户，返回当前身份；管理员治理接口按权限分开当前身份与默认折叠 unbound 历史，即使管理员查看自己也保持治理模式。身份摘要使用受信昵称或 ONES 用户名称、企业或 Team、状态和安全时间，不能以平台姓名或邮箱冒充 Provider 名称。

#### Scenario: 本人查看钉钉详情
- **WHEN** 用户展开自己的钉钉身份
- **THEN** 可查看本人 Staff ID、Corp ID，不获得应用观察、治理 revision、昵称历史或身份管理动作

#### Scenario: 管理员查看应用观察
- **WHEN** 管理员展开钉钉身份治理详情
- **THEN** 展示每个应用名称及首次最近观察时间，不在身份响应直接返回内部 Connector ID 或原消息

#### Scenario: 查看 ONES 身份和 Credential
- **WHEN** 本人或有权管理员读取状态
- **THEN** 返回允许的 User ID、Team 和 Credential configured/status/revision/时间事实，不返回邮箱、密码、Token、nonce、密文或原认证响应

### Requirement: 平台 Principal 按 MCP 认证模式隔离
代码固定的 MCP Server policy SHALL 分别声明 `tool-mcp` 的 Job-context、`ones-mcp` 与 `dingtalk-mcp` 的 Business Principal JWT、`file-service` 的 File Principal JWT。系统 MUST NOT 运行时注册任意认证模式、将一种凭证用于另一 Server 或以旧 Internal API Bearer 作为工具授权替代。

#### Scenario: tool-mcp 接收调用
- **WHEN** 请求具有完整 Job-context Header
- **THEN** 服务读取持久化 RUNNING Job，并逐项核对 invocation、内部用户、project、Session/Publication 适用事实、correlation、Runtime 协议与快照；Header 只供一致性检查，不授予权限

#### Scenario: Job-context 缺失或伪造
- **WHEN** Job 不存在、不在 RUNNING、Runtime 不兼容或任一必需 Header 与持久化事实冲突
- **THEN** 在列出或执行 Tool 前拒绝，不进入旧 Token/Handler/Capability 兼容路径

### Requirement: Business Principal 只从当前 Job 签发
身份服务 SHALL 仅接收内部 `job_id` 和代码固定 `server_code`，验证 RUNNING Job、有效用户、Session、Agent/Application Publication、精确 Tool Snapshot 与 authorization hash，并逐 Tool 复核当前业务授权。签发 MUST 使用 Ed25519，TTL 不超过 300 秒，固定 issuer、authorized party、单一 audience、用户/Job/Session/Publication、完整排序唯一非空 scope、authorization hash、JTI 和时间声明。

#### Scenario: 同一 Job 使用两种业务 MCP
- **WHEN** Job 分别冻结合法 ONES 和钉钉 Tool
- **THEN** 分别签发 audience 为 `ones-mcp` 和 `dingtalk-mcp` 的 Token，scope 不混合

#### Scenario: 请求未知或不适用 Server
- **WHEN** 请求给 `tool-mcp`、`file-service` 或未知 Server 签发 Business Principal
- **THEN** 签发前拒绝并写无 Token 的安全审计

#### Scenario: 只完成 ONES 身份绑定
- **WHEN** 用户未获得应用与角色 Tool 授权或没有冻结到 RUNNING Job
- **THEN** 不签发业务 Principal，不因绑定自动创建角色、Job 或业务调用

### Requirement: Business Principal 验证完整快照并实时复核授权
业务 MCP MUST 使用自身固定 expected audience 验证 EdDSA、JWKS kid、issuer、authorized party、claims 白名单、TTL、时间、JTI 和 required scope，重新读取当前 Job/用户/Publication/快照/授权摘要。Token scope 必须恰好等于该 Server 当前 Job 冻结且获授权的完整 scope 集合；每个 Tool 的 identifier、schema hash、effect、confirmation policy、operation 与 risk 必须按实际 Tool 复核。

#### Scenario: audience 或 scope 不一致
- **WHEN** ONES Token 发往钉钉 MCP，或 scope 仅为快照子集或超集
- **THEN** 服务在解析 Provider Credential 或访问 Provider 前拒绝

#### Scenario: 用户或角色在签发后被撤销
- **WHEN** Token 未过期但当前用户、应用授权或 Tool grant 已失效
- **THEN** 当前调用失败关闭，不把短期 Token 当作不可撤销授权

#### Scenario: Runtime 转交 Principal
- **WHEN** Runtime 收到分 Server Token
- **THEN** 仅在内存向对应服务转交，不向模型、沙盒文件、环境、日志或可持久化 Job 参数暴露 Token

### Requirement: File Principal 与内部 Service Principal 保持独立边界
File Principal SHALL 使用专用签发与验证路径，绑定用户、租户、RUNNING Job、Session、两个 Publication、授权快照和精确 File Tool scope，并复核任务工作区。内部文件调用 SHALL 使用固定角色 `file-worker`、`file-processing-worker`、`delivery-worker` 的 Service Principal；它们共享平台签名信任根和公开 JWKS，但使用独立 issuer、`aud=file-service-internal`、相同 sub/azp 角色和完整固定 scope，TTL 均不超过 300 秒。

#### Scenario: Worker 获取内部身份
- **WHEN** Worker 用自己独立 bootstrap credential 调用内部身份接口
- **THEN** 只签发该角色固定 scope 的短期 Token，Worker 按需在内存刷新，不持有平台签名私钥、其他角色凭据或预生成长期 JWT

#### Scenario: 跨角色或跨认证面调用
- **WHEN** Delivery Token 调用附件导入，Service Principal 调普通 File MCP，或 Business Principal 调文件内部接口
- **THEN** 独立验证策略拒绝，共享 JWKS 不使权限互通

#### Scenario: File Principal 到期
- **WHEN** 仍在运行的 Job 通过受控刷新通道申请新 File Principal
- **THEN** 平台重新校验 Job、租户、工作区与当前授权后签发，不用业务 MCP Token 作为 fallback

### Requirement: 钉钉业务身份由当前 Job 和同企业持久事实解析
`dingtalk-mcp` SHALL 在验证自身 Principal 后，从当前 Job 的内部用户、来源 Connector 与企业解析唯一启用钉钉身份。需要 union ID 的 Tool 可用同一 Connector 固定联系人详情接口核对 Staff ID 后原子补全；不需要 union ID 的 Tool 不得仅因缺少它拒绝。Provider 可见范围和当前 operator 权限不因 Tool grant 扩大。

#### Scenario: 受信补全身份
- **WHEN** 原身份只有 Staff ID 且目标 Tool 需要 union ID
- **THEN** 只从同一 Connector 官方固定接口核对并补全同一身份，不接收 Prompt、JWT 或 Tool 参数中的身份覆盖

#### Scenario: 非空身份事实冲突
- **WHEN** Stream 或固定详情响应的 union ID 与持久值不同
- **THEN** 保留原身份、写安全错误并拒绝，不覆盖或改用其他 Connector

### Requirement: mutation 复核原身份且区分确认人和收件人
外部 mutation SHALL 以准备时内部用户、原外部身份、目标 Team 或来源企业与 Connector 等持久事实作为确认和执行约束。确认及 Provider 执行前 MUST 重新复核原主体、当前 Credential、角色、Publication 和 Job Tool Snapshot；正常同身份凭据刷新可以使用，新身份不得静默继承旧 Intent。批量机器人 `user_ids` 是独立收件人集合，不授予确认权。

#### Scenario: ONES 用户确认后换绑或停用
- **WHEN** 执行时原 ONES 身份已不可用或当前身份 ID 不同
- **THEN** 拒绝原 Intent，不回退到新绑定；冻结目标 Team 仍须在原身份最新验证集合中

#### Scenario: ONES 默认 Team 改变
- **WHEN** 原 Intent 目标 Team 仍在已验证集合中而默认 Team 已变
- **THEN** 按 Intent 的原目标 Team 复核，不静默切换默认 Team

#### Scenario: 钉钉主体或执行身份漂移
- **WHEN** 原身份、企业、Connector/Credential 关联或 robot code 已改变
- **THEN** Provider 写入前拒绝，不替换 Connector、人员或收件人继续执行

#### Scenario: 用户明确选择批量消息收件人
- **WHEN** 用户通过本 Job 已授权搜索和详情核实、必要消歧或直接明确 userId 选择收件人
- **THEN** 冻结独立 `user_ids`，原发起人仍是唯一确认主体；不得以当前用户、昵称首个匹配或其他 Job 候选替代目标，MCP 服务对直接明确 ID 不额外进行隐式逐收件人预查

### Requirement: 身份和授权审计不携带认证材料
用户、角色、成员、身份、Credential 状态、Principal 生命周期和授权拒绝 SHALL 保存操作者、目标、结果、稳定安全错误与必要关联。敏感密码、Token、Cookie、CSRF、Principal JWT、平台私钥、可逆密文、session webhook、原始业务消息和 Provider 认证响应 MUST NOT 进入审计、日志或管理响应。业务执行、Tool 和 Delivery 审计的完整链路由 `execution-delivery` 定义。

#### Scenario: Principal 签发或验证失败
- **WHEN** 平台记录拒绝事实
- **THEN** 仅保存 JTI/kid 等适用安全元数据、Job/actor、audience、scope 摘要与错误，不保存 Token 或原 claims 中非法敏感值

#### Scenario: 查看权限解释
- **WHEN** 授权管理员查看决策 trace
- **THEN** 获得内部用户、角色来源、资源动作、目标范围和安全拒绝原因，不获得可恢复凭据或原始敏感数据

## 实现依据与验证边界

本基线于 2026-09-16 依据当前代码、迁移和测试定义重组；`Confirmed-current` 表示仓库实现事实，不能据此宣称已部署或已通过真实环境验收。

- 用户、Session、认证响应：`backend/app/modules/identity/application/auth_service.py`、`admin_service.py`、`backend/app/modules/identity/api/dependencies.py`、`auth_controller.py`；静态覆盖见 `backend/tests/test_unified_identity_rbac.py`、`test_management_surface_authorization.py` 与 `frontend/src/contexts/auth/presentation/` 测试。
- 角色与严格授权：`backend/app/modules/identity/application/authorization.py`、`backend/app/modules/authorization_center/application/service.py`、`backend/app/modules/identity/infrastructure/repository.py`；静态覆盖见 `backend/tests/test_role_authorization_control_center.py`，包括两名已登录验证管理员、并发撤权、委派和无数据权限旁路。
- 钉钉企业、身份、候选：`backend/app/modules/managed_channel/application/service.py`、`backend/app/modules/identity/application/identity_service.py`、`backend/app/modules/identity_discovery/application/service.py`；静态覆盖见 `backend/tests/test_dingtalk_enterprise_governance.py`、`test_dingtalk_identity_observations.py`、`test_dingtalk_identity_discovery.py`、`test_dingtalk_identity_discovery_api.py`。
- ONES 本人绑定与 Credential：`backend/app/modules/identity/application/ones_identity_binding.py`、`backend/app/modules/identity/infrastructure/ones_identity_verifier.py`、`ones_identity_challenges.py`、`external_identity_credentials.py`；唯一性依据 `backend/migrations/126_release_unbound_ones_identity.sql` 与 `130_restore_dingtalk_identity_indexes.sql`；静态覆盖见 `backend/tests/test_ones_identity_binding.py`、`test_external_identity_credentials.py`。
- Principal 与服务身份：`backend/app/shared/mcp_server_policy.py`、`backend/app/modules/identity/application/principal_jwt.py`、`service_principal.py`、`backend/app/modules/identity/api/file_principal_refresh_controller.py`；静态覆盖见 `backend/tests/test_principal_jwt.py`、`test_business_mcp_principal_policy.py`、`test_service_principal_identity.py`、`test_dingtalk_mcp_runtime.py`。
- 本次只校验文档与代码/测试定义的一致性及 OpenSpec 结构，未运行真实 ONES、钉钉、数据库迁移、登录或 Provider 写入验收；测试文件存在不代表本次执行通过。历史 active change 中未完成任务仍属于独立验收欠账，归档不能作为运行证明。
