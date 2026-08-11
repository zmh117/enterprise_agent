## MODIFIED Requirements

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

## ADDED Requirements

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

## REMOVED Requirements

### Requirement: Challenge 确认原子保存默认 Team 和凭据
**Reason**: 身份确认不得再保存长期个人调用 Token 或 API Connection 关联。
**Migration**: 使用不含 Token 的身份 Challenge，只保存 User ID、Team、默认 Team 和验证时间。

### Requirement: ONES 身份与个人凭据精确关联
**Reason**: 长期个人业务调用凭据随旧 API Connection/Capability 永久退役，身份不再依赖 Credential。
**Migration**: 本人状态直接从当前 ONES Identity 投影。

### Requirement: 个人凭据操作使用本人权限和受限管理员权限
**Reason**: Credential 读取、轮换、disable 和 usage 状态全部删除。
**Migration**: 仅保留身份本人操作与管理员身份治理权限。

### Requirement: 解绑和凭据错误具有明确状态
**Reason**: API 调用 Credential 错误状态随旧 Capability 运行时删除。
**Migration**: 解绑和停用只作用于外部身份并保留审计。
