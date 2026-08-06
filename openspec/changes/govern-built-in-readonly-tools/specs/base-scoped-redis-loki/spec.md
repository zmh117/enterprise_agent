## MODIFIED Requirements

### Requirement: Redis and Loki resolve at the base level
The system SHALL allow Redis to resolve from an exact Environment-level or Base-level Resource Mapping and to be inherited by child Workshops through their frozen namespace policies. Loki SHALL instead resolve from an exact global or Environment-level Resource Mapping plus an Environment and optional Base Scope Policy; Loki MUST NOT require a Base, Workshop or placement-level connection binding.

#### Scenario: Redis routed to base upstream
- **WHEN** a Redis request targets Environment `sanjiu`, Base `guanlan`, Workshop `GL001`
- **THEN** the platform uses the base Resource Revision frozen by the Job and applies GL001's namespace Policy Revision

#### Scenario: Redis routed to environment upstream
- **WHEN** an Environment has no Base layer and its Job freezes one environment-level Redis Resource Revision
- **THEN** the platform uses that revision without creating a default Base or Workshop policy

#### Scenario: Loki routed through global upstream
- **WHEN** an Application Publication maps Environment `sanjiu-test1` to a global Loki Resource Revision and an exact Scope Policy
- **THEN** the platform queries that upstream and injects the Policy's Environment and optional Base selector

#### Scenario: Loki routed through environment upstream
- **WHEN** an Application Publication maps one Environment to its own Loki Resource Revision
- **THEN** the platform uses that exact revision and Scope Policy without considering cloud/edge placement

### Requirement: Workshop is distinguished by Redis key prefix
The system SHALL constrain Workshop-scoped Redis reads using one or more exact complete namespace prefixes stored in the Job's frozen Workshop Partition Policy Revision. It SHALL allow only GET and bounded SCAN, require a complete prefix before any wildcard, and reject cross-namespace, regex or unbounded patterns.

#### Scenario: Key within workshop prefix accepted
- **WHEN** a Redis GET for Workshop `GL001` targets a key beginning with `cr999.crmes.CRMES_TEST_GL#GL001@$`
- **THEN** the platform executes the read against the exact frozen Resource Revision

#### Scenario: Key outside workshop prefix rejected
- **WHEN** a Redis request for Workshop `GL001` targets a key in the `CZ002` namespace or uses `*GL001*`
- **THEN** the platform rejects the request as a policy violation before contacting Redis

#### Scenario: Mutating Redis command rejected
- **WHEN** a Redis request uses a non-read command such as `SET`, `DEL`, `EXPIRE`, `FLUSHDB` or `EVAL`
- **THEN** the platform rejects it as not read-only

#### Scenario: Base has no workshop layer
- **WHEN** Redis is bound to an effective Environment or Base leaf without Workshops
- **THEN** the platform uses the frozen unpartitioned target scope and does not require a synthetic key prefix

## REMOVED Requirements

### Requirement: Workshop is distinguished by Loki label
**Reason**: 现有 Loki 标签契约不能可靠表达逻辑 Workshop；物理 `workshop` 可能表示 Base，`replica` 只在部分应用中映射 Workshop，而 `role` 表示采集侧。继续自动注入 Workshop 会产生错误隔离声明。

**Migration**: 为每个有效 Environment 和可选 Base 创建、验证并发布精确 Loki Scope Selector Policy；新的 Application Publication 冻结 global 或 environment Loki Resource Revision 与该 Policy。删除运行时自动注入 `workshop=<Workshop code>` 的路径，`role`、`replica`、`app`、`logtype` 只保留为受控诊断过滤。

## ADDED Requirements

### Requirement: Loki scope is enforced by environment and optional base selector policy
The system SHALL constrain Loki queries using the exact Environment and optional Base Scope Policy frozen by the Job, independent of whether the Job's business target contains a Workshop. Multiple Bases in one Environment MUST use separate named policies rather than OR conditions.

#### Scenario: Environment-only Loki query
- **WHEN** a Scope Policy maps `customer=sanjiu-test1` to one Environment without a Base condition
- **THEN** every runtime query includes that exact mandatory condition

#### Scenario: Base-scoped Loki query
- **WHEN** a Scope Policy maps `customer=sanjiu-test1 AND workshop=guanlan` to Base `guanlan`
- **THEN** every runtime query includes both exact conditions and treats the physical `workshop` value as a Base mapping

#### Scenario: Workshop Job does not add a label
- **WHEN** a Job target is `sanjiu-test1/guanlan/GL001`
- **THEN** the effective Loki selector remains the frozen Environment/Base Policy and does not add `GL001`, replica or placement conditions automatically
