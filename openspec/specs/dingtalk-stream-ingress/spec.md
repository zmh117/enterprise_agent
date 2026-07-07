# dingtalk-stream-ingress Specification

## Purpose
TBD - created by archiving change replace-dingtalk-http-webhook-with-stream-ingress. Update Purpose after archive.
## Requirements
### Requirement: DingTalk Stream ingress connects with configured enterprise app credentials
系统 SHALL 使用已配置的钉钉企业 App Client ID/Secret 或 DingTalk Stream 所需凭据，主动建立 DingTalk Stream 长连接并接收用户消息事件。

#### Scenario: Stream connector starts successfully
- **WHEN** Stream ingress worker 启动且 connector 配置包含有效凭据
- **THEN** 系统建立 DingTalk Stream 连接、记录连接成功审计事件，并开始接收消息事件

#### Scenario: Stream connector misses credentials
- **WHEN** Stream ingress worker 启动但缺少必填钉钉凭据
- **THEN** 系统拒绝启动该 connector、记录配置错误，且不创建 Agent job

### Requirement: DingTalk Stream messages are normalized as Channel events
系统 SHALL 将 DingTalk Stream 用户消息事件归一化为包含 `from`、`delivery`、`routing`、`message`、`external_event_id` 和 connector metadata 的内部 Channel event。

#### Scenario: User message is received from Stream
- **WHEN** DingTalk Stream 推送一条受支持的用户文本消息
- **THEN** 系统生成 Channel event，并保留钉钉会话 ID、用户 ID、消息 ID、原始文本、connector ID 和默认 delivery 配置

#### Scenario: Unsupported Stream event is received
- **WHEN** DingTalk Stream 推送不受支持的事件类型或消息类型
- **THEN** 系统忽略该事件、记录 ignored 审计事件，且不创建 Agent job 或 RabbitMQ 消息

### Requirement: DingTalk Stream ingress works without public HTTP callback
系统 SHALL 允许本地或内网部署通过 DingTalk Stream 接收钉钉用户消息，不要求配置公网 HTTPS HTTP webhook 回调地址。

#### Scenario: Local Stream worker receives a message
- **WHEN** 开发者在本地启动 Stream ingress worker 且企业 App 已允许 Stream 事件
- **THEN** 系统可以接收钉钉用户消息并创建 Agent job，而无需暴露 `/webhooks/dingding/agent` 到公网

### Requirement: DingTalk Stream acknowledgement follows persisted dispatch result
系统 SHALL 在完成幂等判断、权限检查、Agent job 持久化和队列发布后，再向 DingTalk Stream 确认消息处理成功。

#### Scenario: Stream message creates a job
- **WHEN** DingTalk Stream 用户消息通过校验并成功创建和发布 Agent job
- **THEN** 系统向 DingTalk Stream 返回成功确认，并记录关联的 `job_id`

#### Scenario: Stream message is rejected before job creation
- **WHEN** DingTalk Stream 用户消息因为认证、格式、权限或 routing 错误被拒绝
- **THEN** 系统向 DingTalk Stream 返回拒绝或失败确认，记录安全摘要，且不创建 Agent job

### Requirement: DingTalk Stream ingress handles reconnects safely
系统 SHALL 在 Stream 长连接断开或临时失败时执行有界退避重连，并确保重连不会绕过幂等、权限或审计。

#### Scenario: Stream connection drops
- **WHEN** DingTalk Stream 连接断开或返回临时错误
- **THEN** 系统记录断线审计事件，按配置退避重连，并在恢复后继续处理新事件

#### Scenario: Event is redelivered after reconnect
- **WHEN** 同一个 DingTalk Stream 事件在重连后再次送达
- **THEN** 系统使用稳定幂等键返回已有 Agent job acknowledgement，不创建重复 job

### Requirement: DingTalk webhook robot remains delivery-only
系统 SHALL 将钉钉 webhook 群机器人作为结果出口能力处理，不得将其作为钉钉用户消息入口。

#### Scenario: Webhook robot connector is configured
- **WHEN** connector 配置类型为钉钉 webhook 群机器人
- **THEN** 系统只允许该 connector 用于 delivery，不启动 Stream ingress 或 HTTP ingress

