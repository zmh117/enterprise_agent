## ADDED Requirements

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

