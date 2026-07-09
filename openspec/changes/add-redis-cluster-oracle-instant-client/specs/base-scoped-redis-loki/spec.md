## ADDED Requirements

### Requirement: Base Redis may use standalone or cluster mode
The system SHALL connect to a base Redis upstream using either standalone or cluster mode as declared in the base Redis binding. The default mode SHALL be standalone. Workshop key-prefix isolation and read-only command policy SHALL apply equally in both modes.

#### Scenario: Standalone mode uses single-node client
- **WHEN** a base Redis binding is configured with mode `standalone` (or omits mode)
- **THEN** the platform connects with a single-node Redis client using the configured host, port, db, and password

#### Scenario: Cluster mode uses cluster client
- **WHEN** a base Redis binding is configured with mode `cluster` and one or more startup nodes
- **THEN** the platform connects with a Redis Cluster client using those startup nodes and password, and does not rely on a logical `db` index

#### Scenario: Workshop prefix still enforced on cluster
- **WHEN** a Redis GET or SCAN for workshop `GL001` runs against a cluster-mode base
- **THEN** the platform still accepts only keys/patterns within the `GL001` namespace and rejects cross-workshop or unbounded patterns

#### Scenario: Cluster configuration missing nodes is rejected
- **WHEN** a base Redis binding declares mode `cluster` without usable startup nodes
- **THEN** the platform rejects the configuration (or resolution) with a clear non-retryable error before attempting upstream access
