## ADDED Requirements

### Requirement: Local Internal API Platform is available for development
The system SHALL provide a local development Internal API Platform service that exposes the MVP read-only tool endpoints without changing Agent runtime dependencies.

#### Scenario: Local platform starts in Compose
- **WHEN** the developer starts Docker Compose with the local tools profile
- **THEN** `local-internal-api-platform` starts as a service on the Compose network and exposes port `9000` to other containers

#### Scenario: Worker targets local platform
- **WHEN** `FEATURE_REAL_INTERNAL_TOOLS=true` and `INTERNAL_API_BASE_URL=http://local-internal-api-platform:9000`
- **THEN** `agent-worker` sends tool calls to the local platform through `HttpInternalApiClient`

### Requirement: Local platform queries real Loki through bounded endpoint
The local platform SHALL implement `POST /tools/loki/query` by querying the configured Loki HTTP API with bounded read-only parameters.

#### Scenario: Loki query succeeds
- **WHEN** the platform receives `query_loki` with an allowed service, keyword, time range, and limit
- **THEN** it queries Loki through `LOKI_BASE_URL` and returns a bounded summary envelope containing service, line count, highlights, stream labels, and metadata

#### Scenario: Loki runs on host machine
- **WHEN** Loki is reachable from the host at `http://localhost:3100`
- **THEN** the Compose default configuration uses `http://host.docker.internal:3100` as `LOKI_BASE_URL` for container-to-host access

#### Scenario: Loki is unavailable
- **WHEN** `LOKI_BASE_URL` cannot be reached or Loki returns a transient upstream error
- **THEN** the platform returns a retryable Internal API Platform error response without exposing credentials or unbounded upstream details

### Requirement: Loki query input is constrained
The local platform MUST constrain Loki query input before calling Loki.

#### Scenario: Query exceeds time range
- **WHEN** `minutes` exceeds `LOKI_MAX_MINUTES`
- **THEN** the platform rejects the request with a safe policy or validation error and does not call Loki

#### Scenario: Query exceeds line limit
- **WHEN** `limit` exceeds `LOKI_MAX_LINES`
- **THEN** the platform rejects or clamps the request according to configuration and records truncation metadata

#### Scenario: Unsafe selector is supplied
- **WHEN** the request contains an empty selector, an unsupported selector label, or a selector value with unsafe characters
- **THEN** the platform rejects the request before constructing LogQL

### Requirement: Local context endpoints provide explicit placeholders
The local platform SHALL implement ER and business-flow context endpoints with explicit local placeholder summaries until real graph-context services are connected.

#### Scenario: ER context is requested
- **WHEN** Agent calls `get_er_context`
- **THEN** the local platform returns an envelope that identifies the response as local placeholder context and includes the query and project code

#### Scenario: Business-flow context is requested
- **WHEN** Agent calls `get_business_flow_context`
- **THEN** the local platform returns an envelope that identifies the response as local placeholder context and includes the query and project code

### Requirement: Unconfigured database and Redis tools are disabled by default
The local platform MUST NOT return fake database or Redis evidence when those real sources are not configured.

#### Scenario: Database tool is called before configuration
- **WHEN** Agent calls `query_database` against the local platform without an enabled database gateway
- **THEN** the platform returns a safe `tool_not_configured` error and does not execute SQL

#### Scenario: Redis tool is called before configuration
- **WHEN** Agent calls `query_redis_get` or `query_redis_scan` against the local platform without an enabled Redis gateway
- **THEN** the platform returns a safe `tool_not_configured` error and does not access Redis

### Requirement: Real Claude and local Loki can be validated end to end
The system SHALL document and support an end-to-end local verification path using real Claude/DeepSeek and local Loki.

#### Scenario: Real diagnostic job uses local Loki
- **WHEN** the developer starts `api-server`, `agent-worker`, RabbitMQ, PostgreSQL, and `local-internal-api-platform` with real Claude enabled
- **THEN** submitting a debug Agent job eventually produces a terminal job status and persists steps and tool-call records that show local platform tool activity

#### Scenario: Verification keeps write operations unavailable
- **WHEN** real Claude attempts a database, Redis mutation, or unsupported write operation during local verification
- **THEN** the system rejects the operation and records the safe failure without mutating external systems
