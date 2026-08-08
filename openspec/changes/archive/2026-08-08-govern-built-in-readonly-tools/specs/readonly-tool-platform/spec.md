## MODIFIED Requirements

### Requirement: Tool definitions are persisted
The system SHALL persist governance metadata for exact Built-in Tool Releases, Agent Tool Envelopes and Application Tool Allowlists, while the executable definition itself MUST originate from the code Manifest. Runtime tool preparation MUST use the exact Release ID, Handler Version and Implementation Digest frozen by the Job instead of a name-only enabled flag.

#### Scenario: Tool registry is loaded
- **WHEN** the Agent runtime prepares available tools for a job
- **THEN** it intersects the code Registry with the Job's exact Tool Releases, Application Allowlist, stable tool-use grants, target scope and resource-policy readiness

#### Scenario: Database attempts to define implementation
- **WHEN** a persisted tool record contains executable SQL, script, arbitrary URL or another dynamic implementation field
- **THEN** runtime rejects the record and never executes it

#### Scenario: legacy-v1 name-only binding is encountered after removal
- **WHEN** a new or recoverable Job lacks an exact Tool Execution Snapshot and only references `legacy-v1`
- **THEN** runtime rejects execution and reports a non-retryable migration error

### Requirement: Database query tool is read-only
The system SHALL allow database tool execution only for policy-approved read operations against the exact Resource Revision and Workshop Partition Policy Revision frozen by the Job. It MUST reject insert, update, delete, DDL, privileged, unsafe, unparseable, multi-statement or cross-prefix queries before accessing the data source, and SHALL apply dialect-aware table-prefix checks to every physical table reference.

#### Scenario: Select query is approved
- **WHEN** Agent calls `query_database` with a policy-approved read query whose every table matches the frozen Workshop prefix
- **THEN** the Internal API Platform executes it through the exact database Resource Revision and returns a bounded, summarized result

#### Scenario: Mutating query is rejected
- **WHEN** Agent calls `query_database` with an insert, update, delete, DDL or privileged operation
- **THEN** the system rejects the request and records the rejected tool call without sending it to the real database

#### Scenario: Query crosses workshop prefix
- **WHEN** a Workshop-scoped query references any table outside the frozen exact table prefix
- **THEN** the Internal API Platform rejects the whole query before opening or using the upstream connection

### Requirement: Redis tools are read-only
The system SHALL allow Redis evidence collection only through approved GET and bounded SCAN operations against the exact Resource Revision and Workshop Partition Policy Revision frozen by the Job. GET keys and SCAN patterns MUST begin with an allowed complete namespace prefix, and all mutation, script, regular-expression, cross-namespace or prefix-leading-wildcard operations MUST be rejected before accessing Redis.

#### Scenario: Redis key is read
- **WHEN** Agent calls `query_redis_get` for a complete key beginning with one frozen namespace prefix
- **THEN** the Internal API Platform returns the masked bounded value summary and records the exact resource and policy revision

#### Scenario: Redis mutation is requested
- **WHEN** Agent requests Redis deletion, mutation, expiration, flush or scripting
- **THEN** the system rejects the request and does not forward it to Redis

#### Scenario: Redis scan is outside namespace
- **WHEN** Agent submits `*GL001*`, a regex or a pattern outside all frozen complete namespace prefixes
- **THEN** the platform rejects the SCAN before contacting Redis

### Requirement: Loki queries are bounded
The system SHALL constrain Loki queries by the exact Resource Revision, tenant and mandatory Loki Scope Policy frozen by the Job, plus allowed diagnostic filters, time range, query size and result size. The mandatory selector MUST be injected server-side as exact AND conditions and MUST NOT be overridden, removed or widened by the Agent.

#### Scenario: Loki query is within limits
- **WHEN** Agent calls `query_loki` with allowed diagnostic filters and a bounded time range
- **THEN** the Internal API Platform combines them with the frozen mandatory selector, returns a bounded log summary and records selector metadata/hash

#### Scenario: Loki query exceeds limits
- **WHEN** Agent requests a disallowed label, conflicts with a mandatory key, submits arbitrary LogQL, or exceeds time or result limits
- **THEN** the system rejects or truncates according to policy and records the decision

#### Scenario: Workshop target uses base-level Loki policy
- **WHEN** a Job target contains a Workshop but its Loki Policy is scoped to Environment and Base
- **THEN** the platform uses exactly that Policy and does not infer a Workshop, replica or placement label

### Requirement: DB-backed resource bindings preserve read-only guardrails
系统 SHALL 确保从 Job Execution Snapshot 加载的精确 DB、Redis、Loki Resource Revision 及策略 Revision 继续执行只读、安全、限流、脱敏和审计策略；运行时不得重新查询 latest Resource 或以名称、默认值、最近父级和第一候选回退。

#### Scenario: DB config enables query_database
- **WHEN** Job Snapshot 为数据库 slot 冻结了 Resource Revision 和 Workshop Partition Policy
- **THEN** `query_database` 仍执行只读 SQL、全部表引用前缀、超时、行数和字节限制

#### Scenario: Redis config enables scan
- **WHEN** Job Snapshot 为 Redis slot 冻结了 Resource Revision 和 namespace Policy
- **THEN** `query_redis_scan` 仍执行完整 key prefix、迭代、数量和结果脱敏限制

#### Scenario: Loki config enables query
- **WHEN** Job Snapshot 冻结了 Loki Resource 与 Scope Policy
- **THEN** `query_loki` 仍执行 tenant、强制 selector、允许附加过滤、时间窗和响应限制

#### Scenario: Snapshot has multiple matches
- **WHEN** 一个 slot、目标和 placement 产生多个 Resource Mapping
- **THEN** Internal API Platform 失败关闭且不访问任何候选上游

### Requirement: Internal API Platform 必须提供只读 schema 目录
系统 SHALL 提供只读 schema directory 工具或 endpoint，用于按 Job 冻结的用户、业务目标、数据库 Resource Revision 和 Workshop Partition Policy 返回可访问的数据表和字段摘要。该能力 MUST 复用授权、方言感知的精确表前缀和响应大小限制；目标没有 Workshop 时不得要求虚拟前缀。

#### Scenario: 查询 workshop schema 目录
- **WHEN** Agent 为 `sanjiu/guanlan/GL001` 请求数据库 schema 目录且冻结前缀为 `GL001_`
- **THEN** Internal API Platform 只返回该用户有权访问且表名符合精确前缀的表和字段摘要

#### Scenario: 查询无 workshop 的 schema 目录
- **WHEN** Job 目标是没有 Workshop 层级的 Environment 或 Base
- **THEN** 平台按该目标冻结的 Resource 和访问范围返回目录，不构造默认 Workshop 前缀

#### Scenario: schema 目录不泄露连接密钥
- **WHEN** schema directory 返回数据库元数据
- **THEN** 响应不得包含 host、port、username、password、DSN、tenant secret 或其它连接凭据

#### Scenario: schema 目录受大小限制
- **WHEN** 可访问表或字段数量超过配置上限
- **THEN** 平台返回 bounded 摘要并标记 `truncated=true` 或等价字段

### Requirement: Loki diagnostics must remain read-only and bounded
Internal API Platform SHALL provide Loki runtime diagnostic operations only as read-only, bounded requests using the exact Resource Revision and mandatory Scope Policy frozen by the Job. Management-time label discovery SHALL use a separate authenticated Draft-test contract and MUST NOT be exposed as an Agent tool or bypass runtime selector policy.

#### Scenario: Bounded runtime label diagnostics
- **WHEN** Agent requests allowed Loki labels or label values through Internal API Platform
- **THEN** the platform applies the mandatory selector, returns only bounded diagnostic summaries and records the access decision

#### Scenario: Management label discovery
- **WHEN** an authorized administrator discovers labels after testing a Loki Resource Draft
- **THEN** the platform uses the separate bounded management endpoint and does not add that endpoint to the Agent Tool Catalog

#### Scenario: Disallowed diagnostic selector
- **WHEN** a runtime diagnostic request includes a disallowed selector label or exceeds configured limits
- **THEN** the platform rejects the request with a safe non-secret error summary

## ADDED Requirements

### Requirement: Tool Call 必须校验精确代码实现
Agent Runtime 和 Internal API Platform MUST 在构建和执行 Tool Call 时校验 Job 冻结的 Tool Release ID、Handler Version 和 Implementation Digest 与当前代码 Registry 精确一致；不得仅凭工具名称或输入 Schema 相似即执行。

#### Scenario: 当前实现精确匹配
- **WHEN** Job Snapshot 的 Handler Version 和 Implementation Digest 均存在于当前代码 Registry
- **THEN** 调用可以进入后续生命周期、权限、资源和策略校验

#### Scenario: 当前实现 digest 漂移
- **WHEN** 工具名称和版本字符串相同但 Implementation Digest 不同
- **THEN** 运行时拒绝调用并记录 DRIFTED，不自动使用当前实现
