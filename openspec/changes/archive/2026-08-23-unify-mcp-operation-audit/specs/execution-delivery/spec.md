## ADDED Requirements

### Requirement: Agent Tool Call 必须按真实来源分类
系统 SHALL 使用 `agent_tool_call` 保存 Runtime 观察到的每次逻辑 Tool Call，并以 `tool_origin` 明确区分 `mcp`、`sdk_builtin`、`sdk_custom` 与 `unknown`。只有与当前 Job 冻结 MCP Binding 精确匹配的调用才能保存非空 `server_code` 和 `mcp_call_id`；系统 MUST NOT 将未知或 SDK 原生 Tool 默认归类为 `tool-mcp`、`ones-mcp` 或其它 MCP Server。

#### Scenario: Python Runtime 捕获未知 SDK Tool
- **WHEN** Python Runtime 从 SDK 消息中捕获到无法匹配 MCP Binding、SDK 内置目录或平台注册目录的 Tool Use
- **THEN** Runtime 以 `tool_origin=unknown`、空 `server_code` 产生有界 Tool Event，并由 Worker 保存一条 `agent_tool_call`
- **AND** 系统不得为该事件创建 `mcp_operation_audit`

#### Scenario: SDK 内置工具被 Runtime 拒绝
- **WHEN** Python 或 TypeScript Runtime 拒绝一个未获 Job 授权的 SDK 内置 Tool
- **THEN** Runtime 保存 `tool_origin=sdk_builtin`、`status=DENIED` 和稳定拒绝码，且 `server_code` 与 `mcp_call_id` 为空

#### Scenario: MCP Tool 与冻结 Binding 精确匹配
- **WHEN** Runtime Tool 名称、Server alias 与当前 Job 冻结的 MCP Tool Binding 精确匹配
- **THEN** Tool Event 使用 `tool_origin=mcp` 并保存该 Binding 的真实 `server_code`

### Requirement: 一个 SDK Tool Use 只能形成一条 Agent Tool Call
系统 SHALL 使用 `invocation_id + runtime_tool_call_id` 聚合 `STARTED` 与终态 Tool Event，并为一次逻辑 SDK Tool Use 只保留一条 `agent_tool_call`。重复事件、Runtime 重连、终态恢复或 Worker 重试 MUST 幂等更新同一行，不得按状态、请求摘要或工具名称创建重复事实。

#### Scenario: STARTED 后收到成功终态
- **WHEN** 相同 invocation 和 SDK Tool Use ID 先产生 `STARTED`，随后产生 `SUCCEEDED`
- **THEN** 系统将同一 `agent_tool_call` 更新为成功、最终耗时和有界响应摘要

#### Scenario: Runtime 在终态前失败
- **WHEN** Runtime 已产生 `STARTED` Tool Event 后超时、断连或失败
- **THEN** 系统保留该 Tool Call，并以稳定失败状态结束或标记为未完成证据，不得丢失或复制该调用

### Requirement: MCP 执行审计必须与 Agent Tool Call 精确关联
每次进入平台 MCP Server 的有效 Job-bound Tool Call SHALL 由 MCP Server 分配唯一 `mcp_call_id`，并将对应的 `agent_tool_call.id` 与所有 `mcp_operation_audit` 事件精确关联。MCP Server MUST 通过标准 MCP `CallToolResult._meta` 返回非敏感关联标识，Runtime SHALL 将其与真实 SDK Tool Use ID 一并回传，Worker MUST 幂等补全关联。

#### Scenario: 相同 Job 连续调用同一工具
- **WHEN** 一个 Job 多次调用同一个 MCP Tool
- **THEN** 每次调用具有不同 `mcp_call_id`，且各自的 Agent Tool Call 只关联本次 MCP 审计事件

#### Scenario: 同一工具并发调用
- **WHEN** Runtime 并发发起名称相同但参数不同的 MCP Tool Call
- **THEN** 系统通过 `mcp_call_id` 与 SDK Tool Use ID 精确关联，不按 `job_id + tool_name`、时间顺序或载荷相似度猜测

#### Scenario: MCP 元数据未能传播
- **WHEN** 固定版本的 Agent SDK 未把 MCP `CallToolResult._meta` 传播到 Runtime Tool Result
- **THEN** 兼容性验收失败，系统不得退回按工具名称批量关联或把未知调用伪装成已精确关联

### Requirement: Runtime Tool Event 协议必须支持来源与关联的受控升级
系统 SHALL 提供可验证的 Runtime 协议升级，使 Tool Event 携带 `tool_origin`、可空 `server_code`、SDK Tool Use ID、可空 `mcp_call_id` 与可空已持久化 Tool Call ID。升级期间 Worker MUST 兼容读取既有事件并仅依据 Job 冻结 Binding 纠正旧事件来源；MUST NOT 使用 `tool-mcp` 作为缺省来源。

#### Scenario: Worker 先于 Runtime 升级
- **WHEN** 新 Worker 接收到旧 Runtime 事件
- **THEN** Worker 以 Job 冻结 Binding 进行保守归类，无法唯一匹配时使用 `unknown` 和空 `server_code`

#### Scenario: 新 Runtime 事件到达旧 Worker
- **WHEN** 部署顺序可能让新 Runtime 先于支持新字段的 Worker 接流量
- **THEN** 发布门禁阻止该顺序，避免严格协议校验拒绝事件或丢失 Tool Call 事实

### Requirement: Agent Tool Call 与 MCP 详细审计具有不同保留周期
`agent_tool_call` SHALL 跟随 Job 审计生命周期保留安全摘要；`mcp_operation_audit` SHALL 按配置保留详细 MCP 执行证据。清理 MCP 详细审计 MUST NOT 删除或破坏 Agent Tool Call、Job 历史和 SDK 原生 Tool 事实。

#### Scenario: MCP 审计超过保留期
- **WHEN** `mcp_operation_audit` 事件超过配置保留天数
- **THEN** 系统可删除该详细事件，但关联的 `agent_tool_call` 与其安全摘要保持可查询

