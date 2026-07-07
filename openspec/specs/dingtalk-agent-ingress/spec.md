# dingtalk-agent-ingress Specification

## Purpose
TBD - created by archiving change add-readonly-diagnostic-agent-mvp. Update Purpose after archive.
## Requirements
### Requirement: DingTalk message identity is parsed
The system SHALL parse and persist the DingTalk Stream conversation identity, DingTalk user identity, source channel, connector identity, external event identity, and user message content needed to create an Agent session and Agent job.

#### Scenario: User asks a diagnostic question
- **WHEN** a verified DingTalk Stream message contains a user diagnostic question
- **THEN** the system persists the DingTalk conversation identity, DingTalk user identity, source channel, connector identity, external event identity, and original user message

### Requirement: DingTalk ingress is idempotent
The system SHALL use DingTalk Stream event identifiers, message identifiers, or a deterministic idempotency key to avoid creating duplicate Agent jobs for retried or redelivered Stream events.

#### Scenario: Duplicate Stream event is received
- **WHEN** the same DingTalk Stream event or message is delivered more than once
- **THEN** the system returns the existing Agent job acknowledgement instead of creating another Agent job

### Requirement: DingTalk receives immediate acknowledgement
The system SHALL send a quick DingTalk Stream acknowledgement after a job is persisted and dispatched, without waiting for Claude Code Agent execution to finish.

#### Scenario: Job is created successfully
- **WHEN** the system creates and dispatches an Agent job from a DingTalk Stream message
- **THEN** DingTalk receives an acknowledgement indicating the task has been accepted and analysis is starting

### Requirement: DingTalk receives final Agent results
The system SHALL send the final Agent report or failure notice through the configured DingTalk delivery route after asynchronous job execution completes.

#### Scenario: Agent job succeeds
- **WHEN** an Agent job reaches SUCCEEDED with a final report
- **THEN** the system sends the report to the configured DingTalk delivery target, defaulting to the originating DingTalk conversation when no override is configured

#### Scenario: Agent job fails
- **WHEN** an Agent job reaches FAILED or TIMEOUT
- **THEN** the system sends a failure notice with a safe failure reason to the configured DingTalk delivery target

### Requirement: DingTalk robots can be configured for ingress and delivery
The system SHALL support DingTalk enterprise robots and DingTalk webhook robots as configurable connectors that can allow ingress, delivery, or both.

#### Scenario: DingTalk robot is ingress enabled
- **WHEN** a DingTalk robot connector is configured with `allow_ingress=true`
- **THEN** valid messages from that connector can create Agent jobs through the Channel ingress service

#### Scenario: DingTalk robot is delivery enabled
- **WHEN** a DingTalk robot connector is configured with `allow_delivery=true`
- **THEN** Agent results can be delivered through that connector's DingTalk adapter

### Requirement: DingTalk enterprise App can receive final Agent results
系统 SHALL 支持通过钉钉企业 App 出口将最终报告或失败通知发送回配置的钉钉目标，目标可以来自 reply route 或 connector 默认配置。

#### Scenario: Reply route contains enterprise target
- **WHEN** Agent job 的 reply route 指定企业 App 钉钉目标
- **THEN** 系统使用该目标发送最终报告，并将投递结果关联到原 Agent job

#### Scenario: Reply route omits enterprise target
- **WHEN** Agent job 的 reply route 使用 `dingtalk_enterprise_robot` 但未显式指定目标
- **THEN** 系统使用 connector metadata 中的默认钉钉目标；若默认目标缺失则标记 delivery 配置失败

### Requirement: DingTalk webhook robot is not a user-question ingress
系统 SHALL 将钉钉 webhook 群机器人限定为结果出口能力，MUST NOT 通过该 connector 接收用户问题或创建 Agent job。

#### Scenario: User sends message to webhook robot
- **WHEN** webhook 群机器人相关请求到达系统入口
- **THEN** 系统不会把该请求解析为用户问题，也不会创建 Agent job

#### Scenario: Webhook robot receives final report
- **WHEN** Agent job 使用 `dingtalk_webhook_robot` 作为 delivery route
- **THEN** 系统把最终报告作为群消息发送到配置的钉钉群机器人 webhook

### Requirement: DingTalk delivery uses safe acknowledgement and failure semantics
系统 SHALL 将钉钉投递结果与 Agent 执行结果分离，钉钉发送失败 MUST NOT 改写已经成功或失败的 Agent job 执行状态。

#### Scenario: DingTalk delivery fails after Agent success
- **WHEN** Agent job 已经 SUCCEEDED 但钉钉企业 App 或 webhook 群机器人发送失败
- **THEN** 系统只更新 delivery attempt/chunk 状态并记录安全错误摘要，Agent job 保持 SUCCEEDED

