## MODIFIED Requirements

### Requirement: Users must be authorized before Agent job creation
The system SHALL check connector ingress authorization and the access policy applicable to the resolved Trigger before creating an Agent job from any Channel message. For DingTalk messages resolved to an active Business Application Publication, the system SHALL authorize application access when the actual sender maps to an enabled internal user and MUST NOT require an additional application user allowlist, role, or Capability `use` grant; other Trigger types SHALL retain their defined requester, service-account, service, project, or role policies.

#### Scenario: Authorized user submits request
- **WHEN** a verified Channel requester satisfies the access policy for the resolved Trigger and the source connector allows ingress
- **THEN** the system creates the Agent job and records the permission decision

#### Scenario: Unauthorized user submits request
- **WHEN** a verified Channel requester does not satisfy the access policy for the resolved Trigger or target service or project
- **THEN** the system rejects the request, records the permission denial, and does not publish an Agent job

#### Scenario: Connector is not authorized for ingress
- **WHEN** a request uses a connector that is disabled or not allowed for ingress
- **THEN** the system rejects the request, records the connector authorization failure, and does not publish an Agent job

#### Scenario: DingTalk sender resolves to an enabled user
- **WHEN** a DingTalk message hits a connector bound to an active Application Publication and the actual sender maps to an enabled internal user
- **THEN** the system authorizes access to that application without requiring a separate application user allowlist, role, or Capability grant

#### Scenario: DingTalk sender is unbound or disabled
- **WHEN** the actual DingTalk sender has no enabled internal identity or the internal user is disabled
- **THEN** the system rejects job creation, records a safe reason, and returns an understandable binding or account-status prompt

### Requirement: Tool access is policy checked
The system SHALL check tool allowlists, source access, read-only risk policy and the governance policy applicable to each Tool before execution. For a governed API Capability, the system MUST check the frozen Agent Capability Envelope, Application Capability Allowlist, exact Release status, current user Provider availability, External Execution Subject Snapshot and current personal credential; it MUST NOT require a separate per-user or per-role Capability Code `use` grant.

#### Scenario: Allowed read-only tool call
- **WHEN** Agent requests an enabled internal read-only tool within the user's allowed scope
- **THEN** the system executes the tool call and records the policy decision

#### Scenario: Disallowed tool call
- **WHEN** Agent requests a disabled tool, out-of-scope source, non-read-only operation, or Tool outside the current publication snapshot
- **THEN** the system rejects the tool call and records the policy decision

#### Scenario: Governed Capability is fully allowed
- **WHEN** the exact Capability Release belongs to both the frozen Agent Envelope and Application Allowlist, remains runnable, and the current user binding, Team and Token are valid
- **THEN** the system executes the call and records each governance dimension without checking a separate Capability role grant

#### Scenario: Application did not allow Capability
- **WHEN** the Agent Envelope includes the Release but the Application Allowlist does not
- **THEN** the system rejects the call before external network access and records the missing application authorization dimension

### Requirement: Tool calls are recorded with safe summaries
The system SHALL persist tool call records with sanitized request payload summaries, bounded normalized response summaries, status, duration, risk level, audit linkage, and platform or Capability Release outcome details when available. For governed external APIs, the system MUST record Release and attempt metadata but MUST NOT persist authentication material, raw HTTP request/response bodies or unbounded external content.

#### Scenario: Database tool succeeds
- **WHEN** `query_database` returns evidence through the Internal API Platform
- **THEN** the system records the tool name, sanitized request summary, bounded response summary, duration, status, risk level, related audit event, and platform request metadata if provided

#### Scenario: Tool call returns sensitive or large data
- **WHEN** a tool response contains sensitive fields or exceeds inline storage limits
- **THEN** the system stores a masked or summarized response in PostgreSQL and avoids persisting raw sensitive payloads in the tool call row

#### Scenario: Internal platform rejects a tool call
- **WHEN** the Internal API Platform rejects a tool call because of authorization, data-source policy, query policy, or malformed parameters
- **THEN** the system records a failed tool call with a safe rejection reason, duration, risk level, and audit event without exposing platform secrets

#### Scenario: Governed external API call succeeds after retry
- **WHEN** a QUERY Capability succeeds after one or more HTTP attempts
- **THEN** the system records one linked Tool Call and separate safe attempt metadata containing identifiers, classification, duration, size and status, without raw body, Token, Cookie or authentication Header

#### Scenario: Governed external output is INTERNAL
- **WHEN** a Capability returns bounded normalized INTERNAL data
- **THEN** the Tool Call summary preserves user, Application Publication, Capability Release and classification provenance and remains subject to the existing Job access boundary
