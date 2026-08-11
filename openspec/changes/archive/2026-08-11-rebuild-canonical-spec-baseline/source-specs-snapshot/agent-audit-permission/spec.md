# agent-audit-permission Specification

## Purpose
TBD - created by archiving change add-readonly-diagnostic-agent-mvp. Update Purpose after archive.
## Requirements
### Requirement: Users must be authorized before Agent job creation
The system SHALL check connector ingress authorization and the access policy applicable to the resolved Trigger before creating an Agent job from any Channel message. For DingTalk messages resolved to an active Business Application Publication, the system SHALL authorize application access when the actual sender maps to an enabled internal user and MUST NOT require an additional application user allowlist, role, or Capability `use` grant; other Trigger types SHALL retain their defined requester, service-account, service, project, or role policies.

#### Scenario: Authorized user submits request
- **WHEN** a verified Channel requester satisfies the access policy for the resolved Trigger and the source connector allows ingress
- **THEN** the system creates the Agent job and records the permission decision

#### Scenario: Unauthorized user submits request
- **WHEN** a verified Channel requester does not satisfy the access policy for the resolved Trigger or target service or project
- **THEN** the system rejects the request, records the permission denial, and does not publish an Agent job

#### Scenario: Connector is not authorized for ingress
- **WHEN** a request uses a connector that is disabled or not allowed for ingress
- **THEN** the system rejects the request, records the connector authorization failure, and does not publish an Agent job

#### Scenario: DingTalk sender resolves to an enabled user
- **WHEN** a DingTalk message hits a connector bound to an active Application Publication and the actual sender maps to an enabled internal user
- **THEN** the system authorizes access to that application without requiring a separate application user allowlist, role, or Capability grant

#### Scenario: DingTalk sender is unbound or disabled
- **WHEN** the actual DingTalk sender has no enabled internal identity or the internal user is disabled
- **THEN** the system rejects job creation, records a safe reason, and returns an understandable binding or account-status prompt

### Requirement: Tool access is policy checked
The system SHALL check tool allowlists, source access, read-only risk policy and the governance policy applicable to each Tool before execution. For a governed API Capability, the system MUST check the frozen Agent Capability Envelope, Application Capability Allowlist, exact Release status, current user Provider availability, External Execution Subject Snapshot and current personal credential; it MUST NOT require a separate per-user or per-role Capability Code `use` grant.

#### Scenario: Allowed read-only tool call
- **WHEN** Agent requests an enabled internal read-only tool within the user's allowed scope
- **THEN** the system executes the tool call and records the policy decision

#### Scenario: Disallowed tool call
- **WHEN** Agent requests a disabled tool, out-of-scope source, non-read-only operation, or Tool outside the current publication snapshot
- **THEN** the system rejects the tool call and records the policy decision

#### Scenario: Governed Capability is fully allowed
- **WHEN** the exact Capability Release belongs to both the frozen Agent Envelope and Application Allowlist, remains runnable, and the current user binding, Team and Token are valid
- **THEN** the system executes the call and records each governance dimension without checking a separate Capability role grant

#### Scenario: Application did not allow Capability
- **WHEN** the Agent Envelope includes the Release but the Application Allowlist does not
- **THEN** the system rejects the call before external network access and records the missing application authorization dimension

### Requirement: Audit events are persisted across the execution chain
系统 SHALL 持久化覆盖 Channel receipt、身份解析、connector/RBAC 决策、Job 创建、队列发布确认、Worker claim、工具调用、Claude 安全错误分类、retry 调度、retry 回流、显式恢复、终态结果、delivery attempt/chunk 和最终投递状态的审计事件，并使用 Job 与 correlation ID 串联全链路。

#### Scenario: Job completes successfully without retry
- **WHEN** Agent Job 被接受、首次执行成功并沿 reply route 投递
- **THEN** 审计链包含入口、身份/RBAC、Job、主队列发布、Worker、工具、最终报告和 delivery 结果

#### Scenario: Job succeeds after retry
- **WHEN** Job 首次发生可重试错误，延迟回流后再次执行成功
- **THEN** 审计链包含安全错误码、retry count、`next_retry_at`、retry publish confirm、回流后的再次 claim、最终报告和 delivery 结果

#### Scenario: Job fails after retries are exhausted
- **WHEN** Job 达到最大重试次数并进入 `FAILED`
- **THEN** 审计链包含每次安全错误分类、retry 调度/回流、终态 dead-letter 决策和一次失败通知 delivery 结果

#### Scenario: Retry dispatch is stranded
- **WHEN** Job 已持久化为等待重试但 RabbitMQ publish confirm 失败或超过预期时间没有回流
- **THEN** 审计记录 dispatch/recovery 状态，使运维能区分模型失败、队列滞留和 Worker 未消费

#### Scenario: Administrator recovers a stranded job
- **WHEN** 管理员通过显式 apply 恢复一个滞留 Job
- **THEN** 审计记录管理员内部身份、目标 Job、恢复前后状态、所用队列版本和 publish 结果，不记录完整外部 payload 或 webhook

#### Scenario: Job fails before execution
- **WHEN** Job 在 Agent runtime 开始前被拒绝
- **THEN** 审计链包含拒绝原因且没有工具执行或模型调用记录

#### Scenario: Grafana event is ignored
- **WHEN** Grafana 事件因为不是 `firing` 被忽略
- **THEN** 审计记录 connector、external event ID、忽略原因和安全 payload 摘要

### Requirement: Tool calls are recorded with safe summaries
The system SHALL persist tool call records with sanitized request payload summaries, bounded normalized response summaries, status, duration, risk level, audit linkage, and platform or Capability Release outcome details when available. For governed external APIs, the system MUST record Release and attempt metadata but MUST NOT persist authentication material, raw HTTP request/response bodies or unbounded external content.

#### Scenario: Database tool succeeds
- **WHEN** `query_database` returns evidence through the Internal API Platform
- **THEN** the system records the tool name, sanitized request summary, bounded response summary, duration, status, risk level, related audit event, and platform request metadata if provided

#### Scenario: Tool call returns sensitive or large data
- **WHEN** a tool response contains sensitive fields or exceeds inline storage limits
- **THEN** the system stores a masked or summarized response in PostgreSQL and avoids persisting raw sensitive payloads in the tool call row

#### Scenario: Internal platform rejects a tool call
- **WHEN** the Internal API Platform rejects a tool call because of authorization, data-source policy, query policy, or malformed parameters
- **THEN** the system records a failed tool call with a safe rejection reason, duration, risk level, and audit event without exposing platform secrets

#### Scenario: Governed external API call succeeds after retry
- **WHEN** a QUERY Capability succeeds after one or more HTTP attempts
- **THEN** the system records one linked Tool Call and separate safe attempt metadata containing identifiers, classification, duration, size and status, without raw body, Token, Cookie or authentication Header

#### Scenario: Governed external output is INTERNAL
- **WHEN** a Capability returns bounded normalized INTERNAL data
- **THEN** the Tool Call summary preserves user, Application Publication, Capability Release and classification provenance and remains subject to the existing Job access boundary

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

### Requirement: Identity and RBAC lifecycle changes are audited
The system SHALL audit user creation and disablement, password/session security events, role and membership changes, external identity binding lifecycle, Agent configuration validation/publication/rollback, and permission denials using internal actor IDs and secret-safe summaries.

#### Scenario: Administrator binds DingTalk identity
- **WHEN** an authenticated administrator binds a DingTalk identity to an internal user
- **THEN** the audit records actor, target user, external identity record, tenant/connector summary, action, before/after state and correlation ID without storing credentials or full provider payload

#### Scenario: Role permission is changed
- **WHEN** an administrator adds or removes a role policy
- **THEN** the audit records the role, safe policy summary, revision and actor

### Requirement: 模型与重试审计不得泄漏敏感运行数据
系统 SHALL 对 Claude/DeepSeek 错误、RabbitMQ retry payload、恢复输出和失败通知执行统一脱敏与有界摘要；API key、认证 token、完整 session webhook、完整敏感 URL、原始外部消息、未受限工具结果和模型私有推理 MUST 不进入审计。

#### Scenario: Claude CLI emits sensitive stderr
- **WHEN** CLI 错误包含 authorization、token、key、完整 URL 或请求内容
- **THEN** 审计仅保存屏蔽后的错误分类和有界摘要

#### Scenario: Retry message is audited
- **WHEN** 系统发布或回流 retry 消息
- **THEN** 审计只记录 Job ID、correlation ID、retry count、delay/due time、队列版本和确认结果，不复制用户问题、reply route secret 或模型上下文

### Requirement: Webhook 服务账号必须完成统一授权链
系统 SHALL 在 Webhook event 接收/分发和每次工具调用时，以 Trigger 服务账号执行 Connector ingress、Agent use、project、tool 和平台数据范围授权，MUST 采用显式 deny 优先。

#### Scenario: 服务账号权限完整
- **WHEN** 服务账号、角色和 grant 共同允许固定 Agent、项目、工具和目标数据范围
- **THEN** 系统允许创建 job并在决策 trace 中记录匹配策略和 grant

#### Scenario: 服务账号没有 Agent use 权限
- **WHEN** Trigger publication 有效但服务账号未被允许使用对应 Agent
- **THEN** dispatcher 拒绝创建 job、将 event 标记为安全失败并记录 deny trace

#### Scenario: 工具调用超出数据范围
- **WHEN** Webhook Agent 试图使用允许的工具访问服务账号未授权的基地或车间
- **THEN** 工具层拒绝调用并记录范围拒绝，Agent 不得绕过该决定

### Requirement: Webhook 配置和运行审计不得泄漏凭证或原始报文
系统 SHALL 审计 Trigger 创建、修改、发布、回滚、public ID 轮换、服务账号授权、事件认证/过滤/分发和 Delivery 结果，MUST 只保存安全摘要。

#### Scenario: HMAC 认证失败
- **WHEN** 请求签名不匹配
- **THEN** 审计记录 Trigger、错误码、payload hash、请求大小和 correlation ID，不记录 secret、签名原文或 body

#### Scenario: 管理员修改 Trigger
- **WHEN** 管理员保存或发布 revision
- **THEN** 审计记录 actor、Trigger、before/after config hash、revision 和结果，不记录 secret value

### Requirement: 授权决策记录业务应用和来源摘要
系统 SHALL 为 job 创建、Worker 执行前、每次业务能力调用和结果投递前的授权决策生成安全 trace，至少包含内部用户或服务账号、目标业务应用、能力、明确数据范围、来源角色 ID、兼容策略标记、最终结果和拒绝阶段。trace MUST NOT 包含密码、Token、Secret、模型 API Key 或原始敏感策略条件。

#### Scenario: Worker 因角色到期拒绝
- **WHEN** Worker 执行前发现创建任务时有效的角色成员关系已经到期
- **THEN** 系统记录执行前授权拒绝、角色来源摘要和 job 关联，不记录消息正文或敏感数据

### Requirement: 角色授权配置变更被审计
系统 SHALL 记录角色基本信息、成员、管理后台能力、业务应用、只读能力、数据范围、角色分配委派和高级例外的变更前后安全摘要。高风险变更 MUST 同时记录管理员填写的变更原因。

#### Scenario: 扩大生产数据范围
- **WHEN** 管理员为角色增加生产基地范围
- **THEN** 系统记录操作者、角色、业务应用、增加的明确范围、受影响成员数和变更原因

#### Scenario: 延长成员有效期
- **WHEN** 管理员延长角色成员有效期
- **THEN** 系统通过普通成员更新审计记录原时间、新时间和操作者，不要求独立审批记录

