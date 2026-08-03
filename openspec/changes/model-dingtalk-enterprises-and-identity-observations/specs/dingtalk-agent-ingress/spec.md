## ADDED Requirements

### Requirement: Agent 入口按企业和钉钉用户解析身份
钉钉 Agent 入口 MUST 使用规范化事件中的钉钉企业内部 ID 和 `senderStaffId` 查找当前身份，并 MUST 同时确认企业、身份和内部用户均处于可用状态；Connector ID 不得作为身份唯一键或人员归属条件。

#### Scenario: 同一用户从第二个应用访问
- **WHEN** 启用用户通过同企业另一个绑定活动应用发布的连接发送消息
- **THEN** 系统解析到同一人员，并继续按该连接命中的 Application Publication 计算访问

#### Scenario: 身份启用但企业停用
- **WHEN** 消息对应身份和人员启用，但所属企业已停用
- **THEN** 系统拒绝创建 Agent Job，不允许身份状态绕过企业治理

#### Scenario: 企业和 Staff ID 不匹配任何身份
- **WHEN** 受信消息无法解析到当前启用身份
- **THEN** 系统进入未绑定候选或恢复候选流程，返回安全提示且不创建 Agent Job

### Requirement: 应用观察不授予 Application Access
系统 MUST 根据消息实际命中的连接、活动 Application Publication 和当前启用用户计算 DingTalk Application Access；应用观察记录只能说明历史来源，不得扩大或恢复应用访问。

#### Scenario: 身份曾通过应用 A 被观察但消息命中应用 B
- **WHEN** 当前消息来自应用 B 且应用 B 没有绑定活动 Application Publication
- **THEN** 系统不得因为存在应用 A 的观察记录而路由到应用 A 或授予访问

#### Scenario: 消息命中已发布应用
- **WHEN** 当前连接绑定活动 Application Publication 且实际发送人解析为启用用户
- **THEN** 系统授予该应用访问并继续计算 Agent 能力上限、应用能力子集和用户 Capability 可用状态

### Requirement: 正式身份观察与昵称先于 Job 创建
对已解析身份的消息，Agent 入口 MUST 在创建 Job 前幂等写入身份最近使用、应用观察以及符合事件游标的昵称和昵称审计，并 MUST 在写入后再次使用当前企业、身份和用户状态计算访问。

#### Scenario: 新昵称消息创建 Job
- **WHEN** 业务消息携带晚于当前游标的非空昵称且所有治理条件满足
- **THEN** 系统在同一处理链中先保存昵称和观察，再创建并分发 Agent Job

#### Scenario: 昵称更新后身份被并发停用
- **WHEN** 身份事实写入完成后、Job 创建前身份被管理员停用
- **THEN** 最终状态复核拒绝 Job，不以先前解析结果继续

#### Scenario: 身份事实写入失败
- **WHEN** 最近使用、观察或应写昵称审计无法持久化
- **THEN** 系统不创建 Job，并通过现有安全失败投递路径返回可理解结果

### Requirement: 群聊继续按实际发送人隔离身份
群聊中的企业、身份、应用访问和 ONES Capability 可用性 MUST 按每条消息的实际 `senderStaffId` 独立计算；同群成员、机器人应用或历史观察记录不得共享身份与个人凭据。

#### Scenario: 同一群两个用户先后提问
- **WHEN** 两个钉钉用户在同一群通过同一应用发送消息
- **THEN** 系统分别解析各自企业身份和内部用户，分别计算 ONES 绑定、默认 Team 和个人凭据

#### Scenario: 群中一个用户未绑定
- **WHEN** 已绑定用户和未绑定用户处于同群，而未绑定用户发送消息
- **THEN** 系统只为实际发送人形成候选并拒绝 Job，不复用已绑定群成员身份
