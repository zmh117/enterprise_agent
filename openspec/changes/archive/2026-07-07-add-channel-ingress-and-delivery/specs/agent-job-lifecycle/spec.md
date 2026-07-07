## MODIFIED Requirements

### Requirement: Agent sessions and jobs are persisted
The system SHALL persist Agent sessions, Agent jobs, user messages, assistant messages, retry metadata, result summaries, failure reasons, source channel metadata, requester identity, routing context, and reply route in PostgreSQL 16 before or during the relevant lifecycle event.

#### Scenario: New diagnostic request is accepted
- **WHEN** a verified Channel request passes connector and permission checks
- **THEN** the system persists an Agent session, Agent job, user message, source channel metadata, requester identity, routing context, and reply route before publishing the job to the message bus

#### Scenario: Agent result is produced
- **WHEN** Agent execution completes with a final answer
- **THEN** the system persists the assistant message, result summary, job completion timestamp, and delivery-ready result artifact

#### Scenario: Legacy DingTalk request is accepted
- **WHEN** an existing DingTalk webhook request uses the legacy endpoint
- **THEN** the system persists equivalent generic channel fields while retaining backward-compatible DingTalk fields for existing read paths

### Requirement: Worker execution is idempotent
The system SHALL prevent duplicate RabbitMQ deliveries from executing the same Agent job concurrently or producing duplicate successful final result delivery attempts.

#### Scenario: Same job is delivered twice
- **WHEN** two workers receive the same job identifier
- **THEN** only one worker claims the executable job state and the other delivery is acknowledged or ignored according to the current persisted job state

#### Scenario: Completed job is delivered again
- **WHEN** a job that already reached SUCCEEDED and has a completed delivery attempt is delivered to a worker again
- **THEN** the system does not re-run the Agent and does not send duplicate final result chunks

## ADDED Requirements

### Requirement: Message bus payload remains channel agnostic
The system SHALL keep RabbitMQ job messages limited to internal execution identifiers such as `job_id` and `correlation_id`; external Channel payloads MUST be persisted before queue dispatch instead of embedded in the queue message.

#### Scenario: Channel request dispatches job
- **WHEN** a Channel request creates an Agent job
- **THEN** the message publisher sends only the job identifier and correlation identifier to the Agent job queue
