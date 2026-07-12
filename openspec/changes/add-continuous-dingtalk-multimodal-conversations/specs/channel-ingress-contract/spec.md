## MODIFIED Requirements

### Requirement: Channel requests are normalized before Agent job creation
系统 SHALL 在创建Agent job前，将所有外部入口请求归一化为包含 `from`、`delivery`、`routing` 以及由可选文本正文和附件描述组成的 `message` 的内部Channel event。文本正文和附件列表 MUST 至少有一项非空。

#### Scenario: Generic text channel request is accepted
- **WHEN** 一个已认证入口请求包含有效 `from`、`delivery`、`routing` 和非空文本正文
- **THEN** 系统使用归一化后的Channel event解析或创建Agent session，并创建Agent job和user message

#### Scenario: Generic attachment channel request is accepted
- **WHEN** 一个已认证入口请求包含有效 `from`、`delivery`、`routing` 和至少一个受支持附件描述
- **THEN** 系统归一化附件类型和来源句柄，持久化消息及附件元数据，并按附件输入闸门调度Agent job

#### Scenario: Missing required channel content
- **WHEN** 入口请求缺少 `from.type`、必填routing字段，或文本正文和附件列表同时为空
- **THEN** 系统拒绝请求、记录安全错误摘要，且不创建Agent job或RabbitMQ消息

## ADDED Requirements

### Requirement: Channel附件信封不得泄漏短期凭证
系统 SHALL 只在Channel adapter受控下载阶段使用附件短期来源句柄，MUST NOT 将临时下载URL、download code、session webhook、token或其他凭证写入持久化Channel event、RabbitMQ消息、日志或审计记录。

#### Scenario: Adapter receives temporary media credential
- **WHEN** 外部Channel payload包含下载附件所需的短期凭证
- **THEN** adapter仅将凭证用于受控媒体获取，持久化记录和日志只保留内部attachment ID及安全来源摘要

### Requirement: Channel附件事件保持端到端幂等
系统 SHALL 将Channel类型、connector、外部事件ID、外部消息ID和附件序号纳入稳定幂等语义，避免重投产生重复消息、附件对象或Agent job。

#### Scenario: Attachment event is redelivered
- **WHEN** connector重复投递相同外部附件事件
- **THEN** 系统返回已有处理确认，不新增message、attachment、对象或队列任务

