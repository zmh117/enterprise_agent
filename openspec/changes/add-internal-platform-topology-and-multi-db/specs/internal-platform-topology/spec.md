## ADDED Requirements

### Requirement: Platform models an environment/base/workshop topology
The system SHALL model a three-level topology: Environment (e.g. `sanjiu`, `mmk`), Base identified by a business code (e.g. `guanlan`), and Workshop identified by a workshop code (e.g. `GL001`). A Workshop SHALL be a logical partition inside a Base, not an independently connected resource.

#### Scenario: Full three-tier topology
- **WHEN** the platform loads a topology containing environment `sanjiu` with base `guanlan` and workshops `GL001` and `GL002`
- **THEN** both workshops resolve to the same base-level database, Redis, and Loki resources and are distinguished only by naming (table prefix, key prefix, log label)

#### Scenario: Degenerate topology without workshops
- **WHEN** the platform loads environment `mmk` whose base has no workshop layer
- **THEN** database, Redis, and Loki resources resolve at the base level and workshop-specific naming constraints are not required

### Requirement: Bases are addressed by business code, not IP
The system SHALL address bases using a stable business code (e.g. `guanlan`) rather than an IP address, while connection details (host/IP, port) SHALL be internal configuration not exposed to the Agent or the model.

#### Scenario: Agent addresses a base by code
- **WHEN** a tool request references base `guanlan`
- **THEN** the platform resolves the base by code and never requires the caller to supply an IP address

### Requirement: Database engine is defined per base
The system SHALL define exactly one database engine (`mysql`, `sqlserver`, or `oracle`) per base. All workshops within a base SHALL share that base's engine.

#### Scenario: Workshops inherit base engine
- **WHEN** base `guanlan` is configured with engine `mysql`
- **THEN** queries for workshops `GL001` and `GL002` both execute against the MySQL engine of base `guanlan`

### Requirement: Topology is loaded from YAML and seed configuration
The system SHALL load topology and connection configuration from YAML and seed files for this change, and SHALL reference secrets by identifier rather than storing plaintext credentials in topology files. The system SHALL keep a path open to migrate topology into a database registry later without changing the tool contract.

#### Scenario: Topology loaded from YAML
- **WHEN** the platform starts with a topology YAML describing `sanjiu`/`guanlan`/`GL001`,`GL002` and `mmk`
- **THEN** the platform exposes the resolved topology and rejects tool requests for environments, bases, or workshops not present in the configuration

#### Scenario: Secrets are referenced, not inlined
- **WHEN** a base database connection requires a password
- **THEN** the topology configuration references a secret identifier and the plaintext secret is resolved from environment or a secret source, never stored in the topology file

### Requirement: Structured addressing resolves to a concrete resource binding
The system SHALL resolve `environment` + `base` + optional `workshop` + resource kind (`database`/`redis`/`loki`) into a concrete resource binding before executing any query.

#### Scenario: Unknown target is rejected
- **WHEN** a tool request references an environment, base, or workshop that is not in the topology
- **THEN** the platform returns a non-retryable resolution error and does not attempt any upstream connection

#### Scenario: Missing workshop for a partitioned base
- **WHEN** a database request targets a base whose data is workshop-partitioned but omits the workshop code
- **THEN** the platform rejects the request with a clear error instead of guessing a workshop
