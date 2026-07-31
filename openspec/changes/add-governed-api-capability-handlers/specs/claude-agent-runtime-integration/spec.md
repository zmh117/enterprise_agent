## MODIFIED Requirements

### Requirement: Read-only tools are exposed only through an in-process SDK MCP server
The system SHALL expose MVP internal read-only tools and governed external API QUERY Capabilities to the SDK through in-process SDK MCP servers registered via `ClaudeAgentOptions.mcp_servers`. Internal tools SHALL continue to execute through `ToolRegistry` with the current job context; governed Capabilities SHALL execute through the governed Capability resolver/executor with the frozen job, Agent Publication, Application Publication and subject context.

#### Scenario: Model calls a registered read-only tool
- **WHEN** Claude calls `mcp__internal__query_database` with valid read-only arguments
- **THEN** the runtime routes the call through `ToolRegistry` to `ReadOnlyToolService` and returns the tool result to the model

#### Scenario: Model calls a governed Capability
- **WHEN** Claude calls an exposed `cap__ones__work_item__search` with valid public input
- **THEN** the runtime routes the call through the governed Capability executor and not through an arbitrary web fetch or model-provided URL

#### Scenario: Tool context is bound per job
- **WHEN** two different jobs run through the real runtime
- **THEN** each job's internal and governed Tool invocations use that job's own identifiers, frozen publications and requester context and do not leak context between jobs

### Requirement: Built-in mutating tools are disabled
The system SHALL prevent the SDK's built-in mutating tools such as Bash, Write, Edit, file modification, deployment or web fetch from being available or approved. The system SHALL auto-approve only the exact internal read-only and governed `cap__*` QUERY tools resolved for the current Job; it SHALL deny all other tools through `allowed_tools`, `disallowed_tools`, `permission_mode`, or `can_use_tool`.

#### Scenario: Model attempts a built-in write tool
- **WHEN** the SDK runtime would otherwise allow a built-in Bash, Write, or Edit tool
- **THEN** the tool is not available or its call is denied, so no mutation can occur

#### Scenario: Only current governed set is auto-approved
- **WHEN** the Agent runs a Job whose Application Allowlist includes one Capability Release
- **THEN** only existing permitted internal tools and that exact resolved `cap__*` Tool are pre-approved, while other Capability names and generic web fetch remain denied

#### Scenario: Application has no Capability
- **WHEN** the frozen Application Capability Allowlist is empty
- **THEN** no `cap__*` Tool is registered or auto-approved and existing internal Tool behavior remains unchanged

### Requirement: Tool events are returned without private reasoning
The system SHALL populate `AgentRunResult.tool_events` with safe summaries of each internal or governed Tool invocation, attempt outcome, result size and applicable Capability Release/classification provenance, excluding raw secrets, authentication material, raw HTTP bodies, full unbounded payloads and private model chain-of-thought including SDK thinking blocks.

#### Scenario: Successful tool loop produces events
- **WHEN** the real runtime completes after one or more internal or governed Tool calls
- **THEN** `AgentRunResult` includes ordered safe Tool event summaries suitable for persistence in `agent_tool_call`

#### Scenario: Governed call fails after HTTP attempts
- **WHEN** a QUERY Capability exhausts its allowed attempts
- **THEN** the event summary includes safe classification and attempt count without including external body, Token or authentication Header

## ADDED Requirements

### Requirement: 模型可以组合公开的 Capability 输入输出
Claude Tool循环 SHALL 能读取一个受治理Capability的规范化公开输出，并依据后续Capability的公开Input Schema组织新的结构化调用；每次调用必须独立经过当前Job的Tool可见性与执行校验，运行时不得创建隐式服务端Handler流水线。

#### Scenario: 顺序调用两个测试 Capability
- **WHEN** 模型使用第一个Tool的规范化字段构造第二个Tool输入
- **THEN** SDK循环执行两个独立Tool调用并分别产生安全Tool事件

#### Scenario: 后续 Tool 不在当前目录
- **WHEN** 模型尝试根据文本调用未注册的 `cap__*` Tool
- **THEN** SDK权限策略拒绝该调用且不发起外部请求

### Requirement: 外部规范化文本不得提升为指令
运行时 MUST 将受治理 Capability 的字符串输出标记和封装为不可信业务数据，不得把它拼接进 system/developer/Tool定义或据此修改 `allowed_tools` 和权限策略。

#### Scenario: Tool 输出包含提示注入
- **WHEN** 外部字段内容声称自己是系统指令或要求调用被禁用Tool
- **THEN** 内容保持普通Tool数据，系统提示、Tool集合和权限不发生变化
