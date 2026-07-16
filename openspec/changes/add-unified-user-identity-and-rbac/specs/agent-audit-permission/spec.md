## MODIFIED Requirements

### Requirement: Users must be authorized before Agent job creation
The system SHALL resolve every human Channel requester to an enabled internal user, expand enabled role membership, and check connector ingress authorization, Agent use permission, project/service permission, and applicable platform access grants before creating an Agent job. External provider identifiers MUST NOT be treated as standalone permission principals after unified identity is enabled.

#### Scenario: Authorized user submits request
- **WHEN** a verified Channel identity resolves to an enabled internal user whose direct or role permissions allow the selected Agent and requested service or project, and the source connector allows ingress
- **THEN** the system creates the Agent job with the internal requester ID and records the identity and permission decisions

#### Scenario: Unauthorized user submits request
- **WHEN** a verified internal user is not allowed to use the selected Agent or target service or project
- **THEN** the system rejects the request, records the permission denial, and does not publish an Agent job

#### Scenario: External identity is not bound
- **WHEN** a human Channel requester cannot be resolved to an enabled internal user
- **THEN** the system rejects the request, records identity resolution denial, and does not create or publish an Agent job

#### Scenario: Connector is not authorized for ingress
- **WHEN** a request uses a connector that is disabled or not allowed for ingress
- **THEN** the system rejects the request, records the connector authorization failure, and does not publish an Agent job

### Requirement: Tool access is policy checked
The system SHALL check code registration, tool enablement, selected Agent publication assignment, internal user and role tool permissions, source access, platform data scope, and read-only risk policy before exposing or executing each Agent tool call.

#### Scenario: Allowed read-only tool call
- **WHEN** an enabled read-only tool is assigned to the job's Agent publication and the internal user is allowed for both the tool and requested data scope
- **THEN** the system executes the tool call and records the policy decision

#### Scenario: Disallowed tool call
- **WHEN** Agent requests a disabled tool, a tool absent from its publication, a tool denied to the user or roles, an out-of-scope source, or a non-read-only operation
- **THEN** the system rejects the tool call and records the policy decision

## ADDED Requirements

### Requirement: Identity and RBAC lifecycle changes are audited
The system SHALL audit user creation and disablement, password/session security events, role and membership changes, external identity binding lifecycle, Agent configuration validation/publication/rollback, and permission denials using internal actor IDs and secret-safe summaries.

#### Scenario: Administrator binds DingTalk identity
- **WHEN** an authenticated administrator binds a DingTalk identity to an internal user
- **THEN** the audit records actor, target user, external identity record, tenant/connector summary, action, before/after state and correlation ID without storing credentials or full provider payload

#### Scenario: Role permission is changed
- **WHEN** an administrator adds or removes a role policy
- **THEN** the audit records the role, safe policy summary, revision and actor
