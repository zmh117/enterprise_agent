# agent-audit-permission Specification

## Purpose
TBD - created by archiving change add-readonly-diagnostic-agent-mvp. Update Purpose after archive.
## Requirements
### Requirement: Users must be authorized before Agent job creation
The system SHALL check user allowlists and service or project allowlists before creating an Agent job from a DingTalk message.

#### Scenario: Authorized user submits request
- **WHEN** a verified DingTalk user is allowed to use the Agent for the requested service or project
- **THEN** the system creates the Agent job and records the permission decision

#### Scenario: Unauthorized user submits request
- **WHEN** a verified DingTalk user is not allowed to use the Agent or target service or project
- **THEN** the system rejects the request, records the permission denial, and does not publish an Agent job

### Requirement: Tool access is policy checked
The system SHALL check tool allowlists, source access, and read-only risk policy before executing each Agent tool call.

#### Scenario: Allowed read-only tool call
- **WHEN** Agent requests an enabled read-only tool within the user's allowed scope
- **THEN** the system executes the tool call and records the policy decision

#### Scenario: Disallowed tool call
- **WHEN** Agent requests a disabled tool, out-of-scope source, or non-read-only operation
- **THEN** the system rejects the tool call and records the policy decision

### Requirement: Audit events are persisted across the execution chain
The system SHALL persist audit events for webhook receipt, identity parsing, permission decisions, job creation, queue dispatch, worker claim, tool calls, result creation, failures, retries, and DingTalk callbacks.

#### Scenario: Job completes successfully
- **WHEN** an Agent job is accepted, executed, and replied to DingTalk
- **THEN** the audit trail includes records linking the original user request, job, tool calls, final report, and callback delivery

#### Scenario: Job fails before execution
- **WHEN** a job is rejected before Agent runtime starts
- **THEN** the audit trail includes the rejection reason and no tool execution records

### Requirement: Tool calls are recorded with safe summaries
The system SHALL persist tool call records with sanitized request payload summaries, response summaries, status, duration, risk level, and audit linkage.

#### Scenario: Database tool succeeds
- **WHEN** `query_database` returns evidence
- **THEN** the system records the tool name, sanitized request summary, bounded response summary, duration, status, risk level, and related audit event

#### Scenario: Tool call returns sensitive or large data
- **WHEN** a tool response contains sensitive fields or exceeds inline storage limits
- **THEN** the system stores a masked or summarized response in PostgreSQL and avoids persisting raw sensitive payloads in the tool call row

### Requirement: Agent artifacts are persisted
The system SHALL persist final reports and other approved Agent artifacts with job linkage and artifact type.

#### Scenario: Final report is generated
- **WHEN** the Agent produces the final diagnostic answer
- **THEN** the system persists a report artifact linked to the Agent job

### Requirement: Configuration is persisted for future web management
The system SHALL store permission policies, tool enablement, connector metadata, and data source registry entries in PostgreSQL so a later web service can manage them without redesigning core persistence.

#### Scenario: Administrator later changes tool access
- **WHEN** a future web service updates tool enablement or permission policy
- **THEN** the Agent runtime can read the updated PostgreSQL-backed configuration without requiring a code change

