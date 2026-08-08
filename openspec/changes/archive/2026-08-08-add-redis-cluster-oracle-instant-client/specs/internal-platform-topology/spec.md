## ADDED Requirements

### Requirement: Topology bindings describe Redis mode and Oracle client options
The system SHALL allow base Redis bindings to declare connection mode (`standalone` or `cluster`) and cluster startup nodes, and SHALL allow Oracle base database bindings to declare client mode, optional SID vs service-name usage, optional connect descriptor, and Oracle SQL compatibility (`modern` or `legacy`). Omitted Redis mode SHALL default to standalone; omitted Oracle client/compat options SHALL use safe defaults that preserve existing behavior.

#### Scenario: Cluster Redis binding loaded from topology
- **WHEN** topology configuration for a base includes Redis `mode: cluster` and a list of startup nodes (with secrets resolved for password as today)
- **THEN** the resolved Redis resource binding exposes cluster mode and nodes for the gateway to use

#### Scenario: Oracle legacy binding loaded from topology
- **WHEN** topology configuration for an Oracle base includes thick/legacy-related options (client mode, compat, SID or connect descriptor)
- **THEN** the resolved database resource binding exposes those options without revealing secrets to the Agent

#### Scenario: Existing standalone Redis topology remains valid
- **WHEN** topology configuration omits Redis mode and only provides host/port/db/password refs as before
- **THEN** the platform treats the binding as standalone and continues to resolve successfully
