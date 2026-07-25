## MODIFIED Requirements

### Requirement: DingTalk Stream ingress connects with configured enterprise app credentials
系统 SHALL 由单个 `dingtalk-runtime` 使用控制面中所有已启用且配置完整的钉钉企业 App Connector，为每个 Connector 建立独立 DingTalk Stream Client。

#### Scenario: 多个 Stream Connector 启动成功
- **WHEN** Runtime 取得活动租约且控制面返回多个已启用的有效 Connector
- **THEN** 系统分别建立 Stream 连接、在注册完成后上报 READY，并开始接收各 Connector 的消息事件

#### Scenario: 单个 Stream Connector 缺少凭据
- **WHEN** 一个已启用 Connector 缺少有效 Client ID 或 Client Secret
- **THEN** 系统只将该 Connector 标记为配置或认证失败，不影响其他 Connector，且不创建其 Channel 事件

#### Scenario: 动态启用 Stream Connector
- **WHEN** 管理员在 Runtime 运行期间启用一个配置完整的钉钉 Connector
- **THEN** Runtime 在协调周期内建立新连接，不要求修改或重启 Compose

### Requirement: DingTalk Stream acknowledgement follows durable ingress persistence
系统 SHALL 在 Connector 级幂等判断、标准化 Channel 事件和 Inbox/Outbox 事务持久化成功后向 DingTalk Stream 确认；不得等待 Agent 执行完成。

#### Scenario: Stream message is durably accepted
- **WHEN** DingTalk Stream 用户消息通过基础校验并成功写入 Channel Inbox/Outbox
- **THEN** Runtime 向 DingTalk 返回成功确认，并记录关联的 channel event ID

#### Scenario: Duplicate Stream message is received
- **WHEN** 相同 Connector 重复投递相同 external event ID
- **THEN** 系统返回已有事件的成功确认，不写入第二条 Inbox 或 Outbox

#### Scenario: Durable persistence fails
- **WHEN** Inbox/Outbox 事务失败或内部接入 API不可用
- **THEN** Runtime 不返回成功持久化确认，记录安全错误并允许钉钉按协议重试

### Requirement: DingTalk Stream ingress handles reconnects safely
系统 SHALL 为每个 Stream Connector 独立执行有界退避重连，并确保一个 Connector 的断线、认证失败或 revision 变化不影响其他 Connector。

#### Scenario: 单个 Stream 连接断开
- **WHEN** Connector A 的 Stream 连接断开而 Connector B 保持健康
- **THEN** Runtime 只将 A 标记为 RECONNECTING 并执行退避，B 保持 READY

#### Scenario: Event is redelivered after reconnect
- **WHEN** 同一个 Connector 的相同事件在重连后再次送达
- **THEN** 系统使用 Connector 和 external event ID 组成的稳定幂等键返回已有事件，不创建重复 Channel 事件或 Job

#### Scenario: Connector revision changes during reconnect
- **WHEN** Connector 正在自动重连且控制面提供了更高 revision
- **THEN** Runtime 串行终止旧重连状态并以新 revision 重建一个 Client

## ADDED Requirements

### Requirement: DingTalk Stream Connector 状态可被管理端观测
系统 SHALL 为每个钉钉 Stream Connector 提供期望状态、有效观测状态、加载 revision、注册状态、心跳、最近消息和安全错误摘要。

#### Scenario: Connector 正常可用
- **WHEN** Runtime 正在续约且 SDK 已注册
- **THEN** 管理端显示 READY、当前 loaded revision、最近心跳和最近消息时间

#### Scenario: Runtime 失联
- **WHEN** Runtime 心跳过期
- **THEN** 管理端显示 STALE，而不是沿用上一次 READY
