## ADDED Requirements

### Requirement: Oracle gateway supports thick client and legacy row limits
The system SHALL execute Oracle read-only queries using either thin or thick (Instant Client) connectivity as configured for the base, and SHALL apply a legacy-compatible row-limit mechanism when the base is marked for older Oracle compatibility.

#### Scenario: Thick mode uses Instant Client
- **WHEN** a base with engine `oracle` is configured for thick client mode and Instant Client is available in the process
- **THEN** the gateway connects using oracledb thick mode and executes the read-only query

#### Scenario: Legacy Oracle uses ROWNUM row limit
- **WHEN** a workshop-scoped Oracle query targets a base configured with legacy Oracle compatibility and no explicit row bound in SQL
- **THEN** the gateway enforces the maximum row limit using a `ROWNUM`-based rewrite rather than requiring `FETCH FIRST`

#### Scenario: Modern Oracle keeps FETCH FIRST
- **WHEN** a workshop-scoped Oracle query targets a base without legacy compatibility (default)
- **THEN** the gateway continues to enforce the row limit using `FETCH FIRST` (or equivalent modern syntax)

#### Scenario: Thick requested but client unavailable
- **WHEN** a base requires thick mode but Instant Client was not initialized successfully
- **THEN** the gateway returns a clear non-retryable configuration/upstream error and does not silently fall back to thin
