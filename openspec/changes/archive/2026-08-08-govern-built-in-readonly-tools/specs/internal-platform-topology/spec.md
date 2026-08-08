## MODIFIED Requirements

### Requirement: Platform models an environment/base/workshop topology
The system SHALL model only the topology levels that exist for a deployment: Environment, optional Base within that Environment, and optional Workshop within that Base. A Workshop SHALL be a logical partition inside a Base rather than an independently connected business target, and the platform MUST NOT create phantom `default` or `none` nodes to fill absent levels.

#### Scenario: Full three-tier topology
- **WHEN** the platform stores environment `sanjiu` with base `guanlan` and workshops `GL001` and `GL002`
- **THEN** both workshops are distinct logical targets that may inherit the same base-level DB or Redis connection and remain isolated by published partition policies

#### Scenario: Environment without a base
- **WHEN** a deployment has one environment-level database or Redis and no business base or workshop
- **THEN** the Environment is the effective leaf target and no synthetic Base or Workshop is created

#### Scenario: Base without workshops
- **WHEN** an Environment contains a Base whose data is not divided into workshops
- **THEN** the Base is the effective leaf target and no workshop-specific partition policy is required

#### Scenario: Child is submitted without its parent
- **WHEN** configuration attempts to create a Workshop without a real Base or a Base without a real Environment
- **THEN** the platform rejects the invalid topology relationship

### Requirement: Database engine is defined per base
The system SHALL derive the database engine from the exact Published Database Resource Revision selected for the effective Environment or Base target. All Workshops inheriting one selected parent resource SHALL use that revision's engine, while a different placement MAY select another revision only when it declares a compatible engine and the same Workshop partition policy semantics.

#### Scenario: Workshops inherit base engine
- **WHEN** base `guanlan` is mapped to a MySQL Resource Revision for workshops `GL001` and `GL002`
- **THEN** both workshops execute against that revision's MySQL engine and apply their own frozen table-prefix policies

#### Scenario: Environment has no base
- **WHEN** an Environment leaf is mapped directly to a SQL Server Resource Revision
- **THEN** database requests resolve that engine without requiring a Base code

#### Scenario: Cloud and edge engines disagree
- **WHEN** the same logical target's cloud and edge database mappings declare incompatible engines for one tool contract
- **THEN** Application Publish rejects the mapping instead of changing SQL semantics by placement

### Requirement: Structured addressing resolves to a concrete resource binding
The system SHALL resolve the Job's actual `environment` + optional `base` + optional `workshop` Business Target Path, logical resource slot, and optional placement into the exact Resource Revision and policy revisions frozen by the Application Publication before executing any query.

#### Scenario: Unknown target is rejected
- **WHEN** a tool request references an Environment, Base, or Workshop absent from the Job Execution Snapshot
- **THEN** the platform returns a non-retryable resolution error and does not attempt any upstream connection

#### Scenario: Omitted absent level is accepted
- **WHEN** a Job targets an Environment that has no Base or Workshop levels and omits those fields
- **THEN** the platform resolves the environment-level Mapping without inventing missing codes

#### Scenario: Missing workshop for a partitioned base
- **WHEN** a database or Redis request targets a Base with Workshop children but the Job scope has no Workshop
- **THEN** the platform rejects the request instead of guessing a Workshop or using an unpartitioned parent view

#### Scenario: Floating resource version exists
- **WHEN** the same Resource Identity has a newer revision than the one bound to the Job
- **THEN** resolution returns the Job-bound revision and never floats to the newer revision

#### Scenario: Resource mapping is ambiguous
- **WHEN** the frozen mapping data produces zero or multiple candidates for one slot, target and placement
- **THEN** resolution fails closed and does not use a first, latest, default or closest-scope fallback

## ADDED Requirements

### Requirement: Resource placement must be independent from business topology
The system SHALL model optional Resource Placement separately from Environment/Base/Workshop, with first-phase values `cloud` and `edge`; placement MUST NOT create topology nodes or alter the logical identity of a Base or Workshop.

#### Scenario: Same workshop has cloud and edge resources
- **WHEN** GL001 has both cloud and edge database Resource Revisions
- **THEN** both mappings target the same Environment/Base/Workshop path and differ only by placement

#### Scenario: Resource has no placement dimension
- **WHEN** a deployment has one resource for an effective target
- **THEN** its mapping omits placement and the API rejects `none` or `default` placeholders

#### Scenario: Placement is used as a base code
- **WHEN** configuration attempts to create `guanlan_cloud` and `guanlan_edge` as pseudo-Bases solely to represent resource location
- **THEN** validation rejects or migration reports those pseudo-nodes for explicit normalization
