## ADDED Requirements

### Requirement: Local Internal API Platform preserves the read-only tool contract
The system SHALL treat the local development Internal API Platform as an implementation of the same read-only Internal API Platform contract used by Agent tools.

#### Scenario: Local platform uses fixed MVP endpoint paths
- **WHEN** `HttpInternalApiClient` calls the local platform
- **THEN** the local platform serves the same MVP paths as the real platform: `/tools/context/er`, `/tools/context/business-flow`, `/tools/loki/query`, `/tools/database/query`, `/tools/redis/get`, and `/tools/redis/scan`

#### Scenario: Local platform returns the standard envelope
- **WHEN** a local platform tool endpoint succeeds
- **THEN** it returns `summary`, `raw`, `truncated`, and `metadata` fields compatible with `HttpInternalApiClient`

#### Scenario: Local platform denies unsupported tools safely
- **WHEN** a configured Agent calls an endpoint that is not backed by a real local data source
- **THEN** the local platform returns a safe non-success error instead of fake evidence or a direct data-source call

### Requirement: Local Loki evidence is bounded before persistence
The system SHALL persist only bounded local Loki evidence summaries from the local Internal API Platform.

#### Scenario: Loki returns many log lines
- **WHEN** Loki returns more lines or bytes than the configured local platform summary limit
- **THEN** the local platform truncates the summary, marks the response as truncated, and avoids returning an unbounded raw payload for persistence

#### Scenario: Loki response contains sensitive-looking values
- **WHEN** log lines contain credential-like values or secrets
- **THEN** the local platform or downstream tool summary path masks or omits sensitive values before they are written to tool-call summaries or audit records

### Requirement: Local platform errors follow existing retry classification
The system SHALL format local platform errors so `HttpInternalApiClient` can classify them consistently with real Internal API Platform errors.

#### Scenario: Loki upstream timeout occurs
- **WHEN** the local platform cannot reach Loki due to timeout or transient upstream failure
- **THEN** it returns an HTTP status and safe body that `HttpInternalApiClient` maps to `RetryableExecutionError`

#### Scenario: Local policy rejects Loki input
- **WHEN** the local platform rejects a Loki query because the input violates policy
- **THEN** it returns an HTTP status and safe body that `HttpInternalApiClient` maps to a non-retryable policy or validation error
