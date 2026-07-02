## MODIFIED Requirements

### Requirement: DingTalk message identity is parsed
The system SHALL parse DingTalk conversation identity, DingTalk user identity, DingTalk message identity, source channel, delivery route, and user message content into the generic Channel event needed to create an Agent session and Agent job.

#### Scenario: User asks a diagnostic question
- **WHEN** a verified DingTalk message contains a user diagnostic question
- **THEN** the system persists the DingTalk identity as generic requester/source metadata, persists the source channel, delivery route, and original user message, and creates the Agent job through the Channel ingress service

### Requirement: DingTalk receives final Agent results
The system SHALL send the final Agent report or failure notice through the job's configured delivery route when that route targets DingTalk, rather than assuming every DingTalk-originated job replies to the originating conversation.

#### Scenario: Agent job succeeds with original conversation delivery
- **WHEN** an Agent job reaches SUCCEEDED and its delivery route targets the originating DingTalk conversation
- **THEN** the system sends the report to that DingTalk conversation

#### Scenario: Agent job succeeds with DingTalk webhook robot delivery
- **WHEN** an Agent job reaches SUCCEEDED and its delivery route targets a DingTalk webhook robot connector
- **THEN** the system sends the report through that connector instead of the originating conversation callback

#### Scenario: Agent job fails
- **WHEN** an Agent job reaches FAILED or TIMEOUT and its delivery route targets DingTalk
- **THEN** the system sends a safe failure notice through the configured DingTalk delivery route

## ADDED Requirements

### Requirement: DingTalk robots can be configured for ingress and delivery
The system SHALL support DingTalk enterprise robots and DingTalk webhook robots as configurable connectors that can allow ingress, delivery, or both.

#### Scenario: DingTalk robot is ingress enabled
- **WHEN** a DingTalk robot connector is configured with `allow_ingress=true`
- **THEN** valid messages from that connector can create Agent jobs through the Channel ingress service

#### Scenario: DingTalk robot is delivery enabled
- **WHEN** a DingTalk robot connector is configured with `allow_delivery=true`
- **THEN** Agent results can be delivered through that connector's DingTalk adapter
