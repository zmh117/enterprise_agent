## ADDED Requirements

### Requirement: app_user 必须是跨 Web、钉钉和 MCP 的唯一权限主体
系统 MUST 以 `app_user.id` 作为登录、RBAC、Job、MCP Token 和审计中的唯一内部主体；钉钉身份与 ONES 身份 MUST 作为独立外部身份引用同一 `app_user`，不得直接互相绑定或替代内部主体。

#### Scenario: 同一人员从 Web 和钉钉发起请求
- **WHEN** 已绑定人员分别从 Web Session 和受信钉钉消息创建 Job
- **THEN** 两个 Job 使用同一 `app_user.id` 执行授权，同时保留各自入口身份来源审计

### Requirement: 外部身份不得通过可变资料自动合并
钉钉身份 MUST 以企业和外部 subject 为稳定唯一键，ONES 身份 MUST 以 ONES 实例和验证返回的 user UUID 为稳定唯一键；邮箱、手机号、用户名、昵称和显示名称 MUST NOT 用于自动合并内部用户或外部身份。

#### Scenario: 钉钉与 ONES 邮箱相同
- **WHEN** 两个外部账号展示相同邮箱或名称但尚未完成本人绑定
- **THEN** 系统不自动合并，仍要求受信 Challenge 将二者关联到当前 `app_user`

#### Scenario: 外部主体已属于其他用户
- **WHEN** 当前用户尝试绑定已由另一 `app_user` 占用的稳定外部主体
- **THEN** 系统返回冲突并保留原归属，不提供一键强制转移

### Requirement: 钉钉身份必须通过本人 Challenge 绑定
已登录用户 MUST 生成短时单次绑定码，并从自己的钉钉身份向受信机器人发送该绑定码；系统 MUST 从受信消息事件解析企业和外部 subject，在验证绑定码属于当前登录用户后建立绑定。

#### Scenario: 本人完成钉钉绑定
- **WHEN** 当前登录用户生成有效绑定码并从未绑定钉钉账号发送该码
- **THEN** 系统将受信事件中的钉钉身份绑定到当前 `app_user`，消费绑定码并记录审计

#### Scenario: 绑定码过期或被重复使用
- **WHEN** 钉钉消息包含过期、已消费或属于其他用户的绑定码
- **THEN** 系统拒绝绑定且不泄露目标用户信息

### Requirement: ONES 身份与凭据必须通过本人两阶段验证绑定
已登录用户 MUST 通过 HTTPS 提交邮箱和密码，由服务端登录受信 ONES 实例并创建短时单次 Challenge；密码 MUST 在单次请求结束前丢弃，Challenge 响应 MUST 只包含安全的 User/Team 候选，确认阶段 MUST 只允许选择候选中的默认 Team。

#### Scenario: ONES 本人验证成功
- **WHEN** 当前用户提交有效邮箱密码并确认候选集合中的默认 Team
- **THEN** 系统原子保存 ONES Identity、已验证 Team、默认 Team和加密 Token，并消费 Challenge

#### Scenario: 管理员代用户输入密码
- **WHEN** 管理员尝试为其他用户提交 ONES 邮箱密码或确认 Challenge
- **THEN** 系统拒绝操作；管理员只能查看、禁用或解绑状态

### Requirement: 第一阶段每个 Provider 实例只能有一个当前身份
系统 MUST 保证一个 `app_user` 在每个钉钉企业最多一个当前钉钉身份，在每个 ONES 实例最多一个当前 ONES 身份，并 MUST 保证同一外部主体在对应实例内只能属于一个 `app_user`。

#### Scenario: 用户重复绑定同一 ONES 主体
- **WHEN** 用户重新验证当前 ONES user UUID
- **THEN** 系统轮换当前凭据和验证事实而不是创建第二个当前身份

#### Scenario: 用户尝试换绑另一个 ONES 主体
- **WHEN** 用户已有当前 ONES 身份并验证得到不同 user UUID
- **THEN** 系统要求显式解绑或替换流程，不能静默覆盖当前主体

### Requirement: MCP 身份令牌与 Provider Token 必须分离
Agent Worker MUST 只获得平台 MCP Token；ONES MCP MUST 在服务端根据已验证 Principal 和 Job 快照解析加密个人 ONES Token。ONES Token、数据库密码、Redis 密码和 Loki Token MUST NOT 返回给 Agent Worker、模型、前端或 Tool 参数。

#### Scenario: ONES MCP 执行查询
- **WHEN** 合法 MCP Tool Call 到达 ONES MCP
- **THEN** Server 根据 `sub` 和 `job_id` 解密当前个人 Token 调用冻结默认 Team，Tool 参数和模型上下文均不含该 Token

### Requirement: Job 必须冻结主体范围并实时复核撤权
Job 创建时 MUST 冻结 ONES Identity、外部 user UUID、默认 Team和 binding revision；每次 Tool Call MUST 重新校验 `app_user`、身份、Team和凭据当前状态。Token 轮换 MAY 在主体和 Team 未变化时继续服务旧 Job，但身份换绑、Team 变化、解绑、禁用或凭据失效 MUST 阻止后续调用。

#### Scenario: Job 创建后只轮换 Token
- **WHEN** 用户轮换 Token但 ONES user UUID 和默认 Team 未变化
- **THEN** 后续 Tool Call 使用新 Token继续执行，并记录新 credential revision

#### Scenario: Job 创建后切换默认 Team
- **WHEN** 用户重新验证并选择不同默认 Team
- **THEN** 旧 Job 的后续 ONES Tool Call 因主体快照不再匹配而失败关闭

### Requirement: Provider 认证失败必须使用安全生命周期
ONES 返回 401 时，ONES MCP MUST 原子标记当前个人凭据为 `INVALID`，停止重试并返回重新验证提示；403 MUST 作为外部权限不足处理而不得错误使 Token 失效。任何错误记录 MUST 不包含 Token、邮箱、密码或原始响应。

#### Scenario: ONES 返回 401
- **WHEN** 当前个人 Token 被 ONES 拒绝为未认证
- **THEN** 系统标记凭据失效、停止该调用重试并要求本人重新验证

#### Scenario: ONES 返回 403
- **WHEN** ONES 已认证当前用户但拒绝访问目标数据
- **THEN** 系统保留凭据有效状态，返回安全权限不足结果并记录有界审计
