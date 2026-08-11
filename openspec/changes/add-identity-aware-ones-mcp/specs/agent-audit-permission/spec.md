## ADDED Requirements

### Requirement: Principal JWT生命周期必须安全审计
系统 SHALL 审计 Principal JWT 的签发成功、签发拒绝和 MCP 验证拒绝，记录 issuer、kid、audience、scope 摘要、jti、Job、actor、结果和安全错误码；MUST NOT 保存 JWT 原文、签名、Authorization Header 或私钥材料。

#### Scenario: JWT签发成功
- **WHEN** Identity Service 为运行 Job 签发 `aud=ones-mcp` 的短期 JWT
- **THEN** 审计记录 Job、actor、audience、scope hash、kid、jti 和过期时间，不记录 Token 原文

#### Scenario: JWT验证失败
- **WHEN** ONES MCP 收到伪造、过期、错误 audience 或未知 kid 的 JWT
- **THEN** 审计记录稳定拒绝分类且不读取/记录 Provider credential

### Requirement: ONES MCP查询与Provider尝试必须关联审计
系统 SHALL 把 Agent Tool Call、MCP 操作、Provider 查询 attempt 和可选 Token refresh 使用 correlation ID、Job、session、principal jti、actor、external identity、Team 和 credential revision 串联。

#### Scenario: 查询首次成功
- **WHEN** ONES 查询第一次 Provider attempt 成功
- **THEN** 审计链包含 Tool、业务安全请求摘要、Provider attempt、响应数量/截断摘要、耗时和最终状态

#### Scenario: 401刷新后成功
- **WHEN** 首次查询401、自动登录成功且重试查询成功
- **THEN** 审计链记录两个查询 attempt、一次 credential refresh、revision 变化和最终成功，不记录登录材料或 Token

### Requirement: ONES身份和凭据审计不得泄漏秘密
本人绑定、重验、解绑、管理员停用、自动 Token refresh 和 REAUTH_REQUIRED 事件 MUST 只保存内部 actor、identity/credential ID、revision、Team 安全标识、状态、时间和错误码；邮箱、密码、Token、密文、nonce、JWKS 私钥和原始 Provider 正文 MUST 被排除。

#### Scenario: 扫描绑定与刷新审计
- **WHEN** 测试完成成功绑定、查询、Token 刷新和刷新失败
- **THEN** 所有 `audit_event`、`agent_tool_call`、`mcp_operation_audit`、Runtime event 和日志均不包含已知测试邮箱、密码、Token 或 Principal JWT
