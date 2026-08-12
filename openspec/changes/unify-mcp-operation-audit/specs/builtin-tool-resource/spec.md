## ADDED Requirements

### Requirement: tool-mcp 必须写入通用 MCP 操作审计
`tool-mcp` SHALL 对每次有效 Job-bound 调用写入通用 `mcp_operation_audit`，覆盖 Tool 生命周期、授权判定、资源解析与实际资源访问。审计 MUST 保存 `mcp_call_id`、Job/Session/Invocation、Agent/Application Publication、Tool identifier/schema hash、业务目标、实际 placement、Resource Revision、状态、稳定错误码、尝试次数、耗时以及有界业务请求和结果。

#### Scenario: 只读资源工具调用成功
- **WHEN** `tool-mcp` 完成数据库、Redis、Loki 或 Schema Tool 调用
- **THEN** 系统保存一条终态 `TOOL` 证据及适用的 `AUTHORIZATION`、`RESOURCE` 证据，并全部关联同一个 `mcp_call_id` 和 `agent_tool_call.id`

#### Scenario: 授权或资源解析被拒绝
- **WHEN** Job、角色数据范围、Tool Binding、Schema hash 或唯一资源解析校验失败
- **THEN** 系统保存 `DENIED` 审计、稳定错误码和安全目标摘要，不建立外部资源连接

#### Scenario: 调用相同工具使用不同资源版本
- **WHEN** 同一 Job 的两个 Tool Call 实际解析到不同允许的 Resource Revision
- **THEN** 每个 `mcp_call_id` 只记录本次解析的精确 Resource Revision，不从 Job 或上一调用复制旧版本

### Requirement: tool-mcp 审计必须先于受治理外部访问并失败关闭
`tool-mcp` MUST 在访问数据库、Redis、Loki 或其它受治理资源前创建 MCP Tool Call 根事实与必需审计上下文。若必需的 Agent Tool Call 或 MCP 审计无法持久化，调用 SHALL 以 `mcp_audit_unavailable` 或等价稳定配置错误失败，且不得继续外部访问。

#### Scenario: 审计数据库不可用
- **WHEN** `tool-mcp` 无法创建本次调用的根审计事实
- **THEN** Tool Call 失败关闭并且资源客户端未被调用

### Requirement: tool-mcp 必须通过 MCP 元数据返回精确关联标识
`tool-mcp` SHALL 在成功、失败和业务拒绝的 `CallToolResult._meta` 中返回平台命名空间下的 `mcp_call_id` 与 `agent_tool_call_id`。这些字段 MUST 不进入模型可见业务正文、Tool Schema 或用户输入，并 MUST NOT 接受 Agent 提供的同名值覆盖。

#### Scenario: Runtime 收到 tool-mcp 结果
- **WHEN** `tool-mcp` 返回 Tool Result
- **THEN** Runtime 可从 `_meta` 取得服务端生成的关联标识，并从模型可见结果中排除这些平台内部字段

### Requirement: 通用 MCP 业务审计保留有界原文但排除认证材料
经授权的 `tool-mcp` 审计 SHALL 在配置大小边界内保留完整业务参数与业务结果，不要求对普通业务字段做脱敏；但 MUST 结构性拒绝或排除密码、Token、Cookie、Authorization Header、连接 Secret、密文、私钥及其它认证材料。

#### Scenario: 业务查询包含普通筛选条件
- **WHEN** Tool Call 参数包含环境、库表、只读 SQL、Key 前缀或 Loki Selector 等授权业务字段
- **THEN** 审计在大小边界内保留这些字段供追溯

#### Scenario: 载荷疑似包含认证字段
- **WHEN** 请求、资源结果或异常中出现认证材料字段
- **THEN** 审计写入拒绝该字段或整个非法载荷，并且不会持久化认证材料

