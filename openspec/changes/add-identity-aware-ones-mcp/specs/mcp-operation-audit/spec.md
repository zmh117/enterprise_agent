## ADDED Requirements

### Requirement: MCP操作审计必须关联完整平台Principal
系统 SHALL 为每次 `ones-mcp` Tool 与 Provider 尝试记录 correlation ID、Job、session、JWT `jti`、系统用户、外部身份、Team、server、Tool、operation、credential revision、attempt、status、error code、duration 和时间。

#### Scenario: 查询一次成功
- **WHEN** ONES 查询首次请求成功
- **THEN** 审计可从 Agent Tool Call 关联到唯一 MCP 操作和 Provider attempt

#### Scenario: 401刷新后成功
- **WHEN** 首次 Provider attempt 返回401、登录刷新成功且第二次查询成功
- **THEN** 审计记录各阶段的安全状态、attempt 和最终结果，并使用同一 correlation/Job/principal 链接

### Requirement: MCP审计必须原样保存完整有界业务载荷
系统 SHALL 原样保存每次查询的 Tool Input、固定 Provider GraphQL document 与 variables、Provider 业务响应和规范化 Tool Output，并记录载荷 schema version；不得对 keyword、ONES 邮箱/User ID、工作项字段或其它业务字段做 hash、掩码、摘要或字段裁剪。载荷 MUST 先通过 Tool/Provider 的 JSON schema、响应大小和数量上限，非法或超限正文不属于可持久化业务载荷。

#### Scenario: 查询成功
- **WHEN** ONES 查询在已配置大小上限内返回合法业务响应
- **THEN** 审计保存完整 Tool Input、GraphQL document/variables、Provider 业务响应和 Tool Output，可重建该次业务查询证据

#### Scenario: 业务字段包含邮箱和工作项内容
- **WHEN** 合法请求或响应包含 ONES 邮箱/User ID、keyword、工作项编号、名称、类型或其它 schema 内业务字段
- **THEN** 审计按原值保存这些字段，不做脱敏、摘要或 hash

### Requirement: 认证秘密必须在审计结构之外
密码、ONES Token、Principal JWT、Authorization/Cookie、私钥、密文和 nonce MUST NOT 进入 `audit_event`、`agent_tool_call`、`mcp_operation_audit` 或其请求/响应 JSON。Provider 认证 Header、登录请求/响应和 challenge/credential 密文 SHALL 使用独立内部对象，不得传给业务审计序列化器；登录与刷新审计只保存邮箱/User ID、identity/credential ID、revision、状态、时间和错误码。

#### Scenario: Provider业务响应意外包含认证字段
- **WHEN** Provider 业务响应包含 Token、Authorization、Cookie、password、ciphertext 或 nonce 字段
- **THEN** 系统拒绝把该正文认定为合法业务响应，记录稳定 schema/secret violation 错误且不持久化该正文

#### Scenario: Provider错误正文回显认证材料
- **WHEN** Provider 错误正文回显认证材料
- **THEN** 审计保存稳定错误码和非认证业务错误字段，但不保存可重放认证材料

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

### Requirement: 完整业务审计必须受读取权限和保留期约束
完整 MCP 业务审计详情 SHALL 只允许已认证且通过 `resource_type=audit, resource_code=*, action=read` 授权的调用方读取，并 SHALL 审计读取行为。部署 MUST 配置 `MCP_OPERATION_AUDIT_RETENTION_DAYS`；系统 MUST 定期删除超过保留期的 MCP 操作记录及其业务载荷，缺少或非法配置时 `ones-mcp` readiness MUST 失败。

#### Scenario: 无审计读取权限
- **WHEN** 已认证用户没有 `audit:*:read` 权限并请求 MCP 审计详情
- **THEN** 系统拒绝访问且不返回任何业务载荷

#### Scenario: 审计超过保留期
- **WHEN** MCP 操作记录早于配置的保留期截止时间
- **THEN** 保留期任务删除该操作记录及完整业务载荷，并记录清理计数审计
