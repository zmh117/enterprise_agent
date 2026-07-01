# readonly-tool-platform Specification

## Purpose
TBD - created by archiving change add-readonly-diagnostic-agent-mvp. Update Purpose after archive.
## Requirements
### Requirement: Tool calls go through internal API platform
The system SHALL route Claude tool calls through internal API platform client contracts instead of direct database, Redis, Loki, ER, or business-flow clients inside the Agent runtime.

#### Scenario: Agent queries database evidence
- **WHEN** the Claude runtime calls `query_database`
- **THEN** the tool adapter sends the request to the internal API platform database query endpoint and does not open a direct database connection from Agent runtime code

#### Scenario: Agent queries Redis evidence
- **WHEN** the Claude runtime calls `query_redis_get` or `query_redis_scan`
- **THEN** the tool adapter sends the request to the internal API platform Redis endpoint and does not open a direct Redis connection from Agent runtime code

### Requirement: Tool definitions are persisted
The system SHALL persist tool definitions, connector configuration metadata, data source registry entries, and enablement status needed for later web-based configuration.

#### Scenario: Tool registry is loaded
- **WHEN** the Agent runtime prepares available tools for a job
- **THEN** it loads enabled tool definitions and connector metadata from PostgreSQL-backed configuration

### Requirement: Context search returns compact relevant graph context
The system SHALL provide tools to retrieve relevant ER and business-flow context for a user question without loading all available tables, fields, or flow nodes into the Agent prompt.

#### Scenario: Agent searches order context
- **WHEN** the user asks why an order is stuck in a business status
- **THEN** the context tools return only relevant ER tables, fields, enums, relationships, business-flow nodes, and flow edges for the question

### Requirement: Database query tool is read-only
The system SHALL allow database tool execution only for policy-approved read operations and MUST reject insert, update, delete, DDL, privileged, or unsafe statements.

#### Scenario: Select query is approved
- **WHEN** Agent calls `query_database` with a policy-approved read query
- **THEN** the internal API platform executes the query through the database gateway and returns a bounded, summarized result

#### Scenario: Mutating query is rejected
- **WHEN** Agent calls `query_database` with an insert, update, delete, DDL, or privileged operation
- **THEN** the internal API platform rejects the request and records the rejected tool call

### Requirement: Redis tools are read-only
The system SHALL allow Redis evidence collection only through approved get and bounded scan operations and MUST reject delete, set, expire, flush, or script execution operations.

#### Scenario: Redis key is read
- **WHEN** Agent calls `query_redis_get` for an approved key pattern
- **THEN** the internal API platform returns the masked value summary and records the access

#### Scenario: Redis mutation is requested
- **WHEN** Agent requests Redis deletion, mutation, expiration, flush, or scripting
- **THEN** the internal API platform rejects the request because MVP tools are read-only

### Requirement: Loki queries are bounded
The system SHALL constrain Loki queries by allowed tenant, allowed selector labels, time range, query size, and result size before executing the request.

#### Scenario: Loki query is within limits
- **WHEN** Agent calls `query_loki` with an allowed selector and time range
- **THEN** the internal API platform returns a bounded log summary and records the query metadata

#### Scenario: Loki query exceeds limits
- **WHEN** Agent calls `query_loki` with a disallowed selector, excessive time range, or excessive result size
- **THEN** the internal API platform rejects or truncates the request according to policy and records the decision
