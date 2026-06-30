## MODIFIED Requirements

### Requirement: Tool calls go through internal API platform
The system SHALL route Claude tool calls through internal API platform client contracts instead of direct database, Redis, Loki, ER, or business-flow clients inside the Agent runtime. When real internal tools are enabled, the runtime SHALL perform these calls through the configured HTTP Internal API Platform; when disabled, tests and local development MAY use the fake client with the same application contract.

#### Scenario: Agent queries database evidence
- **WHEN** the Claude runtime calls `query_database`
- **THEN** the tool adapter sends the request to the internal API platform database query endpoint and does not open a direct database connection from Agent runtime code

#### Scenario: Agent queries Redis evidence
- **WHEN** the Claude runtime calls `query_redis_get` or `query_redis_scan`
- **THEN** the tool adapter sends the request to the internal API platform Redis endpoint and does not open a direct Redis connection from Agent runtime code

#### Scenario: Real HTTP client is selected
- **WHEN** `FEATURE_REAL_INTERNAL_TOOLS=true`
- **THEN** the API and worker runtime use `HttpInternalApiClient` for read-only tools instead of `FakeInternalApiClient`

#### Scenario: Fake client remains available
- **WHEN** `FEATURE_REAL_INTERNAL_TOOLS=false` or test runtime builds a container
- **THEN** the runtime uses `FakeInternalApiClient` and preserves deterministic local test behavior

### Requirement: Database query tool is read-only
The system SHALL allow database tool execution only for policy-approved read operations and MUST reject insert, update, delete, DDL, privileged, or unsafe statements before forwarding the request. The Internal API Platform MUST also enforce read-only policy before touching the real data source.

#### Scenario: Select query is approved
- **WHEN** Agent calls `query_database` with a policy-approved read query
- **THEN** the internal API platform executes the query through the database gateway and returns a bounded, summarized result

#### Scenario: Mutating query is rejected
- **WHEN** Agent calls `query_database` with an insert, update, delete, DDL, or privileged operation
- **THEN** the system rejects the request and records the rejected tool call without sending an unsafe operation to the real database

### Requirement: Redis tools are read-only
The system SHALL allow Redis evidence collection only through approved get and bounded scan operations and MUST reject delete, set, expire, flush, or script execution operations before forwarding the request. The Internal API Platform MUST also enforce Redis read-only policy before touching the real Redis source.

#### Scenario: Redis key is read
- **WHEN** Agent calls `query_redis_get` for an approved key pattern
- **THEN** the internal API platform returns the masked value summary and records the access

#### Scenario: Redis mutation is requested
- **WHEN** Agent requests Redis deletion, mutation, expiration, flush, or scripting
- **THEN** the system rejects the request because MVP tools are read-only and does not forward the mutation to the real Redis source

### Requirement: Loki queries are bounded
The system SHALL constrain Loki queries by allowed tenant or service, time range, query size, and result size before executing the request. The Internal API Platform MUST also enforce Loki tenant, selector, time range, and result-size limits before querying the real Loki source.

#### Scenario: Loki query is within limits
- **WHEN** Agent calls `query_loki` with an allowed service selector and time range
- **THEN** the internal API platform returns a bounded log summary and records the query metadata

#### Scenario: Loki query exceeds limits
- **WHEN** Agent calls `query_loki` with a disallowed selector, excessive time range, or excessive result size
- **THEN** the system rejects or truncates the request according to policy and records the decision

## ADDED Requirements

### Requirement: Internal tool endpoints have fixed MVP paths
The system SHALL map each MVP read-only tool to a fixed Internal API Platform HTTP endpoint.

#### Scenario: Context endpoints are called
- **WHEN** Agent calls `get_er_context` or `get_business_flow_context`
- **THEN** the HTTP client calls `/tools/context/er` or `/tools/context/business-flow` with the project code and query text

#### Scenario: Evidence endpoints are called
- **WHEN** Agent calls `query_loki`, `query_database`, `query_redis_get`, or `query_redis_scan`
- **THEN** the HTTP client calls the matching `/tools/loki/query`, `/tools/database/query`, `/tools/redis/get`, or `/tools/redis/scan` endpoint

### Requirement: Tool responses are bounded before persistence
The system SHALL persist only bounded safe summaries of Internal API Platform request and response data.

#### Scenario: Large platform response is returned
- **WHEN** the internal platform returns a response larger than the configured tool summary limit
- **THEN** the system stores a truncated summary and marks the summary as truncated where supported

#### Scenario: Sensitive platform response is returned
- **WHEN** the internal platform response contains sensitive fields or credential-like values
- **THEN** the system masks or omits those values before writing tool-call summaries or audit payloads

