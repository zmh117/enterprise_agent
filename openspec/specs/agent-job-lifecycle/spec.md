# agent-job-lifecycle Specification

## Purpose
TBD - created by archiving change add-readonly-diagnostic-agent-mvp. Update Purpose after archive.
## Requirements
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

### Requirement: Agent job status transitions are controlled
The system SHALL control Agent job status transitions through the job application service and support at least PENDING, RUNNING, SUCCEEDED, FAILED, and TIMEOUT states.

#### Scenario: Worker claims pending job
- **WHEN** an Agent worker starts executing a PENDING job
- **THEN** the system changes the job status to RUNNING and records the start timestamp

#### Scenario: Worker completes job
- **WHEN** an Agent worker produces a valid final report
- **THEN** the system changes the job status from RUNNING to SUCCEEDED and records the finish timestamp

#### Scenario: Worker hits timeout
- **WHEN** an Agent worker exceeds the configured execution timeout
- **THEN** the system changes the job status to TIMEOUT and records a safe timeout reason

### Requirement: Message bus is independent from Agent execution
The system SHALL implement RabbitMQ behind message bus publisher and consumer interfaces so Agent execution logic does not depend on RabbitMQ classes, channels, exchanges, or queue names.

#### Scenario: API server dispatches a job
- **WHEN** the API server creates an Agent job
- **THEN** it publishes the job through a message publisher interface instead of directly invoking RabbitMQ infrastructure from the Agent module

#### Scenario: Worker receives a job
- **WHEN** RabbitMQ delivers a job message
- **THEN** the message bus consumer passes the job identifier to an Agent job handler without exposing RabbitMQ delivery details to AgentExecutor

### Requirement: RabbitMQ queues support retry and dead letter handling
The system SHALL define RabbitMQ queues for normal job execution, delayed retry, and dead-letter handling.

#### Scenario: Retryable failure occurs
- **WHEN** Agent execution fails because of a retryable internal API, Loki, Claude, RabbitMQ, or database timeout or transient connectivity error
- **THEN** the system increments retry metadata and schedules the job on the retry queue until the configured retry limit is reached

#### Scenario: Retry limit is exceeded
- **WHEN** a retryable job has already used all configured retries
- **THEN** the system marks the job as FAILED and routes the message to the dead-letter path

#### Scenario: Non-retryable failure occurs
- **WHEN** Agent execution fails because of permission denial, unknown data source, rejected SQL policy, invalid tool argument, or unsupported user request
- **THEN** the system marks the job as FAILED without scheduling a retry

### Requirement: Worker execution is idempotent
The system SHALL prevent duplicate RabbitMQ deliveries from executing the same Agent job concurrently or producing duplicate successful final result delivery attempts.

#### Scenario: Same job is delivered twice
- **WHEN** two workers receive the same job identifier
- **THEN** only one worker claims the executable job state and the other delivery is acknowledged or ignored according to the current persisted job state

#### Scenario: Completed job is delivered again
- **WHEN** a job that already reached SUCCEEDED and has a completed delivery attempt is delivered to a worker again
- **THEN** the system does not re-run the Agent and does not send duplicate final result chunks

### Requirement: Message bus payload remains channel agnostic
The system SHALL keep RabbitMQ job messages limited to internal execution identifiers such as `job_id` and `correlation_id`; external Channel payloads MUST be persisted before queue dispatch instead of embedded in the queue message.

#### Scenario: Channel request dispatches job
- **WHEN** a Channel request creates an Agent job
- **THEN** the message publisher sends only the job identifier and correlation identifier to the Agent job queue

