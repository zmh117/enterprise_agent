## MODIFIED Requirements

### Requirement: DingTalk message identity is parsed
The system SHALL parse and persist the DingTalk Stream conversation identity, DingTalk user identity, source channel, connector identity, external event identity, and user message content needed to create an Agent session and Agent job.

#### Scenario: User asks a diagnostic question
- **WHEN** a verified DingTalk Stream message contains a user diagnostic question
- **THEN** the system persists the DingTalk conversation identity, DingTalk user identity, source channel, connector identity, external event identity, and original user message

### Requirement: DingTalk ingress is idempotent
The system SHALL use DingTalk Stream event identifiers, message identifiers, or a deterministic idempotency key to avoid creating duplicate Agent jobs for retried or redelivered Stream events.

#### Scenario: Duplicate Stream event is received
- **WHEN** the same DingTalk Stream event or message is delivered more than once
- **THEN** the system returns the existing Agent job acknowledgement instead of creating another Agent job

### Requirement: DingTalk receives immediate acknowledgement
The system SHALL send a quick DingTalk Stream acknowledgement after a job is persisted and dispatched, without waiting for Claude Code Agent execution to finish.

#### Scenario: Job is created successfully
- **WHEN** the system creates and dispatches an Agent job from a DingTalk Stream message
- **THEN** DingTalk receives an acknowledgement indicating the task has been accepted and analysis is starting

### Requirement: DingTalk receives final Agent results
The system SHALL send the final Agent report or failure notice through the configured DingTalk delivery route after asynchronous job execution completes.

#### Scenario: Agent job succeeds
- **WHEN** an Agent job reaches SUCCEEDED with a final report
- **THEN** the system sends the report to the configured DingTalk delivery target, defaulting to the originating DingTalk conversation when no override is configured

#### Scenario: Agent job fails
- **WHEN** an Agent job reaches FAILED or TIMEOUT
- **THEN** the system sends a failure notice with a safe failure reason to the configured DingTalk delivery target

## REMOVED Requirements

### Requirement: DingTalk webhook requests are verified
**Reason**: DingTalk user message ingress is replaced by DingTalk Stream. The formal ingress no longer receives DingTalk user messages through a public HTTP webhook request that requires HTTP signature verification.

**Migration**: Use DingTalk Stream connector authentication and Stream session establishment with enterprise App Client ID/Secret or Stream-required credentials. If the HTTP route remains in code, it MUST be explicitly marked and configured as compatibility or local test ingress, not as the formal DingTalk user message ingress.

