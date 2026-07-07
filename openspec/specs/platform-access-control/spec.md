## Purpose

Define platform-side authorization for internal tool requests so Agent permissions and platform topology access remain independently auditable.

## Requirements

### Requirement: Platform enforces environment/base/workshop access scope
The system SHALL enforce a platform-side access scope that limits which environments, bases, and workshops a user may query, independent of and in addition to the Agent-side tool permission check.

#### Scenario: In-scope request allowed
- **WHEN** a user authorized for `sanjiu`/`guanlan`/`GL001` issues a tool request for that target
- **THEN** the platform allows the request to proceed to resolution and execution

#### Scenario: Out-of-scope base rejected
- **WHEN** a user authorized only for `sanjiu` issues a request targeting `mmk`
- **THEN** the platform rejects the request with a non-retryable authorization error

#### Scenario: Out-of-scope workshop rejected
- **WHEN** a user authorized for workshop `GL001` issues a request targeting `GL002`
- **THEN** the platform rejects the request as unauthorized

### Requirement: Platform validates caller identity from request context
The system SHALL identify the caller from request context (e.g. user and correlation headers) and MAY require a platform authorization token, and SHALL treat missing or invalid identity as unauthorized.

#### Scenario: Missing identity rejected
- **WHEN** a tool request arrives without a resolvable caller identity
- **THEN** the platform rejects the request as unauthorized and records the rejection

### Requirement: Access decisions are audited without leaking secrets
The system SHALL audit access-control decisions (allow/deny) with the resolved target and caller, and SHALL NOT record credentials, connection details, or unbounded raw payloads.

#### Scenario: Denied access is audited
- **WHEN** the platform denies a request for being out of scope
- **THEN** it records an audit entry containing the caller, the requested environment/base/workshop, and the deny reason, without any secret material
