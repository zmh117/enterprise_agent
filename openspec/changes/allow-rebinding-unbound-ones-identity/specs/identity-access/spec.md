## MODIFIED Requirements

### Requirement: ONES 身份通过服务端登录验证
系统 SHALL 允许已认证的人类用户本人使用服务端配置的受信任 ONES 实例和固定登录端点验证自己的 ONES 邮箱与密码，并 SHALL 使用响应中的用户 UUID 作为外部身份标识。管理员只能查看、停用和审计，不得代用户提交邮箱、密码、Token、Team 或目标 URL。已 `unbound` 的 ONES 历史身份不得阻止通过新验证形成新的当前绑定。

#### Scenario: ONES凭据验证成功
- **WHEN** 当前用户提交自己的 ONES 邮箱和有效密码
- **THEN** 系统调用固定 `/project/api/project/auth/login`，校验响应结构，并创建短期 challenge，包含已验证用户 UUID、显示名称、Team 候选和加密登录材料/Token

#### Scenario: 管理员尝试代用户验证
- **WHEN** 管理员在人员管理上下文提交他人的邮箱密码
- **THEN** 系统拒绝且不访问 ONES 登录端点

#### Scenario: ONES凭据无效
- **WHEN** ONES 登录接口拒绝邮箱或密码
- **THEN** 系统返回安全验证失败，不创建身份或当前 credential；审计可记录提交邮箱、actor 和安全错误码，但不得记录密码、Token 或 Provider 认证响应原文

#### Scenario: 客户端提交可信字段
- **WHEN** 请求包含手工 ONES UUID、Token、Team、目标 URL、Header 或 Provider 配置
- **THEN** 系统拒绝请求，可信身份与凭据字段只能来自固定 Adapter 响应和后续 Team 确认

#### Scenario: ONES当前身份属于其它用户
- **WHEN** 经验证 ONES UUID 存在属于另一内部用户的 `enabled` 或 `disabled` 当前身份
- **THEN** 系统返回冲突，不覆盖、转移或共享身份和 credential

#### Scenario: ONES历史身份已由其它用户解绑
- **WHEN** 经验证 ONES UUID 只有属于其它内部用户的 `unbound` 历史身份
- **THEN** 系统 SHALL 允许当前用户继续确认绑定并创建新的当前身份与 credential
- **AND** 系统 MUST NOT 修改历史身份的原用户归属或恢复其已清除 credential

### Requirement: 外部身份生命周期可管理
系统 SHALL 区分提供方治理动作：钉钉身份继续由管理员按受信候选进行启停和软解绑；ONES 身份由本人绑定、重新验证和软解绑，管理员只可查看、停用和审计，不得启用、代验证或代解绑 ONES。ONES 本人解绑 SHALL 终止当前绑定周期并释放该外部主体的当前归属占用，但 MUST 保留原身份和审计历史。

#### Scenario: 管理员停用 ONES 身份
- **WHEN** 管理员使用当前 Revision 停用 ONES 身份
- **THEN** 系统停用并记录审计，重新启用必须由本人完成新一轮验证
- **AND** 停用身份仍占用当前 ONES 主体，其他用户不得绑定

#### Scenario: 用户本人解绑 ONES 身份
- **WHEN** 当前用户解绑自己的 ONES 身份
- **THEN** 系统将身份和 Credential 标记为 `unbound`、清除可逆凭据材料并记录审计
- **AND** 该身份不再占用 ONES 外部主体的当前归属，历史身份的 `user_id` 保持不变

#### Scenario: 管理员尝试解绑 ONES 身份
- **WHEN** 管理员调用通用身份解绑接口处理 ONES 身份
- **THEN** 系统拒绝且保持身份事实不变

### Requirement: 外部主体在受信范围内唯一绑定
系统 MUST 使用 `provider + tenant_code + external_subject_id` 识别同一外部主体，并 MUST 保证同一 ONES 外部主体最多只有一个 `enabled` 或 `disabled` 当前身份。ONES 的 `unbound` 行仅表示历史绑定周期，不占用当前身份唯一性；钉钉身份仍保留跨状态的原人员历史归属。系统 MUST NOT 依据姓名、昵称、邮箱或手机号自动关联，也不得引入不存在的 Connection 或 Claim 作为授权事实。

#### Scenario: 唯一外部主体首次绑定
- **WHEN** 验证结果中的 subject 在该 provider 和 tenant 范围内没有当前绑定
- **THEN** 系统原子创建指向目标内部用户的身份

#### Scenario: 相同主体绑定同一用户
- **WHEN** 同一用户再次验证已经属于自己的当前外部主体
- **THEN** 系统幂等刷新验证时间和受控 provider 上下文
- **AND** 不创建重复当前身份

#### Scenario: ONES相同当前主体属于另一个用户
- **WHEN** provider、tenant 和 subject 对应的 ONES `enabled` 或 `disabled` 当前身份属于其它内部用户
- **THEN** 系统保留原身份并拒绝当前绑定
- **AND** 不依据显示字段自动覆盖、合并或转移身份

#### Scenario: ONES相同主体只有解绑历史
- **WHEN** provider、tenant 和 subject 只命中一个或多个 ONES `unbound` 历史身份
- **THEN** 系统 SHALL 允许已完成新登录验证的当前用户创建新的当前身份
- **AND** 所有历史身份继续关联其原内部用户

#### Scenario: 钉钉解绑历史属于另一个用户
- **WHEN** 相同钉钉企业和外部主体存在属于另一个用户的 `unbound` 历史身份
- **THEN** 系统 MUST 保留原人员历史归属并拒绝转移

### Requirement: 外部身份状态与ONES凭据状态分别治理
系统 SHALL 在 `user_external_identity` 上保存 `enabled`、`disabled` 或 `unbound` 状态、revision 与 `verified_at`，并结合内部用户状态以及 provider 所需的当前上下文判断身份是否可用。ONES 个人 Credential SHALL 使用独立生命周期状态；系统不得声称当前存在通用 pending/conflict/revoked Claim 状态机或 Connection 状态机。ONES `unbound` SHALL 是已结束的历史绑定周期，不得重新获得当前 Credential。

#### Scenario: enabled身份
- **WHEN** 内部用户启用、外部身份为 enabled 且 provider 所需前置条件有效
- **THEN** 系统可以把该身份用于对应受控主体解析

#### Scenario: 身份被禁用
- **WHEN** 外部身份状态为 disabled
- **THEN** 该身份停止解析新请求但仍保留当前主体归属
- **AND** 其它用户不得绑定同一当前外部主体

#### Scenario: ONES身份被解绑
- **WHEN** ONES 外部身份状态变为 unbound
- **THEN** 该身份停止解析新请求并释放当前主体归属
- **AND** 身份历史、原内部用户和其它外部身份不受影响

#### Scenario: ONES Credential不可用
- **WHEN** ONES 身份 enabled 但个人 Credential 非 active
- **THEN** 身份事实仍可查询但 ONES Tool 调用失败关闭

### Requirement: 冲突处理不得一键强制转移身份
系统 MUST 依赖 provider、tenant 与 subject 的当前身份唯一约束阻止外部主体跨用户覆盖。当前 ONES 用户更换自己的账号时，系统 SHALL 要求新登录验证和显式 `replace_existing` 确认，并在一个事务中软解绑该用户旧身份与 Credential 后保存新绑定；系统不得提供管理员一键绕过唯一约束的强制转移命令。已 `unbound` 的 ONES 历史身份不构成强制转移，新的本人验证绑定 MUST 创建新身份记录。

#### Scenario: 外部主体当前属于另一个用户
- **WHEN** 新绑定命中已属于其它内部用户的 `enabled` 或 `disabled` 当前外部主体
- **THEN** 系统拒绝绑定并保留原身份

#### Scenario: 本人换绑另一个ONES主体
- **WHEN** 用户完成新主体验证但未显式确认替换
- **THEN** 系统返回稳定的换绑确认要求且不改变当前身份

#### Scenario: 本人确认换绑
- **WHEN** 同一用户提交有效 Challenge 并显式确认替换当前 ONES 身份
- **THEN** 系统原子软解绑旧身份和 Credential 并保存新身份与 Credential

#### Scenario: 两个用户并发绑定已释放ONES主体
- **WHEN** 两个内部用户分别完成验证并并发确认同一只有 `unbound` 历史的 ONES 主体
- **THEN** 系统 MUST 只创建一个 `enabled` 当前身份
- **AND** 失败方收到安全的身份冲突，且不得留下活动 Credential 或部分绑定数据
