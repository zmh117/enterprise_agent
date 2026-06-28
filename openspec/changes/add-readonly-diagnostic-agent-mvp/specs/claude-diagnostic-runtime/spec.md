## ADDED Requirements

### Requirement: AgentExecutor runs persisted diagnostic jobs
The system SHALL provide an AgentExecutor that accepts an Agent job identifier, loads persisted job context, executes the read-only diagnostic workflow, records execution output, and updates job status.

#### Scenario: Worker executes pending job
- **WHEN** the worker passes a valid PENDING job identifier to AgentExecutor
- **THEN** AgentExecutor loads the job, marks it RUNNING, invokes the diagnostic runtime, records the final result, and marks the job SUCCEEDED or FAILED

### Requirement: Claude Code Agent SDK is wrapped behind a client
The system SHALL isolate Python Claude Code Agent SDK usage behind a ClaudeCodeAgentClient contract so domain and application services do not depend on concrete SDK APIs.

#### Scenario: AgentExecutor invokes Claude runtime
- **WHEN** AgentExecutor needs model execution
- **THEN** it calls ClaudeCodeAgentClient with structured prompt, context, skills, tool registry, and execution limits instead of using SDK APIs directly

### Requirement: Agent context is constructed before model execution
The system SHALL construct an Agent execution context containing system role, safety rules, user question, source/project or service code, allowed tools, tool restrictions, skills, relevant retrieved context, and safe conversation summary.

#### Scenario: Diagnostic question is prepared
- **WHEN** AgentExecutor prepares a job for Claude execution
- **THEN** AgentContextBuilder returns a context that includes read-only safety rules and excludes unrelated full ER/business-flow exports

### Requirement: Skills are loaded as explicit diagnostic workflows
The system SHALL load only configured diagnostic Skills for MVP, including bug analysis, SQL diagnosis, Redis diagnosis, and Loki log analysis.

#### Scenario: Skills are registered
- **WHEN** the Agent runtime starts a diagnostic job
- **THEN** it registers the configured Skills with ClaudeCodeAgentClient and makes their workflow guidance available to the Agent

### Requirement: Runtime exposes only read-only tools
The system SHALL register only read-only MCP or SDK tools for MVP Agent execution.

#### Scenario: Agent asks for a mutating tool
- **WHEN** the Claude runtime attempts to call a tool for code modification, database update, Redis deletion, restart, deployment, pull request creation, or sandbox execution
- **THEN** the system rejects the tool call because that tool is not registered for MVP execution

### Requirement: Final reports are evidence based
The system SHALL require Agent final answers to include a conclusion, evidence summary, uncertainty or limitations when applicable, and suggested safe next actions.

#### Scenario: Agent completes order diagnosis
- **WHEN** the Agent finishes investigating a business question such as an order stuck in a status
- **THEN** the final report includes the likely cause, relevant log/database/Redis/ER/business-flow evidence, uncertainty if evidence is incomplete, and non-mutating recommendations

### Requirement: Private model reasoning is not persisted
The system SHALL persist user-visible execution steps and evidence summaries, not private model chain-of-thought.

#### Scenario: Agent records progress
- **WHEN** the Agent reasons internally during diagnosis
- **THEN** the system persists only safe step summaries, tool calls, tool results, artifacts, and final answer content
