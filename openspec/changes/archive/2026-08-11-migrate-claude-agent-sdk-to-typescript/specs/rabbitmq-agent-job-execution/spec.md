## ADDED Requirements

### Requirement: Python Worker必须拥有跨语言执行的业务状态
系统 SHALL 继续由 Python `agent-worker` 消费 RabbitMQ、claim Job、复核授权、决定 retry/终态、持久化安全 Tool 事件、保存结果并创建 Delivery Outbox。TypeScript Runtime MUST NOT 直接消费业务队列、修改 Job 状态、发布 retry 消息或创建 Delivery。

#### Scenario: TypeScript执行成功
- **WHEN** Runtime 为一次 attempt 返回合法 completed 终态
- **THEN** Python Worker 在本地事务中保存结果、将 Job 转为 SUCCEEDED 并创建 Delivery Outbox 后再确认 RabbitMQ 消息

#### Scenario: TypeScript执行失败
- **WHEN** Runtime 返回稳定 failed 终态或协议客户端抛出分类错误
- **THEN** Python Worker 使用现有 retry policy 决定 RETRY_WAIT 或 FAILED/TIMEOUT，并在终态创建一次安全失败投递

#### Scenario: Runtime越权写业务状态
- **WHEN** 部署检查 Runtime 数据库授权和容器配置
- **THEN** Runtime 只具备模型连接/active Secret 所需最小读权限，不具备 Agent Job、授权或 Delivery 写权限

### Requirement: RabbitMQ确认必须等待本地终态提交
Worker MUST 在 TypeScript Runtime 终态被验证且本地 Job/结果/Delivery 事务提交后才 ack 当前 RabbitMQ 消息。Runtime 已完成但本地提交失败时，Worker SHALL 通过相同 invocation/digest 恢复终态，不得直接启动新的模型执行。

#### Scenario: Runtime完成后数据库提交失败
- **WHEN** Runtime 已返回 completed 但 Python 本地事务回滚
- **THEN** RabbitMQ 消息不被错误确认，重试使用相同 invocation/digest 获取既有安全终态

#### Scenario: 重复RabbitMQ消息
- **WHEN** 相同 dispatch event 被重复投递
- **THEN** Job claim、Runtime invocation 幂等和本地终态共同阻止重复模型执行与重复 Delivery
