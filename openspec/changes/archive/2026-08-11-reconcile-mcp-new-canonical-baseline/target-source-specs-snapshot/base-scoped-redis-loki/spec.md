## Purpose

Define read-only Redis and Loki routing rules for base-level resources with workshop-level isolation through key prefixes and labels.
## Requirements
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

### Requirement: Redis and Loki errors are classified and desensitized
The system SHALL classify Redis and Loki connection timeouts and transient upstream failures as retryable, classify policy violations as non-retryable, and desensitize credentials in all error messages.

#### Scenario: Upstream timeout is retryable
- **WHEN** a base Redis or Loki upstream times out or returns a transient error
- **THEN** the platform returns a retryable error with no credentials in the message

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

### Requirement: Redis 和 Loki 必须由已发布 Resource Revision 提供
Redis 与 Loki 的地址、认证、tenant/数据库号及查询边界 MUST 来自业务应用发布绑定的具体 Resource Revision，并被复制到 Job Execution Scope。

#### Scenario: Redis 发布新 revision
- **WHEN** Redis Resource Identity 发布新 revision 但应用未重新发布
- **THEN** 已发布应用和新建 Job 继续使用原绑定 revision

#### Scenario: Loki 请求覆盖 tenant
- **WHEN** 工具参数请求与绑定 revision 不同的 tenant
- **THEN** 平台必须拒绝或强制使用绑定 tenant，不能扩大范围

### Requirement: Redis 字段契约必须统一
Redis Resource MUST 使用 `host`、`port`、`database`、可选 `username`、`password_ref` 和受控 TLS 配置；管理 API、前端、验证器和运行时不得使用相互不兼容的 `db/user` 别名。

#### Scenario: 旧字段被导入
- **WHEN** import 遇到旧 `db` 或 `user` 字段
- **THEN** 导入器必须显式转换为 canonical 字段并生成 Draft，不能直接发布

### Requirement: Loki 字段契约必须统一
Loki Resource MUST 使用 `base_url`、可选 `tenant_id`、认证 Secret reference、超时和查询上限；管理 API、前端和运行时必须共享同一 schema。

#### Scenario: Draft 使用旧 tenant 字段
- **WHEN** 新建 Draft 直接提交歧义字段 `tenant`
- **THEN** API 必须拒绝或通过有审计的导入转换为 `tenant_id`

### Requirement: Secret 缺失必须阻止相关资源而非回退
Redis 或 Loki Published Revision 的 Secret 无法解析时，系统 MUST 保留 Last Known Good；没有 LKG 时仅阻止依赖该资源的应用。

#### Scenario: Redis 密码 Secret 被禁用
- **WHEN** runtime reload 无法解析 Redis `password_ref`
- **THEN** Redis revision 标为 degraded，且不得从 env 或旧配置回退

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
