# internal-tool-platform-integration Specification

## Purpose
TBD - created by archiving change connect-internal-tool-platform. Update Purpose after archive.
## Requirements
### Requirement: Runtime can select real Internal API Platform
The system SHALL select the HTTP Internal API Platform client for API and worker runtime when `FEATURE_REAL_INTERNAL_TOOLS=true`, and SHALL keep the fake internal API client for test runtime and default local execution unless explicitly enabled.

#### Scenario: Real internal tools are enabled
- **WHEN** the worker starts with `FEATURE_REAL_INTERNAL_TOOLS=true` and a configured `INTERNAL_API_BASE_URL`
- **THEN** the runtime injects `HttpInternalApiClient` into `ReadOnlyToolService`

#### Scenario: Tests keep fake internal tools
- **WHEN** unit tests build the test container without overriding internal tools
- **THEN** the runtime injects `FakeInternalApiClient` and does not require a networked Internal API Platform

### Requirement: Internal API requests include execution context
The system SHALL send job, user, project, and correlation context with every Internal API Platform tool request.

#### Scenario: Tool request carries context headers
- **WHEN** Agent calls any read-only tool through `HttpInternalApiClient`
- **THEN** the HTTP request includes `X-Agent-Job-Id`, `X-Agent-User-Id`, `X-Agent-Project-Code`, and `X-Correlation-Id` headers when those values are available

#### Scenario: Tool request uses configured authorization
- **WHEN** `INTERNAL_API_AUTH_TOKEN` is configured
- **THEN** the HTTP request includes `Authorization: Bearer <token>` and the token is never written to logs, audit payloads, or tool-call summaries

### Requirement: Internal API responses use a safe envelope
The system SHALL normalize Internal API Platform responses into `ToolResult(summary, raw)` and SHALL use the `summary` field for persisted tool-call summaries and model-visible evidence.

#### Scenario: Platform returns summary envelope
- **WHEN** the internal platform returns a JSON object containing `summary`, `raw`, `truncated`, and `metadata`
- **THEN** the client stores `summary` as `ToolResult.summary` and stores the full response as `ToolResult.raw` in memory only

#### Scenario: Platform returns legacy body
- **WHEN** the internal platform returns a JSON object without a `summary` field
- **THEN** the client treats the response body as the summary while still applying bounded persistence in the tool service

### Requirement: Internal API failures are classified
The system SHALL classify Internal API Platform HTTP and transport failures so Agent job retry behavior is deterministic.

#### Scenario: Transient platform failure
- **WHEN** the internal platform request times out, fails with a transient network error, or returns HTTP 429, 502, 503, or 504
- **THEN** the tool call raises a retryable execution error that can be handled by job retry policy

#### Scenario: Non-retryable platform rejection
- **WHEN** the internal platform returns HTTP 400, 401, 403, 404, or an explicit policy denial
- **THEN** the tool call fails with a non-retryable safe error and records the rejected tool call

### Requirement: Local mock platform can verify HTTP tool flow
The system SHALL provide a local mock or test double for Internal API Platform that implements the six MVP read-only endpoints with the same response envelope as the real platform.

#### Scenario: Docker Compose validates mock platform
- **WHEN** Docker Compose runs with `FEATURE_REAL_INTERNAL_TOOLS=true` and `INTERNAL_API_BASE_URL` pointing to the mock platform
- **THEN** a debug Agent job can call HTTP tools, persist tool-call summaries, and produce a diagnostic report without requiring real internal data sources

