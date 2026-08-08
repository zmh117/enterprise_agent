## ADDED Requirements

### Requirement: 本人和治理接口使用不同身份投影
系统 MUST 根据“我的外部身份”和“人员管理 → 用户详情”两个入口分别返回本人投影和治理投影，不得返回完整数据库行后仅依赖前端隐藏越权字段；即使管理员查看自己的人员记录，人员详情仍 MUST 使用治理投影。

#### Scenario: 用户查看我的外部身份
- **WHEN** 已认证用户打开“我的外部身份”
- **THEN** 系统只从认证会话确定本人并返回本人允许字段，不读取或返回其他用户、应用观察、治理 Revision 或原始错误码

#### Scenario: 管理员查看自己的人员详情
- **WHEN** 管理员从人员管理打开自己的用户记录
- **THEN** 系统按治理权限返回治理投影，不自动切换为本人自助模式

#### Scenario: 前端请求未授权技术字段
- **WHEN** 本人接口请求包含展开应用观察、凭据 Revision 或错误码的参数
- **THEN** 系统忽略或拒绝请求且响应中不包含这些字段

### Requirement: 钉钉本人摘要使用友好企业身份字段
钉钉本人摘要 SHALL 展示钉钉昵称、企业名称、身份状态和最近使用；本人只允许展开自己的钉钉用户 ID 与 Corp ID，不得返回应用观察、Connector ID、数据 Revision、昵称历史或治理动作。

#### Scenario: 本人钉钉昵称已获取
- **WHEN** 当前用户存在启用钉钉身份和非空受信昵称
- **THEN** 页面以昵称作为身份名称，并展示企业名称、状态和最近使用

#### Scenario: 本人钉钉昵称尚未获取
- **WHEN** 当前身份没有可验证的非空昵称
- **THEN** 页面显示“尚未从钉钉获取昵称”，不得使用平台人员姓名冒充钉钉昵称

#### Scenario: 本人展开钉钉账户详情
- **WHEN** 当前用户展开自己的钉钉账户详情
- **THEN** 页面只增加显示钉钉用户 ID 与 Corp ID，且仍不提供本人绑定、启停或解绑动作

### Requirement: 钉钉治理摘要分层展示来源事实
钉钉治理摘要 SHALL 默认展示昵称、企业名称、身份状态和最近使用；管理员技术详情 MAY 展示钉钉用户 ID、Corp ID、绑定确认时间、身份 Revision 以及按应用名称汇总的首次和最近观察时间，但 MUST NOT 把内部 Connector ID 作为身份卡日常信息。

#### Scenario: 管理员查看多应用观察身份
- **WHEN** 身份已经通过同企业多个应用被观察
- **THEN** 默认卡仍只显示一个身份，技术详情显示“经 N 个钉钉应用观察”及每个应用名称和时间

#### Scenario: 管理员需要 Connector ID 排障
- **WHEN** 管理员从身份卡查看应用观察
- **THEN** 身份响应不直接返回 Connector ID，并提供进入对应应用连接配置或审计页面的路径

### Requirement: ONES 用户名称只来自验证结果
系统 SHALL 将 ONES 登录验证接口返回的用户 `name` 保存并展示为“ONES 用户名称”，每次本人重新验证成功后刷新；管理员不得手工修改，系统不得以平台人员姓名、登录邮箱或其他内部字段代替。

#### Scenario: ONES 返回用户名称
- **WHEN** 本人验证成功且 ONES 响应包含有效用户名称
- **THEN** 系统保存最新名称并在本人和治理摘要中展示

#### Scenario: ONES 未返回用户名称
- **WHEN** 验证响应没有可用用户名称
- **THEN** 页面显示“ONES 未返回用户名称”，不回退到平台人员显示名称

#### Scenario: 查看 ONES 登录字段
- **WHEN** 本人或管理员查看 ONES 身份
- **THEN** 页面不展示登录邮箱或密码，也不暗示平台持久化了这些登录字段

### Requirement: ONES 保存并展示已验证 Team 名称和 ID
确认 ONES Verification Challenge 时，系统 MUST 保存本次响应的完整已验证 Team 候选 `[{id, name}]` 和单一默认 Team，并 MUST 以最新成功验证集合整体替换旧集合；不再返回的 Team 不得继续可选。

#### Scenario: 验证返回多个有名称 Team
- **WHEN** 用户从最新验证候选中选择一个默认 Team
- **THEN** 系统保存所有候选的名称与 ID，默认摘要显示“Team 名称（Team ID）”，其他候选进入“可用 Team”折叠区域

#### Scenario: Team 没有名称
- **WHEN** 某个验证候选只有 Team ID
- **THEN** 页面显示 Team ID 并标记“名称暂不可用”，不得生成虚假 Team 名称

#### Scenario: 重新验证后 Team 被撤销
- **WHEN** 最新验证响应不再包含旧候选 Team
- **THEN** 系统从当前候选集合移除该 Team，且不得允许继续选择

#### Scenario: 迁移旧 ONES Team ID
- **WHEN** 现有 ONES 身份只有 `team_uuids` 而没有名称
- **THEN** 系统非破坏转换为名称为空的结构化候选，保留默认 Team 和个人凭据，并在下次重新验证后刷新名称

### Requirement: ONES 身份与凭据状态分别治理
系统 MUST 分别保存并展示 ONES 身份绑定状态和个人凭据状态；本人摘要 SHALL 由两者计算“可使用”“需要重新验证”或“已被管理员停用”的业务可用状态，治理详情不得只返回无法解释的原始 `ACTIVE` 标签。

#### Scenario: 身份与凭据均可用
- **WHEN** ONES 身份已启用且精确关联的个人凭据有效
- **THEN** 本人摘要显示“可使用”，管理员详情分别显示“身份绑定状态：已启用”和“个人凭据状态：有效”

#### Scenario: 身份存在但凭据缺失或失效
- **WHEN** 当前身份没有精确关联凭据、凭据无效或认证失败
- **THEN** 本人摘要显示“需要重新验证”及安全操作提示，不返回原始错误码

#### Scenario: 身份或凭据被治理停用
- **WHEN** 管理员停用身份或个人凭据
- **THEN** 本人摘要显示“已被管理员停用”，且不得提供绕过治理状态的运行时能力

### Requirement: ONES 默认摘要只展示业务字段
ONES 本人和治理模式的默认摘要 SHALL 统一展示 ONES 用户名称、业务可用状态、默认 Team、最近验证和最近成功使用；默认摘要 MUST NOT 展示固定“租户／实例：ones”“连接器：服务端 ONES 实例”、身份 Revision、凭据 Revision 或原始错误码。

#### Scenario: ONES 绑定可用
- **WHEN** 页面加载一个具有默认 Team 和有效凭据的当前 ONES 身份
- **THEN** 默认卡只展示约定五类业务字段和适用操作，不展示固定占位或技术 Revision

#### Scenario: 从旧通用身份卡升级
- **WHEN** 旧记录仍含 `tenant_code=ones` 或空 Connector 字段
- **THEN** 新页面忽略这些通用占位字段，不将其渲染为用户可见信息

### Requirement: ONES 账户详情按本人和管理员划分
系统 SHALL 允许本人展开自己的 ONES User ID 和全部已验证 Team 名称／ID；管理员治理详情 SHALL 在具备相应权限时额外展示身份记录 ID 与 Revision、个人凭据状态与 Revision、所绑定 ONES Connection 名称和精确发布版本、最近尝试、最近错误码和错误时间。

#### Scenario: 本人展开 ONES 账户详情
- **WHEN** 当前用户展开本人 ONES 卡片
- **THEN** 系统只返回和展示自己的 User ID 与 Team 明细，不返回凭据 Revision、Connection 内部版本或错误码

#### Scenario: 管理员展开 ONES 技术详情
- **WHEN** 具备外部凭据读取权限的管理员展开他人 ONES 技术详情
- **THEN** 系统返回允许的身份、凭据、Connection 和调用状态元数据，但不允许管理员绑定或重新验证他人凭据

### Requirement: ONES 凭据记录真实使用事实
系统 SHALL 为 ONES 个人凭据维护最近尝试时间、最近成功使用时间、最近错误码和错误发生时间；只有使用持久化个人凭据发起真实外部请求且最终规范化输出通过 Output Schema 校验时，才更新最近成功使用。

#### Scenario: Agent Runtime 成功调用 ONES
- **WHEN** Agent 使用当前用户个人凭据完成 ONES 请求、Mapping 和 Output Schema 校验
- **THEN** 系统更新最近尝试和最近成功使用，并在调用审计中标记来源 `RUNTIME`

#### Scenario: 管理员 Capability Test 成功
- **WHEN** 管理员使用自己的持久化个人凭据完成 Capability Test
- **THEN** 系统更新最近尝试和最近成功使用，并在调用审计中标记来源 `ADMIN_TEST`

#### Scenario: ONES 调用终态失败
- **WHEN** 使用个人凭据的真实请求最终失败
- **THEN** 系统更新最近尝试、最近错误码和错误时间，不覆盖已有最近成功使用时间

#### Scenario: 本人重新验证凭据
- **WHEN** 用户完成登录验证和 Challenge 确认但未调用 ONES 业务 API
- **THEN** 系统只更新最近验证，不更新最近尝试或最近成功使用

#### Scenario: Connection 启动验证成功
- **WHEN** 首个 Connection 使用瞬时管理员密码和 Token 完成启动验证
- **THEN** 系统不更新任何持久化个人凭据的使用事实

### Requirement: 身份响应根本不包含认证材料
本人和治理外部身份接口 MUST NOT 返回 Token、密码、可逆密文、认证 Header、Client Secret、Session Webhook、Verification Challenge 内部 Token 或原始外部响应；前端不得通过日志或其他管理接口拼接这些材料。

#### Scenario: 管理员拥有凭据治理权限
- **WHEN** 管理员读取他人的 ONES 技术详情
- **THEN** 响应仍只包含状态与安全元数据，不返回 Token、密文或登录字段

#### Scenario: 身份接口序列化数据库记录
- **WHEN** 底层记录包含 Secret reference、密文或内部 Challenge 标识
- **THEN** 专用响应白名单排除这些字段，测试证明它们不出现在响应 JSON
