## ADDED Requirements

### Requirement: DingTalk Stream connection lifecycle is audited
The system SHALL persist audit events for DingTalk Stream connector startup, successful connection, disconnect, reconnect attempt, reconnect success, configuration failure, and permanent connector failure.

#### Scenario: Stream connector reconnects
- **WHEN** DingTalk Stream ingress loses connection and reconnects successfully
- **THEN** the audit trail records disconnect, reconnect attempt, reconnect success, connector ID, and timestamps

### Requirement: DingTalk Stream ingress permission is checked before job creation
The system SHALL check connector enablement, user allowlists, and project or service allowlists before creating an Agent job from a DingTalk Stream message.

#### Scenario: Authorized Stream user submits request
- **WHEN** a DingTalk Stream user is allowed to use the Agent for the requested project or service
- **THEN** the system creates the Agent job and records the permission decision with Stream event linkage

#### Scenario: Unauthorized Stream user submits request
- **WHEN** a DingTalk Stream user is not allowed to use the Agent or requested project or service
- **THEN** the system rejects the Stream message, records the permission denial, and does not publish an Agent job

### Requirement: DingTalk Stream message handling is audited end to end
The system SHALL persist audit events linking the Stream event receipt, identity parsing, idempotency decision, permission decision, job creation, queue dispatch, worker execution, final artifact, and DingTalk delivery result.

#### Scenario: Stream job completes successfully
- **WHEN** an Agent job created from DingTalk Stream completes and is delivered to DingTalk
- **THEN** the audit trail links the original Stream event, Agent job, tool calls, final report, and delivery result

#### Scenario: Stream message fails before execution
- **WHEN** a DingTalk Stream message is rejected before Agent runtime starts
- **THEN** the audit trail includes the rejection reason and no tool execution records
