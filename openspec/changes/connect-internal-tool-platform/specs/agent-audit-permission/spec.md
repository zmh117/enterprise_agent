## MODIFIED Requirements

### Requirement: Tool calls are recorded with safe summaries
The system SHALL persist tool call records with sanitized request payload summaries, response summaries, status, duration, risk level, audit linkage, and Internal API Platform outcome details when available.

#### Scenario: Database tool succeeds
- **WHEN** `query_database` returns evidence through the Internal API Platform
- **THEN** the system records the tool name, sanitized request summary, bounded response summary, duration, status, risk level, related audit event, and platform request metadata if provided

#### Scenario: Tool call returns sensitive or large data
- **WHEN** a tool response contains sensitive fields or exceeds inline storage limits
- **THEN** the system stores a masked or summarized response in PostgreSQL and avoids persisting raw sensitive payloads in the tool call row

#### Scenario: Internal platform rejects a tool call
- **WHEN** the Internal API Platform rejects a tool call because of authorization, data-source policy, query policy, or malformed parameters
- **THEN** the system records a failed tool call with a safe rejection reason, duration, risk level, and audit event without exposing platform secrets

### Requirement: Audit events are persisted across the execution chain
The system SHALL persist audit events for webhook receipt, identity parsing, permission decisions, job creation, queue dispatch, worker claim, tool calls, internal platform calls, result creation, failures, retries, and DingTalk callbacks.

#### Scenario: Job completes successfully
- **WHEN** an Agent job is accepted, executed, calls one or more Internal API Platform tools, and replies to DingTalk
- **THEN** the audit trail includes records linking the original user request, job, internal platform tool calls, final report, and callback delivery

#### Scenario: Job fails before execution
- **WHEN** a job is rejected before Agent runtime starts
- **THEN** the audit trail includes the rejection reason and no tool execution records

#### Scenario: Internal platform call fails transiently
- **WHEN** a tool call fails because the Internal API Platform times out or returns a retryable upstream error
- **THEN** the audit trail records the transient failure and the job retry decision without storing credentials or raw platform payloads
