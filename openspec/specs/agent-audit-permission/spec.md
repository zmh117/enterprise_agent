# agent-audit-permission Specification

## Purpose
TBD - created by archiving change add-readonly-diagnostic-agent-mvp. Update Purpose after archive.
## Requirements
### Requirement: Users must be authorized before Agent job creation
The system SHALL check requester allowlists, service account permissions, connector ingress authorization, and service or project allowlists before creating an Agent job from any Channel message.

#### Scenario: Authorized user submits request
- **WHEN** a verified Channel requester is allowed to use the Agent for the requested service or project and the source connector allows ingress
- **THEN** the system creates the Agent job and records the permission decision

#### Scenario: Unauthorized user submits request
- **WHEN** a verified Channel requester is not allowed to use the Agent or target service or project
- **THEN** the system rejects the request, records the permission denial, and does not publish an Agent job

#### Scenario: Connector is not authorized for ingress
- **WHEN** a request uses a connector that is disabled or not allowed for ingress
- **THEN** the system rejects the request, records the connector authorization failure, and does not publish an Agent job

### Requirement: Tool access is policy checked
The system SHALL check tool allowlists, source access, and read-only risk policy before executing each Agent tool call.

#### Scenario: Allowed read-only tool call
- **WHEN** Agent requests an enabled read-only tool within the user's allowed scope
- **THEN** the system executes the tool call and records the policy decision

#### Scenario: Disallowed tool call
- **WHEN** Agent requests a disabled tool, out-of-scope source, or non-read-only operation
- **THEN** the system rejects the tool call and records the policy decision

### Requirement: Audit events are persisted across the execution chain
The system SHALL persist audit events for Channel receipt, signature or token verification, identity parsing, ignored events, connector authorization, permission decisions, job creation, queue dispatch, worker claim, tool calls, result creation, failures, retries, delivery attempts, delivery chunks, and final delivery status.

#### Scenario: Job completes successfully
- **WHEN** an Agent job is accepted, executed, and delivered through its configured reply route
- **THEN** the audit trail includes records linking the original Channel request, job, tool calls, final report, delivery attempt, and delivery chunks

#### Scenario: Job fails before execution
- **WHEN** a job is rejected before Agent runtime starts
- **THEN** the audit trail includes the rejection reason and no tool execution records

#### Scenario: Grafana event is ignored
- **WHEN** a Grafana event is ignored because it is not `firing`
- **THEN** the audit trail records the connector, external event ID, ignored reason, and safe payload summary

### Requirement: Tool calls are recorded with safe summaries
The system SHALL persist tool call records with sanitized request payload summaries, response summaries, status, duration, risk level, audit linkage, and Internal API Platform outcome details when available.

#### Scenario: Database tool succeeds
- **WHEN** `query_database` returns evidence through the Internal API Platform
- **THEN** the system records the tool name, sanitized request summary, bounded response summary, duration, status, risk level, related audit event, and platform request metadata if provided

#### Scenario: Tool call returns sensitive or large data
- **WHEN** a tool response contains sensitive fields or exceeds inline storage limits
- **THEN** the system stores a masked or summarized response in PostgreSQL and avoids persisting raw sensitive payloads in the tool call row

#### Scenario: Internal platform rejects a tool call
- **WHEN** the Internal API Platform rejects a tool call because of authorization, data-source policy, query policy, or malformed parameters
- **THEN** the system records a failed tool call with a safe rejection reason, duration, risk level, and audit event without exposing platform secrets

### Requirement: Agent artifacts are persisted
The system SHALL persist final reports and other approved Agent artifacts with job linkage and artifact type.

#### Scenario: Final report is generated
- **WHEN** the Agent produces the final diagnostic answer
- **THEN** the system persists a report artifact linked to the Agent job

### Requirement: Configuration is persisted for future web management
The system SHALL store permission policies, tool enablement, connector metadata, connector direction flags, delivery metadata, and data source registry entries in PostgreSQL so a later web service can manage them without redesigning core persistence.

#### Scenario: Administrator later changes tool access
- **WHEN** a future web service updates tool enablement or permission policy
- **THEN** the Agent runtime can read the updated PostgreSQL-backed configuration without requiring a code change

#### Scenario: Administrator later changes connector direction
- **WHEN** a future web service disables delivery on a connector
- **THEN** new jobs cannot select that connector as a delivery route until it is enabled again

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

### Requirement: DingTalk delivery credentials are never exposed in audit records
系统 SHALL 在钉钉企业 App 和 webhook 群机器人投递过程中屏蔽 Client Secret、access token、webhook token、签名密钥、完整 webhook URL 和敏感接收人信息。

#### Scenario: Delivery attempt is recorded
- **WHEN** 系统记录 DingTalk delivery attempt
- **THEN** target summary 和 audit payload 只包含 connector ID、route type、目标安全摘要和分片数量，不包含任何密钥或完整 URL

#### Scenario: DingTalk provider returns an error
- **WHEN** 钉钉 API 或 webhook 返回错误
- **THEN** 系统保存安全错误摘要，不保存 access token、签名串、完整请求体中的敏感字段或完整 webhook URL

### Requirement: DingTalk delivery connector authorization is enforced
系统 SHALL 在钉钉企业 App 和 webhook 群机器人投递前校验 connector 存在、启用、允许 delivery，并记录授权决策。

#### Scenario: Delivery connector is allowed
- **WHEN** Agent job 使用允许 delivery 的 DingTalk connector
- **THEN** 系统记录 connector delivery 授权成功并继续投递

#### Scenario: Delivery connector is not allowed
- **WHEN** Agent job 使用未启用或不允许 delivery 的 DingTalk connector
- **THEN** 系统阻止投递、记录授权失败，并不发起外部钉钉请求

### Requirement: DingTalk webhook robot ingress attempts are audited
系统 SHALL 对 webhook 群机器人被误用为入口的请求记录审计事件，说明该 connector 只允许 delivery。

#### Scenario: Webhook robot ingress is rejected
- **WHEN** 请求尝试通过 webhook 群机器人 connector 创建 Agent job
- **THEN** 系统记录入口拒绝审计事件，并且不持久化 Agent session、Agent job 或 queue message

### Requirement: DingTalk Stream connection lifecycle is audited
The system SHALL persist audit events for DingTalk Stream connector startup, successful connection, disconnect, reconnect attempt, reconnect success, configuration failure, and permanent connector failure.

#### Scenario: Stream connector reconnects
- **WHEN** DingTalk Stream ingress loses connection and reconnects successfully
- **THEN** the audit trail records disconnect, reconnect attempt, reconnect success, connector ID, and timestamps

### Requirement: DingTalk Stream ingress permission is checked before job creation
The system SHALL check connector enablement, user allowlists, and project or service allowlists before creating an Agent job from a DingTalk Stream message.

#### Scenario: Authorized Stream user submits request
- **WHEN** a DingTalk Stream user is allowed to use the Agent for the requested project or service
- **THEN** the system creates the Agent job and records the permission decision with Stream event linkage

#### Scenario: Unauthorized Stream user submits request
- **WHEN** a DingTalk Stream user is not allowed to use the Agent or requested project or service
- **THEN** the system rejects the Stream message, records the permission denial, and does not publish an Agent job

### Requirement: DingTalk Stream message handling is audited end to end
The system SHALL persist audit events linking the Stream event receipt, identity parsing, idempotency decision, permission decision, job creation, queue dispatch, worker execution, final artifact, and DingTalk delivery result.

#### Scenario: Stream job completes successfully
- **WHEN** an Agent job created from DingTalk Stream completes and is delivered to DingTalk
- **THEN** the audit trail links the original Stream event, Agent job, tool calls, final report, and delivery result

#### Scenario: Stream message fails before execution
- **WHEN** a DingTalk Stream message is rejected before Agent runtime starts
- **THEN** the audit trail includes the rejection reason and no tool execution records

