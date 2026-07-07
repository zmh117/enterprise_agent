## Purpose

Define the read-only multi-dialect database gateway used by internal tools to query enterprise databases through a bounded and auditable platform layer.

## Requirements

### Requirement: Database gateway supports MySQL, SQL Server, and Oracle
The system SHALL execute read-only queries against MySQL, SQL Server, and Oracle engines through a common gateway contract, selecting the driver and dialect based on the resolved base engine.

#### Scenario: Query routes to base engine
- **WHEN** a database query targets base `guanlan` configured as `mysql`
- **THEN** the gateway executes the query using the MySQL driver and MySQL dialect rules

#### Scenario: Unsupported engine is rejected
- **WHEN** a base is configured with an engine outside `mysql`/`sqlserver`/`oracle`
- **THEN** the platform rejects configuration or requests for that base with a clear non-retryable error

### Requirement: Only read-only statements are allowed across dialects
The system SHALL allow only read-only statements (single `SELECT` or `WITH` query) and SHALL reject data-modifying or administrative statements for every supported dialect. The system SHALL reject multiple statements in a single request.

#### Scenario: Mutating statement rejected
- **WHEN** a request contains `INSERT`, `UPDATE`, `DELETE`, `DROP`, `ALTER`, `TRUNCATE`, `MERGE`, `CALL`, or `EXEC`
- **THEN** the gateway rejects it with a policy error before any execution, regardless of dialect

#### Scenario: Multiple statements rejected
- **WHEN** a request contains more than one SQL statement (e.g. separated by `;`)
- **THEN** the gateway rejects the request as a policy violation

#### Scenario: Comment-obfuscated statement rejected
- **WHEN** a request hides a forbidden operation using comments or unusual whitespace
- **THEN** the gateway strips comments before analysis and still rejects the forbidden operation

### Requirement: Queries are restricted to the target workshop table prefix
The system SHALL enforce that every table referenced by a workshop-scoped query uses that workshop's table prefix (e.g. `GL001_EBR_`). The system SHALL reject queries that reference tables without the required prefix or belonging to another workshop.

#### Scenario: Correct prefix accepted
- **WHEN** a query for workshop `GL001` references only tables like `GL001_EBR_order`
- **THEN** the gateway executes the query

#### Scenario: Missing prefix rejected
- **WHEN** a query for workshop `GL001` references `order_header` without the workshop prefix
- **THEN** the gateway rejects the query as a policy violation

#### Scenario: Cross-workshop access rejected
- **WHEN** a query for workshop `GL001` references `GL002_EBR_order`
- **THEN** the gateway rejects the query because it targets a different workshop

### Requirement: Result size is bounded per dialect
The system SHALL enforce a maximum row limit using each dialect's correct mechanism (e.g. `LIMIT` for MySQL, `TOP`/`OFFSET FETCH` for SQL Server, `FETCH FIRST`/`ROWNUM` for Oracle) and SHALL bound the serialized response size.

#### Scenario: Limit applied for each dialect
- **WHEN** a query is executed against MySQL, SQL Server, or Oracle without an explicit bound
- **THEN** the gateway applies the configured maximum row limit using that dialect's mechanism

#### Scenario: Oversized response is truncated
- **WHEN** a query result exceeds the configured maximum response size
- **THEN** the gateway truncates the response, marks it truncated, and still returns a bounded summary

### Requirement: Database errors are classified and desensitized
The system SHALL classify database connection timeouts and transient failures as retryable, classify policy and syntax rejections as non-retryable, and desensitize credentials or connection details in all error messages.

#### Scenario: Connection timeout is retryable
- **WHEN** a base database connection times out or fails transiently
- **THEN** the gateway returns a retryable error and no credentials appear in the error message

#### Scenario: Policy rejection is non-retryable
- **WHEN** a query is rejected for read-only or prefix policy violations
- **THEN** the gateway returns a non-retryable policy error
