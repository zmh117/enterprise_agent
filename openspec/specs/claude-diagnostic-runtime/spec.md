# claude-diagnostic-runtime Specification

## Purpose
TBD - created by archiving change add-readonly-diagnostic-agent-mvp. Update Purpose after archive.
## Requirements
### Requirement: AgentExecutor runs persisted diagnostic jobs
The system SHALL provide an AgentExecutor that accepts an Agent job identifier, loads persisted job context, executes the read-only diagnostic workflow, records execution output, and updates job status.

#### Scenario: Worker executes pending job
- **WHEN** the worker passes a valid PENDING job identifier to AgentExecutor
- **THEN** AgentExecutor loads the job, marks it RUNNING, invokes the diagnostic runtime, records the final result, and marks the job SUCCEEDED or FAILED

### Requirement: Claude Code Agent SDK is wrapped behind a client
The system SHALL isolate Claude Agent SDK usage behind a ClaudeCodeAgentClient contract so domain and application services do not depend on concrete SDK APIs. When `FEATURE_REAL_CLAUDE=true`, the default injected implementation SHALL be `RealClaudeCodeAgentClient` backed by the Claude Agent SDK; otherwise the system SHALL use `StubClaudeCodeAgentClient`.

#### Scenario: AgentExecutor invokes Claude runtime
- **WHEN** AgentExecutor needs model execution
- **THEN** it calls ClaudeCodeAgentClient with structured prompt, context, skills, tool registry, and execution limits instead of using SDK APIs directly

#### Scenario: Real runtime uses the SDK internally
- **WHEN** `RealClaudeCodeAgentClient.run()` is invoked with a valid API key and CLI runtime
- **THEN** only the infrastructure client module calls Claude Agent SDK APIs and AgentExecutor remains unaware of SDK types

### Requirement: Agent context is constructed before model execution
The system SHALL construct an Agent execution context containing system role, safety rules, user question, source/project or service code, allowed tools, tool restrictions, skills, relevant retrieved context, and safe conversation summary.

#### Scenario: Diagnostic question is prepared
- **WHEN** AgentExecutor prepares a job for Claude execution
- **THEN** AgentContextBuilder returns a context that includes read-only safety rules and excludes unrelated full ER/business-flow exports

### Requirement: Skills are loaded as explicit diagnostic workflows
The system SHALL load only configured diagnostic Skills for MVP, including bug analysis, SQL diagnosis, Redis diagnosis, and Loki log analysis. The real runtime SHALL inject loaded skill guidance into the SDK system prompt (or equivalent settings) so the agent follows the configured diagnostic workflows.

#### Scenario: Skills are registered
- **WHEN** the Agent runtime starts a diagnostic job
- **THEN** it registers the configured Skills with ClaudeCodeAgentClient and makes their workflow guidance available to the Agent

### Requirement: Runtime exposes only read-only tools
The system SHALL register only read-only tools for MVP Agent execution. During real runtime execution, the six MVP read-only tools SHALL be exposed exclusively through the in-process SDK MCP server bridging `ToolRegistry`, and built-in mutating SDK tools SHALL remain unavailable or denied.

#### Scenario: Agent asks for a mutating tool
- **WHEN** the Claude runtime attempts to call a tool for code modification, database update, Redis deletion, restart, deployment, pull request creation, or sandbox execution
- **THEN** the system rejects the tool call because that tool is not registered or is denied for MVP execution

#### Scenario: Registered tool is executed through internal platform
- **WHEN** Claude invokes `mcp__internal__query_loki` during real runtime execution
- **THEN** the call flows through `ToolRegistry` to `ReadOnlyToolService` and internal API client contracts

### Requirement: Final reports are evidence based
The system SHALL require Agent final answers to include a conclusion, evidence summary, uncertainty or limitations when applicable, and suggested safe next actions. Real runtime prompts SHALL instruct the model to follow this report structure using tool evidence gathered during the job.

#### Scenario: Agent completes order diagnosis
- **WHEN** the Agent finishes investigating a business question such as an order stuck in a status
- **THEN** the final report includes the likely cause, relevant log/database/Redis/ER/business-flow evidence, uncertainty if evidence is incomplete, and non-mutating recommendations

### Requirement: Private model reasoning is not persisted
The system SHALL persist user-visible execution steps and evidence summaries, not private model chain-of-thought. `AgentExecutor` SHALL persist tool call summaries from `AgentRunResult.tool_events` and SHALL NOT persist raw SDK thinking blocks or hidden reasoning content.

#### Scenario: Agent records progress
- **WHEN** the Agent reasons internally during diagnosis
- **THEN** the system persists only safe step summaries, tool calls, tool results, artifacts, and final answer content

#### Scenario: Tool events are persisted after real execution
- **WHEN** `RealClaudeCodeAgentClient` returns tool events for a completed job
- **THEN** `AgentExecutor` writes corresponding `agent_tool_call` rows with desensitized summaries

### Requirement: AgentExecutor records Claude tool loop progress
The system SHALL add execution steps when the real runtime starts, completes context preparation, and finishes model execution, so operators can inspect job progress through the debug API.

#### Scenario: Real runtime adds completion step
- **WHEN** the real runtime returns a final answer
- **THEN** AgentExecutor records a step indicating model execution completed before saving the result

### Requirement: 诊断上下文必须包含目标 schema 目录
系统 SHALL 在诊断上下文中提供目标 environment/base/workshop 可访问的 schema 目录或明确说明无法唯一解析目标。schema 目录 MUST 来自 Internal API Platform，只包含按权限和 topology 过滤后的表、列和非密钥元数据。

#### Scenario: 单一目标问题预取 schema
- **WHEN** 用户问题能从 addressing 目录唯一解析到一个 partitioned workshop
- **THEN** Agent context 包含该 workshop 的 schema 目录摘要，供模型生成 SQL 前检查可用表和字段

#### Scenario: 目标不明确时不猜 schema
- **WHEN** 用户问题不能唯一解析 environment/base/workshop
- **THEN** Agent context 要求模型先解析目标或报告目标不明确，不得猜测不存在于 addressing 目录的目标代码

### Requirement: 诊断运行时必须停止缺证据试错
系统 SHALL 指示真实模型在 schema 不足、表不存在、字段不存在、连续策略拒绝、空结果无法支撑结论或关键业务字段缺失时停止扩散式工具试错，并输出“不具备诊断证据”的报告。最终报告 MUST 明确列出已经验证的限制条件和安全下一步。

#### Scenario: schema 中没有订单表或订单字段
- **WHEN** schema 目录不包含可用于按订单号查询的表或字段
- **THEN** Agent 不得继续猜测 `mo`、`order`、`production_order` 等未列出的表名，并必须报告当前数据结构不足以诊断该订单

#### Scenario: 工具连续返回结构化拒绝
- **WHEN** 数据库工具连续返回表不存在、字段不存在、跨 workshop、非 SELECT 或 schema 不可用等结构化拒绝
- **THEN** Agent 必须停止新的相邻表名尝试，并产出证据不足报告

#### Scenario: 缺证据报告仍遵循只读诊断格式
- **WHEN** Agent 因缺少可用证据而停止
- **THEN** 最终报告包含结论、已验证证据、限制/不确定性和非变更类下一步，不建议 Agent 执行写操作或自动修复

