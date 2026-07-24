## ADDED Requirements

### Requirement: 业务应用约束钉钉回复原会话投递
系统 MUST 在业务应用路由命中后要求存在唯一、启用且与 ingress source connector 一致的 `reply_original` Delivery Binding，并 SHALL 使用事件生成的受信临时 reply route 完成实际投递。

#### Scenario: 有效回复原会话Binding
- **WHEN** 应用包含唯一 `reply_original` Binding，connector 与钉钉 Stream 来源一致，事件包含有效 session webhook
- **THEN** 系统将受信 reply route 固定到 Job
- **AND** Delivery Worker 将结果回复到原私聊或群聊

#### Scenario: 缺少回复原会话Binding
- **WHEN** 钉钉 Trigger 命中应用但没有启用的 `reply_original` Binding
- **THEN** 运行时将 route 标记为 `blocked/missing_delivery_binding`
- **AND** 不改用全局固定群或其他 Delivery 类型

#### Scenario: Binding connector不一致
- **WHEN** `reply_original` Binding 的 connector ID 与 ingress source connector ID 不同
- **THEN** 激活预检或运行时校验拒绝该配置
- **AND** 不把临时 session webhook 发送给不匹配的 Connector

### Requirement: 应用Delivery Binding不得持久化临时凭据
系统 MUST 将 Business Application Delivery Binding 作为投递授权和策略，不得在草稿、Publication、runtime status 或审计中保存 session webhook、访问 Token 或完整敏感 URL。

#### Scenario: 发布回复原会话配置
- **WHEN** 管理员发布包含 `reply_original` 的应用
- **THEN** Publication 只保存 delivery type、connector ID 和非敏感策略
- **AND** 临时投递目标只从每次受信钉钉事件进入受保护 Job reply route

#### Scenario: 管理端查看Delivery状态
- **WHEN** 管理员查看应用或 Job 的 Delivery 摘要
- **THEN** 页面显示类型、connector、状态和安全目标摘要
- **AND** 不显示可直接调用的 session webhook

### Requirement: 应用投递失败不得改变Agent执行结果
系统 SHALL 延续 Delivery 与 Agent 执行分离的生命周期，MUST 在应用投递失败时记录并重试 Delivery，而不是创建新 Job、切换应用版本或重新执行 Agent。

#### Scenario: Agent成功但钉钉投递暂时失败
- **WHEN** Agent Job 已成功生成结果而 session webhook 投递发生可重试错误
- **THEN** 系统保留 Agent 成功状态并按现有策略重试 Delivery
- **AND** 重试使用原 Job 的应用 Publication 和 reply route

#### Scenario: session webhook已过期
- **WHEN** Delivery 检测到原 session webhook 永久过期
- **THEN** 系统将投递标记为不可重试失败并记录安全原因
- **AND** 不改发到应用未授权的钉钉群或用户

