## ADDED Requirements

### Requirement: Real runtime is implemented with the Claude Agent SDK
The system SHALL implement `RealClaudeCodeAgentClient` using the Claude Agent SDK (`claude_agent_sdk`) entry points (`ClaudeSDKClient` or `query` with `ClaudeAgentOptions`) instead of calling the raw Anthropic Messages API. Only the infrastructure client module SHALL import the SDK.

#### Scenario: Real client drives an agent loop
- **WHEN** `RealClaudeCodeAgentClient.run()` executes a job with a valid API key and CLI available
- **THEN** it issues the diagnostic prompt through the Claude Agent SDK and consumes the SDK message stream until a final result message is produced

#### Scenario: SDK types do not leak into application layer
- **WHEN** `AgentExecutor` invokes the client
- **THEN** it receives an `AgentRunResult` and never imports or references `claude_agent_sdk` types

### Requirement: Real runtime is selectable via feature flag
The system SHALL select `RealClaudeCodeAgentClient` when `FEATURE_REAL_CLAUDE=true` and `StubClaudeCodeAgentClient` otherwise for API and worker runtime containers. Test runtime SHALL continue to use stub by default unless a test explicitly injects a fake client.

#### Scenario: Compose worker uses real runtime when enabled
- **WHEN** `agent-worker` starts with `FEATURE_REAL_CLAUDE=true` and a valid Anthropic API key
- **THEN** the worker container injects `RealClaudeCodeAgentClient` into `AgentExecutor`

#### Scenario: Local tests keep stub runtime
- **WHEN** unit tests build the test container without overriding the Claude client
- **THEN** `AgentExecutor` uses `StubClaudeCodeAgentClient` and does not require the SDK, an API key, or the CLI

### Requirement: Anthropic credentials and CLI runtime are validated before execution
The system SHALL read `ANTHROPIC_API_KEY` from environment configuration when real Claude runtime is enabled and MAY read optional `ANTHROPIC_BASE_URL`. The system SHALL surface a clear error when the SDK or its underlying Claude Code CLI runtime is unavailable.

#### Scenario: Missing API key fails fast
- **WHEN** `FEATURE_REAL_CLAUDE=true` and `ANTHROPIC_API_KEY` is empty
- **THEN** real Claude execution fails with a non-retryable configuration error and a safe user-facing message

#### Scenario: Missing CLI runtime is not retried indefinitely
- **WHEN** the Claude Agent SDK cannot locate its CLI runtime
- **THEN** execution fails with a non-retryable error rather than being re-queued as a transient failure

### Requirement: Read-only tools are exposed only through an in-process SDK MCP server
The system SHALL expose the MVP read-only tools to the SDK by wrapping `ToolRegistry` in an in-process SDK MCP server (`create_sdk_mcp_server`) and registering it via `ClaudeAgentOptions.mcp_servers`. Each tool call SHALL execute through `ToolRegistry` with the current job's `job_id`, `user_id`, and `project_code`.

#### Scenario: Model calls a registered read-only tool
- **WHEN** Claude calls `mcp__internal__query_database` with valid read-only arguments
- **THEN** the runtime routes the call through `ToolRegistry` to `ReadOnlyToolService` and returns the tool result to the model

#### Scenario: Tool context is bound per job
- **WHEN** two different jobs run through the real runtime
- **THEN** each job's tool invocations use that job's own `job_id`, `user_id`, and `project_code` and do not leak context between jobs

### Requirement: Built-in mutating tools are disabled
The system SHALL prevent the SDK's built-in mutating tools (such as Bash, Write, Edit, file modification, deployment, or web fetch) from being available or approved. The system SHALL auto-approve only `mcp__internal__*` read-only tools via `allowed_tools` and SHALL deny everything else through `disallowed_tools`, `permission_mode`, or a `can_use_tool` callback.

#### Scenario: Model attempts a built-in write tool
- **WHEN** the SDK runtime would otherwise allow a built-in Bash, Write, or Edit tool
- **THEN** the tool is not available or its call is denied, so no mutation can occur

#### Scenario: Only internal read-only tools are auto-approved
- **WHEN** the agent runs a diagnostic job
- **THEN** only `mcp__internal__*` tools are pre-approved and no permission prompt blocks execution

### Requirement: Execution is bounded by turns and wall-clock time
The system SHALL bound real Claude execution using `AGENT_MAX_TURNS` (via SDK `max_turns`) and `AGENT_TIMEOUT_SECONDS` (via an async wall-clock timeout around the SDK session).

#### Scenario: Execution exceeds configured timeout
- **WHEN** the SDK session exceeds `AGENT_TIMEOUT_SECONDS`
- **THEN** the runtime cancels the session and raises `RetryableExecutionError` with a safe timeout message

### Requirement: SDK failures are classified for retry policy
The system SHALL map SDK process errors, transport failures, CLI JSON decode errors, network timeouts, and Anthropic rate limit / overloaded responses to `RetryableExecutionError`. The system SHALL map missing credentials, missing CLI runtime, invalid model configuration, and tool policy violations to non-retryable failures.

#### Scenario: Transient process error triggers retry
- **WHEN** the SDK raises a process or transport error during job execution
- **THEN** the runtime raises `RetryableExecutionError` so `JobRetryService` can republish the job

#### Scenario: Policy violation does not retry as transport error
- **WHEN** a tool call is rejected because SQL policy forbids the statement
- **THEN** the runtime surfaces the rejection to the model and does not treat it as an SDK transport retry

### Requirement: Async SDK is bridged into synchronous execution
The system SHALL bridge the asynchronous Claude Agent SDK into the synchronous `AgentExecutor` and worker without leaking event-loop management into application code.

#### Scenario: Synchronous executor runs async SDK
- **WHEN** the synchronous `AgentExecutor.execute()` calls `RealClaudeCodeAgentClient.run()`
- **THEN** the client manages its own event loop (e.g. `asyncio.run`) and returns a plain `AgentRunResult`

### Requirement: Tool events are returned without private reasoning
The system SHALL populate `AgentRunResult.tool_events` with safe summaries of each tool invocation and result size, excluding raw secrets, full unbounded payloads, and private model chain-of-thought (including SDK thinking blocks).

#### Scenario: Successful tool loop produces events
- **WHEN** the real runtime completes after one or more tool calls
- **THEN** `AgentRunResult` includes ordered tool event summaries suitable for persistence in `agent_tool_call`

### Requirement: Health endpoints report runtime mode without invoking Claude
The system SHALL expose whether real Claude is enabled, whether an API key is configured, and whether the SDK CLI runtime is detected, without making live Claude API calls during health or readiness checks.

#### Scenario: Ready check with stub mode
- **WHEN** `/api/ready` is called with `FEATURE_REAL_CLAUDE=false`
- **THEN** the response indicates Claude is not invoked and real runtime is disabled

#### Scenario: Ready check with missing key
- **WHEN** `/api/ready` is called with `FEATURE_REAL_CLAUDE=true` and no API key
- **THEN** the response reports real runtime enabled but not configured
