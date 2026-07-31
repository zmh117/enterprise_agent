## ADDED Requirements

### Requirement: 外部身份与个人 API 凭据分离持久化
系统 MUST 将 ONES External Identity 用于证明外部主体，将 External API Credential 用于保存加密个人 Token；明文密码 MUST NOT 持久化，个人 Token MUST NOT 保存到共享平台 Secret、身份展示字段、日志、审计或 API 响应。

#### Scenario: 用户完成 ONES 绑定
- **WHEN** 两阶段验证成功并选择默认 Team
- **THEN** 系统分别保存外部 User ID/Team 元数据和加密 Token，并关联同一内部用户与 Published Connection Revision

#### Scenario: 管理员查看用户绑定
- **WHEN** 管理员读取他人的 ONES 外部身份
- **THEN** API 只返回 User ID、默认 Team、凭据状态和验证时间，不返回 Token、密码或可逆密文

### Requirement: ONES 自助验证分为 Challenge 两阶段
ONES 自助绑定第一阶段 MUST 从认证会话确定当前内部用户，使用邮箱密码调用精确 Connection/Authentication Profile Revision，并创建与当前用户和 Connection Revision 绑定的短时单次 Verification Challenge；响应只能包含 Challenge ID 和安全 User/Team 候选，MUST NOT 包含 Token。

#### Scenario: 第一阶段验证成功
- **WHEN** 当前用户提交有效邮箱密码
- **THEN** 系统丢弃密码，创建包含加密临时 Token、候选摘要、过期时间和未消费状态的 Challenge，并向浏览器返回安全候选

#### Scenario: 客户端提交目标用户
- **WHEN** 自助接口请求包含其他 `user_id`
- **THEN** 系统拒绝或忽略该字段并只使用认证会话中的当前用户

#### Scenario: 第一阶段验证失败
- **WHEN** ONES 拒绝凭据或响应不符合 Authentication Profile
- **THEN** 系统不创建 Challenge、身份或凭据，并返回不泄露账号存在性和认证材料的安全错误

### Requirement: Challenge 确认原子保存默认 Team 和凭据
第二阶段 MUST 校验 Challenge 属于当前用户、精确 Connection Revision、未过期且未消费，并只允许选择 Challenge 候选中的 Team；成功后 MUST 在一个事务中保存外部 User ID、最新验证 Team 集合、default Team、加密 Token 和验证时间，并将 Challenge 标记为已消费。

#### Scenario: 用户选择合法默认 Team
- **WHEN** 当前用户提交有效 Challenge 和候选中的 Team ID
- **THEN** 系统原子更新身份与凭据，且后续重复消费同一 Challenge 被拒绝

#### Scenario: 用户选择候选外 Team
- **WHEN** 提交的 Team ID 不在 Challenge 的已验证候选集合中
- **THEN** 系统拒绝确认，不改变现有身份或凭据

#### Scenario: Challenge 已过期
- **WHEN** 用户提交过期或已消费的 Challenge
- **THEN** 系统失败关闭并要求重新验证，不使用其中 Token

### Requirement: 切换默认 Team 必须重新验证
用户切换 ONES default Team MUST 重新提交邮箱密码并创建新 Challenge，以 ONES 当前返回的 Team 集合为准；系统 MUST NOT 允许直接从历史 Team 集合切换。

#### Scenario: 最新 Team 集合包含目标 Team
- **WHEN** 用户重新验证并选择新响应中的 Team
- **THEN** 系统原子刷新 User、Team 集合、default Team 和 Token

#### Scenario: 历史 Team 已被撤销
- **WHEN** 旧绑定包含某 Team 但新登录响应不再包含它
- **THEN** 系统不得允许选择该 Team，并从最新验证集合中移除

### Requirement: 第一版每个用户只有一个有效 ONES 账号
第一版 MUST 只支持一个逻辑 ONES Connection，且每个内部用户最多一个当前有效 ONES External Identity、一个 default Team 和一个有效个人 Token；界面和 API MUST NOT 提供实例或账号选择器。

#### Scenario: 用户重复绑定同一 ONES 主体
- **WHEN** 用户再次验证同一外部 User ID
- **THEN** 系统幂等更新允许更新的 Team、默认 Team、Token 和验证时间，不创建第二个有效账号

#### Scenario: 用户尝试绑定不同 ONES 主体
- **WHEN** 当前用户已有有效主体却确认另一个 User ID
- **THEN** 系统按显式换绑流程原子替换并使旧主体不再有效，不得同时保留两个有效账号

#### Scenario: 外部主体已属于其他内部用户
- **WHEN** 经验证 ONES User ID 已绑定给另一个启用内部用户
- **THEN** 系统返回冲突，不自动迁移或共享凭据

### Requirement: 本人和管理员复用外部身份面板
现有 `ExternalIdentityPanel` SHALL 支持本人模式与管理员治理模式；本人模式允许绑定、重新验证、切换 default Team 和解绑，管理员查看他人时只允许读取元数据、禁用或软解绑，不得显示邮箱密码表单或代替用户重新验证。

#### Scenario: 普通用户访问我的外部身份
- **WHEN** 已认证普通用户打开“我的外部身份”
- **THEN** 系统复用本人模式面板，且该用户不能访问人员列表、角色、会话或其他用户详情

#### Scenario: 管理员查看其他用户
- **WHEN** 管理员打开他人的用户详情外部身份区域
- **THEN** 面板进入治理模式，只显示允许元数据和禁用/解绑操作

#### Scenario: 管理员查看本人
- **WHEN** 管理员在用户详情查看自己的记录
- **THEN** 面板进入本人模式，但仍须通过自助接口从会话解析本人身份

### Requirement: 个人凭据操作使用本人权限和受限管理员权限
系统 MUST 使用 `external_credentials.self_manage` 授权本人绑定、重新验证、切换 Team 和解绑；管理员对他人的操作只允许 `external_credentials.read/disable/unbind`，不得读取或轮换 Token。

#### Scenario: 普通用户管理本人凭据
- **WHEN** 当前用户具备 self_manage 并调用本人接口
- **THEN** 系统允许受控操作并记录不含邮箱密码和 Token 的审计

#### Scenario: 管理员尝试代用户重新验证
- **WHEN** 管理员在他人上下文提交邮箱密码或凭据轮换请求
- **THEN** 系统拒绝操作且不访问 ONES 登录端点

### Requirement: 解绑和凭据错误具有明确状态
解绑 MUST 软删除身份并禁用关联个人凭据；外部 API 返回 401 时系统 MUST 将当前凭据标记为 invalid，403 MUST 保留凭据有效状态；任何状态变更 MUST 保留审计且不得删除历史事实。

#### Scenario: 用户解绑 ONES
- **WHEN** 本人确认解绑
- **THEN** 系统原子停用身份与凭据，后续 Tool 暴露和执行均失败关闭

#### Scenario: 外部 API 返回 401
- **WHEN** 使用当前凭据的调用收到 401
- **THEN** 系统标记该凭据 invalid，不重试，并提示用户重新验证

#### Scenario: 外部 API 返回 403
- **WHEN** 调用收到 403
- **THEN** 系统不重试但保留凭据状态，并返回权限不足的安全结果

### Requirement: 现有 ONES 身份记录非破坏迁移
已有只有身份元数据而没有个人 Token 的 ONES 记录 MUST 保留，并 SHALL 显示“需要凭据验证”；迁移 MUST NOT 伪造 Token、自动共享服务账号或强制删除后重新绑定。

#### Scenario: 旧用户打开外部身份面板
- **WHEN** 用户存在历史 ONES User ID 和 Team 元数据但没有 External API Credential
- **THEN** 面板保留身份信息并提示完成重新验证，运行时不暴露依赖 ONES 凭据的 Capability
