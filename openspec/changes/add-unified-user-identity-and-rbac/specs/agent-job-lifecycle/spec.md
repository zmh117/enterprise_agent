## MODIFIED Requirements

### Requirement: Agent sessions and jobs are persisted
The system SHALL persist Agent sessions, Agent jobs, user messages, assistant messages, retry metadata, result summaries, failure reasons, source channel metadata, internal requester identity, safe external identity reference, routing context, reply route, selected Agent definition, immutable publication ID, publication revision, and config hash in PostgreSQL before or during the relevant lifecycle event.

#### Scenario: New diagnostic request is accepted
- **WHEN** a verified Channel request resolves to an authorized internal user and passes connector, Agent, project and permission checks
- **THEN** the system persists an Agent session, Agent job, user message, source channel metadata, internal requester identity, safe external identity reference, routing context, reply route, and fixed Agent publication before publishing the job to the message bus

#### Scenario: Agent result is produced
- **WHEN** Agent execution completes with a final answer
- **THEN** the system persists the assistant message, result summary, job completion timestamp, delivery-ready result artifact, and the Agent config version used for execution

#### Scenario: Legacy DingTalk request is read
- **WHEN** an existing historical DingTalk row predates unified identity or Agent publications
- **THEN** the system retains backward-compatible DingTalk/requester fields and uses an explicit legacy runtime path without silently rewriting historical identity

## ADDED Requirements

### Requirement: Job retries preserve identity and Agent publication
The system SHALL preserve the internal requester, external identity reference, Agent publication ID, revision and config hash across queue retries and duplicate deliveries.

#### Scenario: Agent publication changes before retry
- **WHEN** a retryable job is waiting and an administrator publishes a new Agent version
- **THEN** the retry uses the original fixed publication

#### Scenario: Duplicate job delivery occurs
- **WHEN** RabbitMQ redelivers the same job
- **THEN** idempotent claim and execution use the same persisted internal requester and Agent publication
