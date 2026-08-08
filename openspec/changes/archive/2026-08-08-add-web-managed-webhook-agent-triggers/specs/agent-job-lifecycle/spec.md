## ADDED Requirements

### Requirement: Webhook job 保存可复现的 Trigger 来源
系统 SHALL 为 Webhook 创建的 Agent job 保存 `webhook_event_id`、Trigger definition/publication、服务账号和固定 Agent publication 引用，并 MUST 保持历史 job 在配置变化后仍可追溯。

#### Scenario: Webhook dispatcher 创建 job
- **WHEN** dispatcher 处理一个 `DISPATCH_PENDING` event
- **THEN** job 事务保存 Webhook 来源引用、服务账号、routing、reply route 和固定 Agent revision/hash

#### Scenario: 普通钉钉或 Debug job
- **WHEN** job 不是由受管 Webhook 创建
- **THEN** 新增 Webhook 来源字段保持为空且不改变现有生命周期

### Requirement: Webhook 队列载荷保持最小且可幂等恢复
系统 SHALL 只向 Webhook dispatch 队列发布 event ID 和 correlation ID，并继续只向 Agent job 队列发布 job ID 和 correlation ID；消费者 MUST 通过数据库状态恢复上下文。

#### Scenario: Webhook dispatch 消息重复投递
- **WHEN** 同一个 event ID 被 RabbitMQ 至少一次投递多次
- **THEN** 消费者复用已经关联的 job并确认消息，不重复创建 job

#### Scenario: Agent job 消息重复投递
- **WHEN** Webhook job 已成功或处于不可重复执行状态后再次收到相同 job ID
- **THEN** 现有 job 幂等状态机阻止再次执行 Agent 和重复成功 Delivery
