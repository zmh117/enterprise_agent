## ADDED Requirements

### Requirement: ones-mcp 必须使用通用 MCP 操作审计契约
身份感知的 `ones-mcp` SHALL 使用与其它平台 MCP Server 相同的 `mcp_call_id`、Agent Tool Call 和 `mcp_operation_audit` 契约，同时记录适用的 `TOOL`、`AUTHORIZATION`、`PROVIDER` 与 `CREDENTIAL` 证据。ONES 专用身份、Team、Credential Revision 与 Provider Attempt 必须作为可选扩展上下文，不得使通用审计字段依赖 ONES。

#### Scenario: ONES 查询成功
- **WHEN** 已绑定且已授权用户成功调用 `ones_work_item_search`
- **THEN** 系统保存一条 Agent Tool Call、同一 `mcp_call_id` 下的 TOOL 与 PROVIDER 证据，并精确关联真实 SDK Tool Use

#### Scenario: ONES 调用未进入 Provider
- **WHEN** Principal、身份绑定、默认 Team、Tool scope 或业务应用权限校验失败
- **THEN** 系统保存适用的拒绝证据且不创建伪造的 Provider 成功事件

#### Scenario: ONES Token 刷新后重试
- **WHEN** Provider 首次返回未授权并触发一次受控 Token 刷新和重试
- **THEN** CREDENTIAL 与两个 PROVIDER Attempt 共享同一 `mcp_call_id`，并记录各自状态、尝试次数和 Credential Revision

### Requirement: ONES MCP 关联标识不得来自 Principal 或 Agent 输入
`ones-mcp` SHALL 由服务端生成 `mcp_call_id` 和 `agent_tool_call_id`，并通过 MCP `CallToolResult._meta` 返回 Runtime。Principal JWT、Agent 参数和 Provider 响应中的同名字段 MUST NOT 被采用为平台关联标识。

#### Scenario: Agent 参数伪造关联标识
- **WHEN** Agent Tool Input 包含平台保留关联字段
- **THEN** Schema 或服务端拒绝该输入，并且不会关联或覆盖任何现有审计记录

### Requirement: ONES MCP 审计保留业务证据但隔离认证材料
`ones-mcp` SHALL 在授权读取与配置大小边界内保留 Tool 和 Provider 的业务请求、业务响应及错误证据；MUST NOT 保存 Principal JWT、ONES Token、密码、Authorization/Cookie Header、Credential 密文、Nonce 或私钥。管理员读取通用 MCP 审计仍 MUST 经过 `audit:*:read` 并记录读取审计。

#### Scenario: 管理员读取 ONES MCP 审计
- **WHEN** 具备 `audit:*:read` 的管理员查询 MCP 审计详情
- **THEN** 响应返回有界业务证据与关联标识，并记录本次读取行为

#### Scenario: 审计载荷包含 ONES Token
- **WHEN** Provider 请求、响应或异常对象中包含 Token 或认证 Header
- **THEN** 系统不得持久化该认证材料，且调用按安全审计策略失败或排除非法字段

