## ADDED Requirements

### Requirement: Principal JWT生命周期必须安全审计
系统 SHALL 审计 Principal JWT 的签发成功、签发拒绝和 MCP 验证拒绝，记录 issuer、kid、audience、完整 scope、jti、Job、actor、结果和安全错误码；MUST NOT 保存 JWT 原文、签名、Authorization Header 或私钥材料。

#### Scenario: JWT签发成功
- **WHEN** Identity Service 为运行 Job 签发 `aud=ones-mcp` 的短期 JWT
- **THEN** 审计记录 Job、actor、audience、完整 scope、kid、jti 和过期时间，不记录 JWT 原文

#### Scenario: JWT验证失败
- **WHEN** ONES MCP 收到伪造、过期、错误 audience 或未知 kid 的 JWT
- **THEN** 审计记录稳定拒绝分类且不读取/记录 Provider credential

### Requirement: ONES MCP查询与Provider尝试必须关联审计
系统 SHALL 把 Agent Tool Call、MCP 操作、Provider 查询 attempt 和可选 Token refresh 使用 correlation ID、Job、session、principal jti、actor、external identity、Team 和 credential revision 串联。

#### Scenario: 查询首次成功
- **WHEN** ONES 查询第一次 Provider attempt 成功
- **THEN** 审计链包含 Tool、完整有界业务请求、Provider attempt、完整有界业务响应、耗时和最终状态

#### Scenario: 401刷新后成功
- **WHEN** 首次查询401、自动登录成功且重试查询成功
- **THEN** 审计链记录两个查询 attempt、一次 credential refresh、revision 变化和最终成功，不记录登录材料或 Token

### Requirement: ONES身份审计保留原始身份字段但不得泄漏认证秘密
本人绑定、重验、解绑、管理员停用、自动 Token refresh 和 REAUTH_REQUIRED 事件 SHALL 原样保存内部 actor、ONES 邮箱/User ID、identity/credential ID、revision、Team 标识、状态、时间和错误码；密码、Token、Principal JWT、Authorization/Cookie、密文、nonce、JWKS 私钥和 Provider 认证请求/响应原文 MUST 被排除。

#### Scenario: 扫描绑定与刷新审计
- **WHEN** 测试完成成功绑定、查询、Token 刷新和刷新失败
- **THEN** `audit_event` 和 `mcp_operation_audit` 包含预期邮箱/User ID 与完整有界查询业务载荷，所有审计、Runtime event 和日志均不包含已知测试密码、Token、Principal JWT、Authorization/Cookie、密文或 nonce
