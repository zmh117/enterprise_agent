## MODIFIED Requirements

### Requirement: Agent sessions and jobs are persisted
The system SHALL persist Agent sessions, Agent jobs, user messages, assistant messages, retry metadata, result summaries, failure reasons, source channel metadata, requester identity, routing context, reply route, and an immutable Tool Execution Snapshot before dispatch. The Snapshot MUST include the exact Agent/Application Publication, Tool Releases, Handler Versions, Implementation Digests, Business Target Path, permitted placements, Resource Revisions, Partition/Loki Policy IDs/revisions/hashes and authorization-fact summary required by the Job.

#### Scenario: New diagnostic request is accepted
- **WHEN** a verified Channel request passes connector, publication, identity, permission, target and resource-composition checks
- **THEN** the system persists the session, Job, user message, routing facts and complete Tool Execution Snapshot before publishing the Job to the message bus

#### Scenario: Agent result is produced
- **WHEN** Agent execution completes with a final answer
- **THEN** the system persists the assistant message, result summary, Job completion timestamp, delivery-ready result artifact and exact Tool Call fact references

#### Scenario: Legacy DingTalk request is accepted during cutover
- **WHEN** an existing DingTalk endpoint creates a new Job after exact-snapshot cutover
- **THEN** the system persists equivalent generic channel fields and a complete exact Tool Execution Snapshot; it MUST NOT create a new `legacy-v1` tool binding

#### Scenario: Snapshot cannot be constructed uniquely
- **WHEN** the active Publication produces zero or multiple Tool/Resource/Policy candidates for the requested target
- **THEN** Job creation fails before queue dispatch and records a safe non-retryable composition error

## ADDED Requirements

### Requirement: Job Tool Execution Snapshot must be immutable
系统 MUST 在 Job 创建后禁止修改其 Tool Release、Handler Version、Implementation Digest、Business Target Path、placement 集合、Resource Revision、Partition Policy 或 Loki Scope Policy；任何配置新版本都只能影响显式使用新 Application Publication 创建的新 Job。

#### Scenario: Resource rotates after job creation
- **WHEN** Job 已创建后 Resource Identity 发布了新 Revision
- **THEN** 原 Job、重试和 replay 继续引用冻结 Revision

#### Scenario: Operator attempts to edit snapshot
- **WHEN** 管理 API、恢复命令或数据库 repository 请求替换已有 Job 的精确绑定
- **THEN** 系统拒绝修改并记录审计，不提供普通 CRUD 覆盖路径

### Requirement: Retry and replay must use the original snapshot
所有自动重试、Outbox replay 和授权的显式恢复 MUST 使用原 Job Tool Execution Snapshot，并 MUST 重新检查冻结 Release 的当前可调用生命周期和精确实现可用性；不得解析 latest、replacement 或当前活动 Application Publication。

#### Scenario: Retry after application upgrade
- **WHEN** 原 Job 失败后应用切换到新的 Application Publication
- **THEN** 重试仍使用原 Publication 和全部冻结资源策略事实

#### Scenario: Frozen release is disabled
- **WHEN** 重试时冻结 Tool Release 已为 DISABLED
- **THEN** Job 以安全的非重试或隔离状态失败，不自动替换 Release

#### Scenario: Frozen implementation is missing
- **WHEN** 当前 Worker 缺少 Snapshot 中精确 Handler Version 或 Implementation Digest
- **THEN** Worker 不执行相似名称工具，并报告 MISSING/DRIFTED 运行错误

### Requirement: Tool Call must record the actual resolved placement and scope
每次 Tool Call SHALL 持久化实际选择的 placement、Resource Revision、Partition/Loki Policy revision、有效 selector 或 namespace 的安全 hash、授权判定和 correlation id，并 MUST NOT 保存 Secret 或无界业务响应。

#### Scenario: Cloud resource is selected
- **WHEN** Job 允许 cloud 和 edge，某次 Tool Call 明确解析到 cloud
- **THEN** Tool Call 记录 `cloud` 和其精确 Resource Revision，后续同 Job 的其它调用仍可独立解析允许的 placement

#### Scenario: No-placement resource is selected
- **WHEN** Job 使用没有 placement 维度的 Redis Resource
- **THEN** Tool Call 记录 placement 缺省而不是 `none` 或 `standalone`

### Requirement: Legacy recoverable jobs must be materialized or isolated before removal
在删除 `legacy-v1` 兼容读取前，系统 MUST 对所有非终态、待重试、可 replay 或可显式恢复的旧 Job 生成幂等迁移报告，并只在候选唯一且证据充分时物化精确 Tool Execution Snapshot；其它 Job MUST 被隔离。

#### Scenario: Legacy job can be uniquely resolved
- **WHEN** 原 Publication、代码 digest、资源绑定和策略能唯一确定精确事实
- **THEN** 迁移事务写入 Snapshot、内容 hash、迁移版本和证据摘要

#### Scenario: Legacy job is ambiguous
- **WHEN** 旧名称可对应多个 Release 或资源范围无法唯一还原
- **THEN** 迁移不猜测候选，将 Job 标记为不可重试/不可恢复并列入人工报告

#### Scenario: Historical terminal job remains
- **WHEN** 已终态且不可恢复的 Job 只包含 `legacy-v1` 历史字段
- **THEN** 系统保留其只读审计记录，但不得从该记录创建新执行
