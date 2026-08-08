## MODIFIED Requirements

### Requirement: DingTalk message identity is parsed
The system SHALL parse the DingTalk Stream conversation identity, provider user identifiers, source connector, connector-configured tenant/corp identity, external event identity, and message content. Before permission checks or job creation, it SHALL resolve the provider identity to an enabled internal user and persist the internal requester ID together with a safe external identity reference.

#### Scenario: Bound user asks a diagnostic question
- **WHEN** a verified DingTalk Stream message contains a diagnostic question and its `tenant/corp + senderStaffId` binding resolves to an enabled internal user
- **THEN** the system persists the conversation, internal requester ID, external identity reference, source connector, external event identity and original user message

#### Scenario: Unbound user asks a question
- **WHEN** a verified DingTalk Stream message contains a sender identity with no enabled internal binding
- **THEN** the system records a safe identity denial, returns a safe rejection acknowledgement, and does not create an Agent session or job

## ADDED Requirements

### Requirement: DingTalk identity resolution is tenant isolated
The system SHALL resolve DingTalk identities using the tenant/corp associated with the ingress connector and MUST NOT share a binding solely because another tenant uses the same `senderStaffId`.

#### Scenario: Same staff ID appears in two tenants
- **WHEN** two enabled connectors from different tenants receive messages with the same `senderStaffId`
- **THEN** each message resolves only through its own tenant binding

### Requirement: DingTalk permission uses internal user roles
The system SHALL evaluate DingTalk Agent, tool and platform access using the resolved internal user and enabled roles, while preserving the external identity and connector only as source context and audit evidence.

#### Scenario: Web role grant enables DingTalk request
- **WHEN** an administrator grants an internal user's role access to the default diagnostic Agent and the user's bound DingTalk identity sends a request
- **THEN** DingTalk ingress observes the same role grant without duplicating a DingTalk-specific permission record
