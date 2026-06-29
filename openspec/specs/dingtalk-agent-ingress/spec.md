# dingtalk-agent-ingress Specification

## Purpose
TBD - created by archiving change add-readonly-diagnostic-agent-mvp. Update Purpose after archive.
## Requirements
### Requirement: DingTalk webhook requests are verified
The system SHALL expose a DingTalk Agent webhook endpoint that verifies the DingTalk request signature before any Agent session, job, or message is created.

#### Scenario: Valid DingTalk webhook is accepted
- **WHEN** DingTalk sends a webhook request with a valid signature and supported message type
- **THEN** the system accepts the request for Agent job creation

#### Scenario: Invalid DingTalk webhook is rejected
- **WHEN** DingTalk sends a webhook request with an invalid or missing signature
- **THEN** the system rejects the request without creating an Agent session, job, message, or queue message

### Requirement: DingTalk message identity is parsed
The system SHALL parse and persist the DingTalk conversation identity, DingTalk user identity, source channel, and user message content needed to create an Agent session and Agent job.

#### Scenario: User asks a diagnostic question
- **WHEN** a verified DingTalk message contains a user diagnostic question
- **THEN** the system persists the DingTalk conversation identity, DingTalk user identity, source channel, and original user message

### Requirement: DingTalk ingress is idempotent
The system SHALL use DingTalk message identifiers or a deterministic idempotency key to avoid creating duplicate Agent jobs for retried webhook deliveries.

#### Scenario: Duplicate webhook delivery is received
- **WHEN** the same DingTalk message is delivered more than once
- **THEN** the system returns the existing Agent job acknowledgement instead of creating another Agent job

### Requirement: DingTalk receives immediate acknowledgement
The system SHALL return a quick acknowledgement to DingTalk after a job is persisted and dispatched, without waiting for Claude Code Agent execution to finish.

#### Scenario: Job is created successfully
- **WHEN** the system creates and dispatches an Agent job from a DingTalk message
- **THEN** DingTalk receives a response indicating the task has been accepted and analysis is starting

### Requirement: DingTalk receives final Agent results
The system SHALL send the final Agent report or failure notice back to the originating DingTalk conversation after asynchronous job execution completes.

#### Scenario: Agent job succeeds
- **WHEN** an Agent job reaches SUCCEEDED with a final report
- **THEN** the system sends the report to the originating DingTalk conversation

#### Scenario: Agent job fails
- **WHEN** an Agent job reaches FAILED or TIMEOUT
- **THEN** the system sends a failure notice with a safe failure reason to the originating DingTalk conversation

