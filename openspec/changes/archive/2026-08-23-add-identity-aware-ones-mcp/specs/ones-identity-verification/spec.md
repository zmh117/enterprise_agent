## REMOVED Requirements

### Requirement: ONES验证材料只存在于单次请求内
**Reason**: 第一阶段查询需要在 Token 失效后自动重新登录，因此必须保留加密登录材料与 Token。

**Migration**: 明文仍只存在于当前请求；验证材料改为 challenge 和 current credential 中的 AES-GCM 密文，公开 API、日志、审计和浏览器存储继续禁止任何可重放材料。

## ADDED Requirements

### Requirement: ONES验证材料必须以加密Challenge转交
ONES Adapter SHALL 返回严格规范化的主体、Team 和 Token；Identity Service MUST 在同一请求内把邮箱、密码和 Token 加密写入短期 challenge，且公开 challenge 投影只包含主体、Team、验证时间、过期时间和状态。

#### Scenario: 验证成功
- **WHEN** ONES 返回包含用户 UUID、Token 和 Team 的合法响应
- **THEN** 系统创建不回显秘密的加密 challenge，等待用户选择默认 Team

#### Scenario: 验证失败
- **WHEN** ONES 拒绝邮箱/密码或响应不合法
- **THEN** 系统不创建 challenge credential、当前 credential 或身份，并返回统一安全错误

#### Scenario: 运行日志扫描
- **WHEN** 成功或失败验证完成
- **THEN** 日志只包含 correlation ID、Provider instance、actor、outcome 和安全错误码
- **AND** 不包含请求体、响应体、邮箱、密码或 Token

### Requirement: ONES凭据确认必须原子且可重验
确认 challenge 时，系统 SHALL 在一个事务中消费 challenge、创建或更新 ONES 身份、选择已验证 Team、创建或轮换 current credential 并记录审计；同一 ONES subject 的重验 MUST 增加 credential revision。

#### Scenario: 首次确认
- **WHEN** 用户确认有效 challenge 中的 Team
- **THEN** 系统创建启用身份与 revision 1 的 ACTIVE credential

#### Scenario: 同一用户重验
- **WHEN** 已绑定用户再次验证同一 ONES subject
- **THEN** 系统更新允许的身份事实、轮换 credential 并使旧密文版本不可用

#### Scenario: 换绑其它subject
- **WHEN** 验证返回与当前绑定不同的 subject
- **THEN** 系统要求显式换绑确认，并在成功后使旧 identity credential 失效

### Requirement: ONES Token必须支持安全自动刷新
运行时 SHALL 在 ONES 查询首次返回401后使用当前 ACTIVE credential 的加密邮箱/密码重新登录，校验 subject 和 Team 后条件更新 Token；原调用最多重试一次。

#### Scenario: 自动刷新成功
- **WHEN** 旧 Token 失效但登录材料有效且 subject/Team 未变化
- **THEN** 系统更新 Token 密文、credential revision 和刷新时间，并重试一次查询

#### Scenario: 自动刷新失败
- **WHEN** 登录失败、subject 改变、Team 消失或重试仍401
- **THEN** 系统把 credential 标记为 REAUTH_REQUIRED、停止重试并要求用户本人重新验证

#### Scenario: 并发刷新
- **WHEN** 多个请求同时发现同一 credential Token 失效
- **THEN** 系统以进程锁和 revision 条件更新收敛到最新 Token，不用旧 revision 覆盖新值
