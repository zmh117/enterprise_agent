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
The system SHALL send the persisted Job ID and correlation ID with every Internal API Platform tool request and MUST authenticate with a required service Bearer Token loaded from a file. User, application, project and scope headers MAY be included only for server-side consistency checks.

#### Scenario: Tool request carries authoritative lookup keys
- **WHEN** Agent calls any read-only tool through `HttpInternalApiClient`
- **THEN** the request includes `X-Agent-Job-Id` and `X-Correlation-Id`, plus any non-authoritative consistency headers

#### Scenario: Tool request uses required authorization
- **WHEN** a non-test Worker starts with real internal tools
- **THEN** it loads the service Token from `INTERNAL_API_AUTH_TOKEN_FILE`, sends `Authorization: Bearer <token>`, and never writes the Token to logs, audit or summaries

#### Scenario: Required Token file is absent
- **WHEN** a non-test Worker or Internal API Platform starts without its required Token file
- **THEN** startup must fail instead of accepting unauthenticated tool traffic

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

### Requirement: Internal API Platform 必须重新读取 Job 授权事实
Internal API Platform MUST use the authenticated Job ID to load current Job state and its immutable application publication, Handler, Resource Revision and Execution Scope before every tool operation.

#### Scenario: Service Token 有效但 Job 不属于请求范围
- **WHEN** request headers attempt to name a resource outside the loaded Job scope
- **THEN** the platform rejects the request without opening an upstream connection

### Requirement: Internal API 服务 Token 必须支持受控轮换
系统 SHALL 支持 current/next Token 在短暂维护窗口重叠，并使用常量时间比较；完成轮换后 MUST 移除旧 Token。

#### Scenario: 轮换窗口内使用 next Token
- **WHEN** next Token 已部署到服务端并开始逐个更新调用方
- **THEN** current 和 next 均可通过认证，且审计不记录 Token 内容

#### Scenario: 轮换完成
- **WHEN** 所有调用方已切换到 next Token
- **THEN** 运维必须将其提升为 current 并撤销旧 Token

