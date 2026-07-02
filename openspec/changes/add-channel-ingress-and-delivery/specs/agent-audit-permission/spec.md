## MODIFIED Requirements

### Requirement: Users must be authorized before Agent job creation
The system SHALL check requester allowlists, service account permissions, connector ingress authorization, and service or project allowlists before creating an Agent job from any Channel message.

#### Scenario: Authorized user submits request
- **WHEN** a verified Channel requester is allowed to use the Agent for the requested service or project and the source connector allows ingress
- **THEN** the system creates the Agent job and records the permission decision

#### Scenario: Unauthorized user submits request
- **WHEN** a verified Channel requester is not allowed to use the Agent or target service or project
- **THEN** the system rejects the request, records the permission denial, and does not publish an Agent job

#### Scenario: Connector is not authorized for ingress
- **WHEN** a request uses a connector that is disabled or not allowed for ingress
- **THEN** the system rejects the request, records the connector authorization failure, and does not publish an Agent job

### Requirement: Audit events are persisted across the execution chain
The system SHALL persist audit events for Channel receipt, signature or token verification, identity parsing, ignored events, connector authorization, permission decisions, job creation, queue dispatch, worker claim, tool calls, result creation, failures, retries, delivery attempts, delivery chunks, and final delivery status.

#### Scenario: Job completes successfully
- **WHEN** an Agent job is accepted, executed, and delivered through its configured reply route
- **THEN** the audit trail includes records linking the original Channel request, job, tool calls, final report, delivery attempt, and delivery chunks

#### Scenario: Job fails before execution
- **WHEN** a job is rejected before Agent runtime starts
- **THEN** the audit trail includes the rejection reason and no tool execution records

#### Scenario: Grafana event is ignored
- **WHEN** a Grafana event is ignored because it is not `firing`
- **THEN** the audit trail records the connector, external event ID, ignored reason, and safe payload summary

### Requirement: Configuration is persisted for future web management
The system SHALL store permission policies, tool enablement, connector metadata, connector direction flags, delivery metadata, and data source registry entries in PostgreSQL so a later web service can manage them without redesigning core persistence.

#### Scenario: Administrator later changes tool access
- **WHEN** a future web service updates tool enablement or permission policy
- **THEN** the Agent runtime can read the updated PostgreSQL-backed configuration without requiring a code change

#### Scenario: Administrator later changes connector direction
- **WHEN** a future web service disables delivery on a connector
- **THEN** new jobs cannot select that connector as a delivery route until it is enabled again
