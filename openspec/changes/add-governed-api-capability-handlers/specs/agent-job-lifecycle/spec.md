## MODIFIED Requirements

### Requirement: Agent sessions and jobs are persisted
The system SHALL persist Agent sessions, Agent jobs, user messages, assistant messages, retry metadata, result summaries, failure reasons, source channel metadata, requester identity, routing context, reply route, frozen Agent/Application publication references, and any required non-secret External Execution Subject Snapshot in PostgreSQL 16 before or during the relevant lifecycle event. The snapshot MAY contain external User ID and default Team ID but MUST NOT contain password, Token, Cookie or authentication Header.

#### Scenario: New diagnostic request is accepted
- **WHEN** a verified Channel request passes connector and permission checks
- **THEN** the system persists an Agent session, Agent job, user message, source channel metadata, requester identity, routing context, reply route and frozen publication references before publishing the job to the message bus

#### Scenario: ONES-enabled request is accepted
- **WHEN** an enabled DingTalk user creates a Job whose Application Allowlist includes an ONES Capability and the user binding is currently available
- **THEN** the system additionally freezes that user's current external User ID and default Team ID before queue dispatch, without copying the personal Token

#### Scenario: Agent result is produced
- **WHEN** Agent execution completes with a final answer
- **THEN** the system persists the assistant message, result summary, job completion timestamp, delivery-ready result artifact and applicable Capability/classification provenance

#### Scenario: Legacy DingTalk request is accepted
- **WHEN** an existing DingTalk webhook request uses the legacy endpoint
- **THEN** the system persists equivalent generic channel fields while retaining backward-compatible DingTalk fields for existing read paths, and an application with no Capability configuration receives an empty Capability snapshot

## ADDED Requirements

### Requirement: External Execution Subject Snapshot 不随绑定变化漂移
Job 创建后 MUST 保持外部 User ID 和 default Team ID 快照不可变；每次外部 Tool调用仍 MUST 对当前启用绑定、最新 Team 集合和当前个人 Token实施实时撤权校验。系统 MUST NOT 因用户换绑、切换 Team 或解绑而改写旧 Job。

#### Scenario: 用户在排队期间切换 Team
- **WHEN** Job 已入队且用户随后更改 default Team
- **THEN** Job 保留原 Team快照，并在原 Team不再有效时失败关闭

#### Scenario: 用户轮换同一主体的 Token
- **WHEN** Job快照User/Team仍有效且只有个人Token更新
- **THEN** 执行时可以解析新Token而不修改Job快照

### Requirement: 规范化 Capability 结果沿用既有持久化生命周期
通过 Output Schema 和大小限制的 Capability Tool结果以及最终回复 SHALL 按现有 Job、Tool Call、会话与制品模型正常持久化；系统 MUST 保留用户、Application Publication、Capability Release和数据分级来源，且本变更 MUST NOT 新增定时清理执行。

#### Scenario: INTERNAL 查询完成
- **WHEN** 受治理Capability返回合法规范化结果并由Agent形成最终回复
- **THEN** 系统按既有成功生命周期保存结果与来源，不保存原始HTTP响应

#### Scenario: retention_days 已配置
- **WHEN** 会话策略含有 `retention_days`
- **THEN** 本变更继续只保存该值而不据此删除Capability结果
