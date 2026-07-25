## MODIFIED Requirements

### Requirement: Channel ingress is idempotent by external event identity
系统 SHALL 基于 Channel 类型、Connector 和外部事件 ID 生成稳定幂等键，并在可靠 Inbox 层阻止重复外部投递产生第二条 Outbox、Agent Job 或队列消息。

#### Scenario: Duplicate channel delivery is received
- **WHEN** 同一个 Connector 重复投递相同外部事件 ID 的请求
- **THEN** 系统返回已有 Channel event 或 Job acknowledgement，不创建第二条 Inbox、Outbox、Agent Job 或队列消息

#### Scenario: Same external message reaches different connectors
- **WHEN** 两个不同 Connector 收到相同外部消息 ID
- **THEN** 系统为每个 Connector 保存一个独立 Channel event，并允许后续分别路由

#### Scenario: Different channel events use different idempotency keys
- **WHEN** 同一个 Connector 收到两个不同外部事件 ID 的请求
- **THEN** 系统生成不同幂等键并允许分别保存和 dispatch

## ADDED Requirements

### Requirement: DingTalk Channel 事件使用事务 Inbox/Outbox
系统 SHALL 在一个数据库事务中持久化钉钉标准化 Channel 事件和待发布 Outbox，并由独立 Publisher 重试发布。

#### Scenario: RabbitMQ 暂时不可用
- **WHEN** Channel Inbox/Outbox 已提交但 RabbitMQ 不可用
- **THEN** 事件保持 pending，不丢失也不创建重复 Inbox，并在 RabbitMQ 恢复后继续发布

#### Scenario: Outbox 发布成功
- **WHEN** Publisher 成功把事件标识发布到 RabbitMQ
- **THEN** 系统原子更新 Outbox 为 published，并记录发布时间

#### Scenario: Publisher 重启
- **WHEN** Publisher 在 claim 后、确认 published 前退出
- **THEN** 超时 claim 可以被安全重试，消费者和 Inbox 幂等保证不会产生重复 Job

### Requirement: Channel 队列载荷保持最小且不包含回复凭据
系统 SHALL 只在 Channel dispatch 队列中传递 channel event ID 和 correlation ID，MUST NOT 传递 Client Secret、sessionWebhook、原始 payload 或完整用户附件。

#### Scenario: 发布 DingTalk Channel 事件
- **WHEN** Outbox Publisher 构造 RabbitMQ 消息
- **THEN** 消息只包含用于加载持久化事件的标识和追踪字段

#### Scenario: Dispatcher 需要回复路由
- **WHEN** Python Dispatcher 处理事件并调用现有 Channel Ingress
- **THEN** Dispatcher 从受控存储加载必要回复上下文，不从 RabbitMQ 明文载荷获取

### Requirement: Python Dispatcher 复用现有 Channel Ingress
系统 SHALL 由 Python Dispatcher 将持久化事件转换为现有 Channel Event，并调用唯一的 `ChannelIngressService`。

#### Scenario: 已绑定业务应用的事件
- **WHEN** Dispatcher 处理命中活动 Business Application Trigger 的事件
- **THEN** 现有身份映射、RBAC、Publication 固定、Session/Execution Policy 和 Job 创建继续生效

#### Scenario: 事件未命中业务应用
- **WHEN** Dispatcher 处理没有可用 Trigger Binding 的事件
- **THEN** 系统使用现有配置错误处理和安全回复，不回退到默认 Agent

#### Scenario: 本变更完成
- **WHEN** 多钉钉 Runtime 后端上线
- **THEN** Agent 执行器、Agent 并行和结果投递实现保持不变
