## MODIFIED Requirements

### Requirement: Channel requests are normalized before Agent job creation
系统 SHALL 在创建Agent job前，将所有外部入口归一化为包含`from`、`delivery`、`routing`以及由可选文本和附件描述组成的`message`。文本和附件 MUST 至少一项非空。

#### Scenario: Generic text channel request is accepted
- **WHEN** 已认证请求包含有效来源、投递、路由和非空文本
- **THEN** 系统解析或创建session并持久化job和user message

#### Scenario: Generic attachment channel request is accepted
- **WHEN** 已认证请求包含有效来源、投递、路由和至少一个受支持附件描述
- **THEN** 系统持久化消息与附件元数据并按输入闸门调度job

#### Scenario: Missing required channel content
- **WHEN** 请求缺少来源、必填路由或文本和附件同时为空
- **THEN** 系统拒绝请求且不创建job或RabbitMQ消息

## ADDED Requirements

### Requirement: Channel附件信封不得泄漏短期凭证
系统 SHALL 只在adapter控制范围内使用附件短期来源句柄，MUST NOT把临时URL、download code、session webhook或token写入数据库、RabbitMQ、日志或审计。

#### Scenario: Adapter receives temporary media credential
- **WHEN** 外部payload包含下载附件所需的短期凭证
- **THEN** 持久化记录和日志只保留内部attachment ID及安全来源摘要

### Requirement: Channel附件事件保持端到端幂等
系统 SHALL 将Channel、connector、外部事件、外部消息和附件序号纳入稳定幂等语义。

#### Scenario: Attachment event is redelivered
- **WHEN** connector重复投递同一附件事件
- **THEN** 系统返回已有确认且不新增message、attachment、对象或任务
