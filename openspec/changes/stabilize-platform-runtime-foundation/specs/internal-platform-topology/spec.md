## MODIFIED Requirements

### Requirement: Topology is loaded from YAML and seed configuration
The system SHALL persist topology in PostgreSQL and SHALL resolve runtime connections only from Published Resource Revisions. YAML and seed configuration MAY be used only for bootstrap or explicit import into Draft records; they MUST NOT directly override or replace an effective runtime snapshot.

#### Scenario: Topology imported from YAML
- **WHEN** an administrator explicitly imports YAML describing environments, bases, workshops and legacy resource data
- **THEN** the platform creates or updates topology and Resource Draft records that require validation and publication

#### Scenario: Secrets are referenced, not inlined
- **WHEN** an imported base connection requires a password
- **THEN** import must map it to a platform Secret migration; no plaintext is stored in topology or Resource Revision

#### Scenario: Database runtime configuration is invalid
- **WHEN** a Published Resource Revision fails to load but legacy YAML remains available
- **THEN** the platform keeps Last Known Good or blocks the affected application and MUST NOT fall back to YAML

### Requirement: Structured addressing resolves to a concrete resource binding
The system SHALL resolve `environment` + `base` + optional `workshop` + resource slot into the exact Resource Revision fixed by the Business Application Publication and Job Execution Scope before executing any query.

#### Scenario: Unknown target is rejected
- **WHEN** a tool request references an environment, base, or workshop absent from the Job Execution Scope
- **THEN** the platform returns a non-retryable resolution error and does not attempt any upstream connection

#### Scenario: Missing workshop for a partitioned base
- **WHEN** a database request targets a partitioned base but the fixed Job scope has no workshop
- **THEN** the platform rejects the request instead of guessing a workshop

#### Scenario: Floating resource version exists
- **WHEN** the same Resource Identity has a newer revision than the one bound to the Job
- **THEN** resolution returns the Job-bound revision and never floats to the newer revision
