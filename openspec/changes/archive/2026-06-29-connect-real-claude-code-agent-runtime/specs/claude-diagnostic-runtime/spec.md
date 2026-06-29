## MODIFIED Requirements

### Requirement: Claude Code Agent SDK is wrapped behind a client
The system SHALL isolate Claude Agent SDK usage behind a ClaudeCodeAgentClient contract so domain and application services do not depend on concrete SDK APIs. When `FEATURE_REAL_CLAUDE=true`, the default injected implementation SHALL be `RealClaudeCodeAgentClient` backed by the Claude Agent SDK; otherwise the system SHALL use `StubClaudeCodeAgentClient`.

#### Scenario: AgentExecutor invokes Claude runtime
- **WHEN** AgentExecutor needs model execution
- **THEN** it calls ClaudeCodeAgentClient with structured prompt, context, skills, tool registry, and execution limits instead of using SDK APIs directly

#### Scenario: Real runtime uses the SDK internally
- **WHEN** `RealClaudeCodeAgentClient.run()` is invoked with a valid API key and CLI runtime
- **THEN** only the infrastructure client module calls Claude Agent SDK APIs and AgentExecutor remains unaware of SDK types

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

## ADDED Requirements

### Requirement: AgentExecutor records Claude tool loop progress
The system SHALL add execution steps when the real runtime starts, completes context preparation, and finishes model execution, so operators can inspect job progress through the debug API.

#### Scenario: Real runtime adds completion step
- **WHEN** the real runtime returns a final answer
- **THEN** AgentExecutor records a step indicating model execution completed before saving the result
