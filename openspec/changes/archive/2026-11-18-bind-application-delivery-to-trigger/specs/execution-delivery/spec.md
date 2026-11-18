## MODIFIED Requirements

### Requirement: 业务应用约束钉钉回复原会话投递
系统 MUST 在业务应用路由命中后要求命中 Trigger 存在唯一、启用且与 ingress source connector 一致的 `reply_original` Delivery Binding，并 SHALL 使用事件生成的受信临时 reply route 完成实际投递。不同触发器的投递 MUST 独立校验和选择，不得使用其他入口的目标。既有不可变 Publication 保持原已冻结规则；新 Publication MUST 固定每入口关联模式。

#### Scenario: 有效回复原会话Binding
- **WHEN** 命中 Trigger 包含唯一 `reply_original` Binding，connector 与钉钉 Stream 来源一致，事件包含有效 session webhook
- **THEN** 系统将受信 reply route 固定到 Job
- **AND** Delivery Worker 将结果回复到原私聊或群聊

#### Scenario: 缺少回复原会话Binding
- **WHEN** 钉钉 Trigger 命中应用但没有为此 Trigger 配置启用的 `reply_original` Binding
- **THEN** 运行时将 route 标记为 `blocked/missing_delivery_binding`
- **AND** 不改用其他 Trigger 的 Binding、全局固定群或其他 Delivery 类型

#### Scenario: Binding connector不一致
- **WHEN** `reply_original` Binding 的 connector ID 与命中 Trigger 的 ingress source connector ID 不同
- **THEN** 激活预检或运行时校验拒绝该配置
- **AND** 不把临时 session webhook 发送给不匹配的 Connector

## ADDED Requirements

### Requirement: Webhook 按命中应用入口选择结果投递
新应用 Publication SHALL 按命中 Trigger 的自然路由身份选择最多一个 Delivery，并在 Job 中冻结该结果路由。其他入口的人员、连接器或回调目标 MUST NOT 被复用。未配置投递或钉钉私聊目标人员为空 SHALL 执行并保存结果且不发送消息。

#### Scenario: 同一应用具有两个 Webhook
- **WHEN** 两个 Webhook 分别绑定不同收件人或回调，其中一个入口触发任务
- **THEN** Job 只冻结该入口绑定的目标，不受绑定数组排列影响

#### Scenario: 当前入口只保存结果
- **WHEN** 命中 Webhook 未配置投递且其他入口具有投递
- **THEN** reply route 为 none，不借用其他入口的配置
