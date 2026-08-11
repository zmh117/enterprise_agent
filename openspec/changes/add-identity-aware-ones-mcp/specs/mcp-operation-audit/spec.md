## ADDED Requirements

### Requirement: MCP操作审计必须关联完整平台Principal
系统 SHALL 为每次 `ones-mcp` Tool 与 Provider 尝试记录 correlation ID、Job、session、JWT `jti`、系统用户、外部身份、Team、server、Tool、operation、credential revision、attempt、status、error code、duration 和时间。

#### Scenario: 查询一次成功
- **WHEN** ONES 查询首次请求成功
- **THEN** 审计可从 Agent Tool Call 关联到唯一 MCP 操作和 Provider attempt

#### Scenario: 401刷新后成功
- **WHEN** 首次 Provider attempt 返回401、登录刷新成功且第二次查询成功
- **THEN** 审计记录各阶段的安全状态、attempt 和最终结果，并使用同一 correlation/Job/principal 链接

### Requirement: MCP审计只保存业务安全摘要
查询请求摘要 SHALL 只保存 keyword hash/长度、issue type 和 limit；响应摘要 SHALL 只保存返回数量、total 和 truncated。审计 MUST NOT 保存 JWT、Authorization Header、邮箱、密码、Token、GraphQL document、原始请求/响应或完整工作项正文。

#### Scenario: 外部结果包含敏感字段
- **WHEN** ONES 原始响应包含 Token、邮箱或额外未声明字段
- **THEN** MCP 输出规范化器和审计摘要均丢弃这些字段

#### Scenario: 错误正文包含Token
- **WHEN** Provider 错误正文回显认证材料
- **THEN** 审计只保存稳定错误码和有界安全分类

### Requirement: 凭据生命周期操作必须审计
系统 SHALL 审计本人绑定确认、重验、Token refresh、`REAUTH_REQUIRED`、停用和解绑，记录 actor、identity、credential revision、结果和安全原因；不得记录可重放材料。

#### Scenario: 本人确认绑定
- **WHEN** 用户确认已验证 challenge 和默认 Team
- **THEN** 审计记录身份与 credential revision 已创建，不记录 challenge 密文或登录材料

#### Scenario: 自动刷新失败
- **WHEN** 401 后重新登录失败
- **THEN** 审计记录凭据状态转为 `REAUTH_REQUIRED` 和安全错误码

### Requirement: 审计写入失败必须失败关闭
当系统无法持久化要求的 MCP 操作审计时，MCP SHALL 返回安全失败，且不得把未审计的 Provider 成功结果交给 Agent。

#### Scenario: 审计数据库不可用
- **WHEN** ONES Provider 已返回结果但 MCP 操作审计提交失败
- **THEN** Tool 返回 `mcp_audit_unavailable` 安全错误且日志不包含原始结果或凭据
