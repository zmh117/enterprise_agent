## ADDED Requirements

### Requirement: 旧 Connection 凭据不得迁移到新 Provider Credential
切换 MUST 删除所有引用 API Connection Revision 的 `external_api_credential`、临时 ONES Challenge 与密文 Token，不得备份、导出、解密后重存或自动转换；保留的 ONES 稳定身份 MUST 标记为 `REVERIFICATION_REQUIRED`，只有本人完成新的两阶段验证后才能创建 `provider_credential`。

#### Scenario: 旧用户在切换后首次登录
- **WHEN** 用户保留 ONES user UUID 与默认 Team 元数据但旧凭据已删除
- **THEN** 门户显示需要重新验证，ONES MCP Tool 保持不可用且系统不尝试读取旧密文

#### Scenario: 用户重新验证成功
- **WHEN** 本人完成新 Provider 实例的两阶段验证并确认候选 Team
- **THEN** 系统创建全新的加密 Provider Credential，身份恢复 enabled，且记录中不引用旧 Connection Revision

## MODIFIED Requirements

### Requirement: 外部身份与个人 API 凭据分离持久化
系统 MUST 将 ONES External Identity 用于证明稳定外部主体，将 Provider Credential 用于保存加密个人 Token；Provider Credential MUST 关联内部用户、精确外部身份和受信 ONES Provider 实例，不得关联已删除的 Capability 或 Connection Revision。明文密码 MUST NOT 持久化，个人 Token MUST NOT 保存到共享平台 Secret、身份展示字段、日志、审计或 API 响应。

#### Scenario: 用户完成 ONES 重新验证
- **WHEN** 两阶段验证成功并选择默认 Team
- **THEN** 系统分别保存外部 User ID/Team 元数据和新加密 Token，并关联同一内部用户、外部身份与 Provider 实例

#### Scenario: 管理员查看用户绑定
- **WHEN** 管理员读取他人的 ONES 外部身份
- **THEN** API 只返回 User ID、默认 Team、凭据状态和验证时间，不返回 Token、密码或可逆密文

### Requirement: ONES 自助验证分为 Challenge 两阶段
ONES 自助绑定第一阶段 MUST 从认证会话确定当前内部用户，使用受信 ONES Provider 实例调用登录接口，并创建与当前用户和 Provider 实例绑定的短时单次 Verification Challenge；响应只能包含 Challenge ID 和安全 User/Team 候选，MUST NOT 包含 Token。

#### Scenario: 第一阶段验证成功
- **WHEN** 当前用户提交有效邮箱密码
- **THEN** 系统在请求结束前丢弃密码，创建包含加密临时 Token、候选摘要、过期时间和未消费状态的 Challenge，并返回安全候选

#### Scenario: 客户端提交目标用户
- **WHEN** 自助接口请求包含其他 `user_id`
- **THEN** 系统拒绝或忽略该字段并只使用认证会话中的当前用户

#### Scenario: 第一阶段验证失败
- **WHEN** ONES 拒绝凭据或响应不符合 Provider 契约
- **THEN** 系统不创建 Challenge、身份或凭据，并返回不泄露账号存在性和认证材料的安全错误

### Requirement: Challenge 确认原子保存默认 Team 和凭据
第二阶段 MUST 校验 Challenge 属于当前用户、精确 Provider 实例、未过期且未消费，并只允许选择 Challenge 候选中的 Team；成功后 MUST 在一个事务中保存外部 User ID、最新验证 Team 集合、default Team、新加密 Provider Credential 和验证时间，并将 Challenge 标记为已消费。

#### Scenario: 用户选择合法默认 Team
- **WHEN** 当前用户提交有效 Challenge 和候选中的 Team ID
- **THEN** 系统原子更新身份与凭据，且后续重复消费同一 Challenge 被拒绝

#### Scenario: 用户选择候选外 Team
- **WHEN** 提交的 Team ID 不在 Challenge 的已验证候选集合中
- **THEN** 系统拒绝确认，不改变现有身份或凭据

#### Scenario: Challenge 已过期
- **WHEN** 用户提交过期或已消费的 Challenge
- **THEN** 系统失败关闭并要求重新验证，不使用其中 Token

### Requirement: 第一版每个用户只有一个有效 ONES 账号
第一版 MUST 只支持一个受信 ONES Provider 实例，且每个内部用户最多一个当前有效 ONES External Identity、一个 default Team 和一个有效 Provider Credential；界面和 API MUST NOT 提供实例或账号选择器。

#### Scenario: 用户重复绑定同一 ONES 主体
- **WHEN** 用户再次验证同一外部 User ID
- **THEN** 系统幂等更新允许更新的 Team、默认 Team、Token 和验证时间，不创建第二个有效账号

#### Scenario: 用户尝试绑定不同 ONES 主体
- **WHEN** 当前用户已有有效主体却确认另一个 User ID
- **THEN** 系统要求显式换绑并原子使旧主体与凭据失效，不得同时保留两个有效账号

#### Scenario: 外部主体已属于其他内部用户
- **WHEN** 经验证 ONES User ID 已绑定给另一个启用内部用户
- **THEN** 系统返回冲突，不自动迁移、转移或共享凭据

### Requirement: 本人和管理员复用外部身份面板
轻量用户门户 SHALL 复用同一外部身份事实提供本人模式与只读治理摘要。本人模式允许当前用户完成钉钉 Challenge、ONES 两阶段验证、切换 default Team、重新验证和解绑；管理员不得代用户输入 ONES 密码、查看 Token 或直接填写钉钉 subject，只能通过受控管理 API 禁用或解绑已验证身份。

#### Scenario: 普通用户管理本人身份
- **WHEN** 已认证用户打开“我的外部身份”
- **THEN** 页面只以当前 Session 主体调用本人接口，并提供钉钉 Challenge 与 ONES 重新验证

#### Scenario: 管理员尝试代填主体
- **WHEN** 管理员提交其他用户的 ONES 密码或钉钉 subject
- **THEN** 系统拒绝操作且不访问 Provider 登录或绑定路径

### Requirement: ONES 身份与个人凭据精确关联
本人 ONES 状态 MUST 根据 Provider Credential 的 `external_identity_id + provider_instance_id` 返回对应当前身份，或使用等价单次关联查询；系统 MUST NOT 分别选择第一条 ONES 身份和最新凭据后拼接响应。

#### Scenario: 历史 ONES 身份排序在当前身份之前
- **WHEN** 用户的历史 ONES 身份排序早于当前身份
- **THEN** 本人状态仍返回当前 Provider Credential 精确关联的身份、Team 和默认 Team

#### Scenario: 当前身份尚未重新验证
- **WHEN** 保留身份为 `REVERIFICATION_REQUIRED` 且不存在新 Provider Credential
- **THEN** 系统返回需要重新验证的安全状态，不拼接其他凭据或声称可调用

## REMOVED Requirements

### Requirement: 现有 ONES 身份记录非破坏迁移
**Reason**: 用户明确要求旧 API/Internal Platform 数据不备份、不迁移；依赖旧 Connection Revision 的 Token 凭据必须删除。

**Migration**: 只保留稳定身份与默认 Team 元数据并标记需重新验证；用户本人重新验证后创建全新 Provider Credential。
