## ADDED Requirements

### Requirement: Redis and Loki resolve at the base level
The system SHALL treat Redis and Loki as base-level resources shared by all workshops within that base, routing each request to the base's configured upstream.

#### Scenario: Redis routed to base upstream
- **WHEN** a Redis request targets environment `sanjiu`, base `guanlan`
- **THEN** the platform connects to the Redis upstream configured for base `guanlan`

#### Scenario: Loki routed to base upstream
- **WHEN** a Loki request targets base `guanlan`
- **THEN** the platform queries the Loki upstream (and tenant, if configured) for base `guanlan`

### Requirement: Workshop is distinguished by Redis key prefix
The system SHALL constrain workshop-scoped Redis reads to that workshop's key prefix (derived from the workshop code) and SHALL reject keys or scan patterns outside that prefix. The system SHALL allow only read operations (`GET`, bounded `SCAN`).

#### Scenario: Key within workshop prefix accepted
- **WHEN** a Redis GET for workshop `GL001` targets a key within the `GL001` key namespace
- **THEN** the platform executes the read

#### Scenario: Key outside workshop prefix rejected
- **WHEN** a Redis request for workshop `GL001` targets a key or scan pattern in the `GL002` namespace or an unbounded `*` pattern
- **THEN** the platform rejects the request as a policy violation

#### Scenario: Mutating Redis command rejected
- **WHEN** a Redis request uses a non-read command (e.g. `SET`, `DEL`, `EXPIRE`, `FLUSHDB`, `EVAL`)
- **THEN** the platform rejects it as not read-only

### Requirement: Workshop is distinguished by Loki label
The system SHALL constrain workshop-scoped Loki queries using the workshop label derived from the workshop code, in addition to existing bounded selector, time range, and result size limits.

#### Scenario: Workshop label injected
- **WHEN** a Loki query for base `guanlan`, workshop `GL001` is executed
- **THEN** the platform includes the workshop label (e.g. `workshop="GL001"`) in the effective selector

#### Scenario: Base-only Loki query when no workshop
- **WHEN** a Loki query targets a base without a workshop layer
- **THEN** the platform queries at the base level without a workshop label while still enforcing bounded selector, time range, and result size

### Requirement: Redis and Loki errors are classified and desensitized
The system SHALL classify Redis and Loki connection timeouts and transient upstream failures as retryable, classify policy violations as non-retryable, and desensitize credentials in all error messages.

#### Scenario: Upstream timeout is retryable
- **WHEN** a base Redis or Loki upstream times out or returns a transient error
- **THEN** the platform returns a retryable error with no credentials in the message
