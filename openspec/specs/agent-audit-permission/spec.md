# agent-audit-permission Specification

## Purpose
TBD - created by archiving change add-readonly-diagnostic-agent-mvp. Update Purpose after archive.
## Requirements
### Requirement: Users must be authorized before Agent job creation
The system SHALL check user allowlists and service or project allowlists before creating an Agent job from a DingTalk message.

#### Scenario: Authorized user submits request
- **WHEN** a verified DingTalk user is allowed to use the Agent for the requested service or project
- **THEN** the system creates the Agent job and records the permission decision

#### Scenario: Unauthorized user submits request
- **WHEN** a verified DingTalk user is not allowed to use the Agent or target service or project
- **THEN** the system rejects the request, records the permission denial, and does not publish an Agent job

### Requirement: Tool access is policy checked
The system SHALL check tool allowlists, source access, and read-only risk policy before executing each Agent tool call.

#### Scenario: Allowed read-only tool call
- **WHEN** Agent requests an enabled read-only tool within the user's allowed scope
- **THEN** the system executes the tool call and records the policy decision

#### Scenario: Disallowed tool call
- **WHEN** Agent requests a disabled tool, out-of-scope source, or non-read-only operation
- **THEN** the system rejects the tool call and records the policy decision

### Requirement: Audit events are persisted across the execution chain
The system SHALL persist audit events for webhook receipt, identity parsing, permission decisions, job creation, queue dispatch, worker claim, tool calls, result creation, failures, retries, and DingTalk callbacks.

#### Scenario: Job completes successfully
- **WHEN** an Agent job is accepted, executed, and replied to DingTalk
- **THEN** the audit trail includes records linking the original user request, job, tool calls, final report, and callback delivery

#### Scenario: Job fails before execution
- **WHEN** a job is rejected before Agent runtime starts
- **THEN** the audit trail includes the rejection reason and no tool execution records

### Requirement: Tool calls are recorded with safe summaries
The system SHALL persist tool call records with sanitized request payload summaries, response summaries, status, duration, risk level, and audit linkage.

#### Scenario: Database tool succeeds
- **WHEN** `query_database` returns evidence
- **THEN** the system records the tool name, sanitized request summary, bounded response summary, duration, status, risk level, and related audit event

#### Scenario: Tool call returns sensitive or large data
- **WHEN** a tool response contains sensitive fields or exceeds inline storage limits
- **THEN** the system stores a masked or summarized response in PostgreSQL and avoids persisting raw sensitive payloads in the tool call row

### Requirement: Agent artifacts are persisted
The system SHALL persist final reports and other approved Agent artifacts with job linkage and artifact type.

#### Scenario: Final report is generated
- **WHEN** the Agent produces the final diagnostic answer
- **THEN** the system persists a report artifact linked to the Agent job

### Requirement: Configuration is persisted for future web management
The system SHALL store permission policies, tool enablement, connector metadata, and data source registry entries in PostgreSQL so a later web service can manage them without redesigning core persistence.

#### Scenario: Administrator later changes tool access
- **WHEN** a future web service updates tool enablement or permission policy
- **THEN** the Agent runtime can read the updated PostgreSQL-backed configuration without requiring a code change

### Requirement: Platform configuration authorization is policy checked
系统 SHALL 在平台配置 API 执行新增、修改、启停、导入和发布动作前检查操作者是否具有对应配置管理权限。

#### Scenario: Authorized admin updates topology
- **WHEN** 具备平台配置管理权限的操作者更新基地或车间配置
- **THEN** 系统允许更新并记录授权决策

#### Scenario: Unauthorized user updates topology
- **WHEN** 不具备平台配置管理权限的用户尝试修改资源绑定
- **THEN** 系统拒绝请求，记录拒绝原因，并且不写入配置变更

### Requirement: Platform configuration audit is linked to runtime audit model
系统 SHALL 将平台配置变更审计与现有 Agent 审计模型保持一致的 actor、entity、action、before、after 和 correlation 信息。

#### Scenario: Admin changes access grant
- **WHEN** 管理员修改某用户的车间访问授权
- **THEN** 系统记录配置审计，包含操作者、被修改实体、修改前摘要、修改后摘要和 correlation id

#### Scenario: YAML import updates resource binding
- **WHEN** YAML import 更新已有资源绑定
- **THEN** 系统记录该资源绑定的配置审计，并能关联到本次 import 操作

### Requirement: Runtime tool authorization can consume platform access grants
系统 SHALL 允许运行时工具授权从平台访问授权配置生成访问策略，且 MUST 保持只读工具风险边界。

#### Scenario: User has workshop grant
- **WHEN** Agent job 用户命中某车间的 read-only access grant
- **THEN** 运行时工具授权允许该用户访问该车间允许的只读资源

#### Scenario: User lacks grant
- **WHEN** Agent job 用户没有目标车间或资源的访问授权
- **THEN** 运行时工具授权拒绝工具调用并记录权限拒绝
