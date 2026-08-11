# dingtalk-stream-ingress Specification

## Purpose
TBD - created by archiving change replace-dingtalk-http-webhook-with-stream-ingress. Update Purpose after archive.
## Requirements
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

### Requirement: DingTalk Stream Connector 状态可被管理端观测
系统 SHALL 为每个钉钉 Stream Connector 提供期望状态、有效观测状态、加载 revision、注册状态、心跳、最近消息和安全错误摘要。

#### Scenario: Connector 正常可用
- **WHEN** Runtime 正在续约且 SDK 已注册
- **THEN** 管理端显示 READY、当前 loaded revision、最近心跳和最近消息时间

#### Scenario: Runtime 失联
- **WHEN** Runtime 心跳过期
- **THEN** 管理端显示 STALE，而不是沿用上一次 READY

### Requirement: DingTalk webhook robot remains delivery-only
系统 SHALL 将钉钉 webhook 群机器人作为结果出口能力处理，不得将其作为钉钉用户消息入口。

#### Scenario: Webhook robot connector is configured
- **WHEN** connector 配置类型为钉钉 webhook 群机器人
- **THEN** 系统只允许该 connector 用于 delivery，不启动 Stream ingress 或 HTTP ingress

### Requirement: 钉钉Stream私聊使用机器人身份路由应用
系统 MUST 为钉钉 Stream 私聊从受信 payload 或 Connector 配置解析稳定 bot identity，并 SHALL 生成 `bot:<normalized_bot_identity>` 作为应用 routing key。

#### Scenario: 私聊payload包含robotCode
- **WHEN** Stream 私聊事件包含受信 `robotCode`
- **THEN** 适配器将其规范化为 bot identity 并生成私聊 routing key
- **AND** 同一机器人收到的不同用户私聊使用同一应用 route

#### Scenario: payload缺少robotCode但Connector已配置
- **WHEN** 私聊事件没有可用 robotCode 且来源 Connector 配置了固定 bot identity
- **THEN** 适配器使用 Connector bot identity 生成 routing key

#### Scenario: 无法取得受信bot identity
- **WHEN** payload 和 Connector 都不能提供 bot identity
- **THEN** 事件不得使用发送人、会话名或消息内容猜测 routing key
- **AND** 系统记录未解析原因并按无匹配兼容规则处理

### Requirement: 钉钉Stream群聊使用会话身份路由应用
系统 MUST 为钉钉 Stream 群聊生成 `conversation:<normalized_conversation_id>` routing key，并 MUST 使用当前消息发送人的统一身份执行 RBAC。

#### Scenario: 群聊中机器人被提及
- **WHEN** 合法群聊消息满足现有提及规则并包含 conversation ID
- **THEN** 适配器按 connector 与 conversation routing key 解析应用
- **AND** Agent/API 权限仍按当前发送人而不是整个群计算

#### Scenario: 两个群使用同一机器人
- **WHEN** 两个群具有不同 conversation ID 且使用同一 Stream Connector
- **THEN** 系统允许它们分别绑定到不同业务应用

### Requirement: 业务应用路由不改变Stream快速确认和幂等语义
系统 SHALL 在现有 Stream ACK 时限内完成接收确认，并 MUST 保持基于来源 connector 与外部事件 ID 的幂等边界；应用路由与版本切换不得为同一事件创建第二个 Job。

#### Scenario: 同一消息重复投递
- **WHEN** 钉钉重复投递相同外部事件 ID
- **THEN** 系统至多创建一个 Agent Job
- **AND** 重复事件不会因为应用 Publication 已切换而创建新版本 Job

#### Scenario: 路由解析耗时或失败
- **WHEN** 应用路由解析未能在 Stream 回调处理窗口完成或返回配置错误
- **THEN** 适配器遵循现有快速 ACK 与异步处理契约
- **AND** 记录可定位的接收、路由和通知状态

### Requirement: 钉钉Stream应用错误回复原会话
系统 SHALL 对已命中应用后的安全配置错误使用当前事件的有效 session webhook 向原私聊或群聊发送失败说明，并 MUST 遮蔽内部异常、hash、凭据和堆栈。

#### Scenario: 命中应用但Delivery配置无效
- **WHEN** 钉钉消息命中应用但 reply-original Delivery 校验失败
- **THEN** 用户收到简短的“应用配置暂不可用”或等效错误
- **AND** 审计保存稳定 reason code 供管理员排查

### Requirement: Stream 消息携带并校验企业上下文
系统 MUST 从受信钉钉 Stream 消息提取应用连接、`senderCorpId`、`chatbotCorpId`、`senderStaffId`、`senderNick`、事件时间和稳定事件 ID，并在进入身份解析前校验连接所属企业；企业字段不得由客户端管理请求或消息正文覆盖。

#### Scenario: 已验证企业收到正常消息
- **WHEN** 启用连接收到 SDK 认证消息，且两个 Corp ID 与所属 `ACTIVE` 企业一致
- **THEN** 系统将企业内部 ID 和受信身份字段写入规范化 Channel Event，继续身份解析

#### Scenario: 消息缺少 Staff ID
- **WHEN** 受信事件缺少可用 `senderStaffId`
- **THEN** 系统拒绝身份解析且不创建候选、身份、观察或 Agent Job

### Requirement: 待验证企业消息只能形成验证证据
所属企业为 `PENDING_VERIFICATION` 时，Stream worker MUST 将满足条件的受信测试消息交给企业验证流程，并 MUST 阻止其进入普通 Channel Dispatch、身份发现、Application Access 和 Agent Job 流程。

#### Scenario: 待验证消息完成 Corp ID 验证
- **WHEN** 同一受信测试消息包含非空且相等的 `senderCorpId` 与 `chatbotCorpId`
- **THEN** 系统固化企业 Corp ID 并确认消息，不创建 Channel Outbox、身份候选或 Agent Job

#### Scenario: 待验证消息包含业务问题
- **WHEN** 测试消息正文同时看起来像普通 Agent 请求
- **THEN** 系统仍只执行企业验证，不调用模型或 API Capability，并提示管理员验证成功后重新发送业务消息

### Requirement: Corp ID 不一致时失败关闭并治理告警
已验证企业的任何应用连接收到缺失或不匹配的 Corp ID 时，系统 MUST 拒绝该消息、阻止身份与 Job 写入并产生安全治理告警；系统不得自动修改企业或连接归属。

#### Scenario: 后续应用实际属于另一企业
- **WHEN** 新应用连接收到的受信消息 Corp ID 与所选企业不同
- **THEN** 系统拒绝消息并把连接标记为企业校验错误，告警不包含消息正文或认证材料

#### Scenario: 重连后收到不匹配消息
- **WHEN** Stream 重连成功后第一条消息的 Corp ID 与企业不一致
- **THEN** 重连状态不得绕过企业校验，系统仍拒绝分发

### Requirement: 非活动企业不处理业务 Stream 消息
所属企业为 `DISABLED` 或 `ARCHIVED` 时，系统 MUST 停止或拒绝其全部应用连接的业务入口；已有连接心跳或 SDK 回调不得使企业自动恢复。

#### Scenario: 企业停用时仍收到 SDK 回调
- **WHEN** 停用动作与在途 Stream 消息并发
- **THEN** 消息在持久化 Job 前重新校验企业状态并失败关闭

#### Scenario: 只重新启动 Runtime
- **WHEN** 管理员重启已停用或归档企业的连接 Runtime
- **THEN** 系统不恢复业务处理，必须完成显式企业恢复和 Corp ID 复验

### Requirement: 企业校验参与 Stream 幂等确认
Stream 重试和重连 MUST 使用稳定事件 ID 保持企业验证与业务分发幂等；同一事件不得既被用作企业验证又在重试时创建业务 Job。

#### Scenario: 企业验证事件被重投
- **WHEN** 完成企业验证的测试事件再次到达
- **THEN** 系统返回已有验证确认且不进入业务分发

#### Scenario: 正常业务事件被重投
- **WHEN** `ACTIVE` 企业的同一业务事件重复到达
- **THEN** 系统复用现有 Channel Event 或 Job 结果，不重复更新昵称审计、观察记录或创建 Job

