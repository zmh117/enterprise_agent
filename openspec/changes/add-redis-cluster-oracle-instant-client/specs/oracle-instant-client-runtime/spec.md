## ADDED Requirements

### Requirement: Internal API Platform image bundles Oracle Instant Client
The system SHALL ship Oracle Instant Client libraries inside the `internal-api-platform` runtime image so that thick-mode Oracle connections can be initialized in container deployments without mounting client libraries from the host.

#### Scenario: Image contains Instant Client libraries
- **WHEN** the `internal-api-platform` image is built
- **THEN** Instant Client shared libraries are present in the image and discoverable via the configured library path environment

#### Scenario: Process initializes thick client when libraries exist
- **WHEN** the platform process starts and Instant Client libraries are present
- **THEN** the process initializes oracledb thick mode once successfully (or records a clear startup failure if initialization fails)

#### Scenario: Other service images stay without Instant Client
- **WHEN** `api-server` or `agent-worker` images are built
- **THEN** those images are not required to include Oracle Instant Client
