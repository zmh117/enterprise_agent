# result-delivery-routing Specification

## Purpose
TBD - created by archiving change add-channel-ingress-and-delivery. Update Purpose after archive.
## Requirements
### Requirement: Agent results are delivered through reply routes
系统 SHALL 根据 Agent job 持久化的 `reply_route` 投递最终报告或安全失败通知，而不是由 Agent runtime 直接调用特定平台 client。

#### Scenario: Successful job has DingTalk webhook delivery
- **WHEN** Agent job 成功且 `reply_route.type` 为 `dingtalk_webhook_robot`
- **THEN** 系统通过 DingTalk webhook robot delivery adapter 发送最终报告并记录投递结果

#### Scenario: Failed job has email delivery
- **WHEN** Agent job 最终失败且 `reply_route.type` 为 `email`
- **THEN** 系统通过 email delivery adapter 发送安全失败通知并记录投递结果

### Requirement: Delivery supports explicit none route
系统 SHALL 支持 `delivery.type=none`，用于 Debug API 或只需要查询接口读取结果的任务。

#### Scenario: None delivery route is used
- **WHEN** Agent job 完成且 `reply_route.type` 为 `none`
- **THEN** 系统不调用外部投递 adapter，但记录 delivery skipped 状态供审计和查询

### Requirement: Long reports are delivered in chunks
系统 SHALL 在最终报告超过目标平台单条消息限制时，将报告分片发送并持久化每个分片状态。

#### Scenario: Report exceeds DingTalk chunk limit
- **WHEN** DingTalk delivery 的报告长度超过配置的单片字符限制
- **THEN** 系统按顺序发送多个分片，每片包含 `part x/y` 标识，并记录每个 delivery chunk

#### Scenario: Report fits in one chunk
- **WHEN** 报告长度未超过目标平台单片字符限制
- **THEN** 系统发送一个分片并将 delivery attempt 标记为成功

### Requirement: Delivery failures do not re-execute Agent jobs
系统 SHALL 将 Delivery 失败与 Agent 执行失败分开处理；Delivery 失败 MUST NOT 触发 Agent job 重新执行。

#### Scenario: Delivery adapter returns transient failure
- **WHEN** Agent job 已经 SUCCEEDED 但 Delivery adapter 返回超时或临时网络错误
- **THEN** 系统记录 delivery failed 或 pending retry 状态，且 Agent job 保持 SUCCEEDED

#### Scenario: Duplicate RabbitMQ job delivery after successful result
- **WHEN** 同一个已 SUCCEEDED job 被重复投递给 worker
- **THEN** 系统不重新执行 Agent，也不重复发送已经成功完成的 delivery attempt

### Requirement: Delivery attempts are auditable
系统 SHALL 持久化每次 delivery attempt 的目标类型、connector、目标安全摘要、状态、错误摘要、开始和结束时间。

#### Scenario: Delivery attempt completes
- **WHEN** 任一 delivery adapter 完成投递
- **THEN** 系统保存 delivery attempt 和 chunk 记录，并关联到 Agent job

#### Scenario: Delivery attempt fails
- **WHEN** 任一 delivery adapter 投递失败
- **THEN** 系统保存安全错误摘要，不记录 token、webhook secret 或敏感目标地址

### Requirement: DingTalk enterprise App delivery sends final reports directly
系统 SHALL 支持 `reply_route.type=dingtalk_enterprise_robot`，通过钉钉企业 App 凭据获取访问令牌并把 Agent 最终报告或安全失败通知直接发送到钉钉目标。

#### Scenario: Enterprise App delivery succeeds
- **WHEN** Agent job 完成且 `reply_route.type` 为 `dingtalk_enterprise_robot`
- **THEN** 系统使用该 route 的 delivery connector 获取 access token、发送钉钉消息，并记录成功的 delivery attempt 和 chunk

#### Scenario: Enterprise App token request fails
- **WHEN** 钉钉企业 App access token 获取失败
- **THEN** 系统将 delivery attempt 标记为失败、保存安全错误摘要，并保持 Agent job 原有执行状态不变

### Requirement: DingTalk webhook robot delivery sends group messages only
系统 SHALL 支持 `reply_route.type=dingtalk_webhook_robot`，按钉钉群机器人 webhook 协议把 Agent 报告发送到群，且该 route MUST NOT 创建 Agent job 或处理用户入口消息。

#### Scenario: Webhook robot delivery succeeds
- **WHEN** Agent job 完成且 `reply_route.type` 为 `dingtalk_webhook_robot`
- **THEN** 系统向 connector 配置的 webhook endpoint 发送群消息，并记录 delivery attempt 和 chunk 状态

#### Scenario: Webhook robot is used as ingress
- **WHEN** 外部请求尝试使用 webhook 群机器人 connector 作为 `from.connector_id`
- **THEN** 系统拒绝该入口请求，不创建 Agent job，也不发布 RabbitMQ 消息

### Requirement: DingTalk delivery chunks preserve ordering
系统 SHALL 对 DingTalk 企业 App 和 webhook 群机器人出口复用统一报告分片逻辑，按顺序发送并持久化每个分片状态。

#### Scenario: DingTalk report exceeds chunk limit
- **WHEN** DingTalk delivery 的报告超过配置的 `DELIVERY_CHUNK_MAX_CHARS`
- **THEN** 系统按顺序发送多个分片，每个分片包含 `part x/y` 标识，并记录每个 chunk 的状态

#### Scenario: One chunk fails
- **WHEN** DingTalk delivery 中任一分片发送失败
- **THEN** 系统记录失败分片和安全错误摘要，delivery attempt 标记为失败，Agent job 不重新执行

