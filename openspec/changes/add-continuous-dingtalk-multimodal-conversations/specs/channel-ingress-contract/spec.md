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

### Requirement: Channel附件信封保护短期凭证
系统 SHALL 只在受控媒体下载边界使用附件短期来源凭证。为支持可恢复异步下载，系统 MAY 使用平台主密钥短期加密凭证并保存类型和过期时间，但 MUST NOT 持久化明文或把明文/密文写入RabbitMQ、日志、审计、API或调试输出；终态或过期后 MUST 清除密文。

#### Scenario: Adapter receives temporary media credential
- **WHEN** 外部payload包含下载附件所需的短期凭证
- **THEN** 数据库只可保存短期密文、类型和过期时间，其他持久化输出只保留内部attachment ID及安全来源摘要

### Requirement: Channel附件事件保持端到端幂等
系统 SHALL 将Channel、connector、外部事件、外部消息和附件序号纳入稳定幂等语义。

#### Scenario: Attachment event is redelivered
- **WHEN** connector重复投递同一附件事件
- **THEN** 系统返回已有确认且不新增message、attachment、对象或任务
