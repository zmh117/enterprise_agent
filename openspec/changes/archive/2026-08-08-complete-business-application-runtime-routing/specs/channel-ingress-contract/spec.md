## ADDED Requirements

### Requirement: Channel入口在创建Job前解析业务应用路由
系统 SHALL 在完成 Channel event 规范化和外部身份解析后、创建 Agent Job 前执行受信 Business Application route 解析，并 MUST 将业务应用解析与用户业务 routing context 分开。

#### Scenario: 规范化事件命中业务应用
- **WHEN** 受信 Channel event 的部署环境、Trigger type、connector ID 和 routing key 命中活动应用
- **THEN** Channel ingress 使用解析得到的不可变应用运行快照创建 Job
- **AND** 用户消息或模型不能修改应用路由键

#### Scenario: 业务数据环境与部署环境不同
- **WHEN** 事件 routing context 包含 `environment=sanjiu` 且服务运行环境为 `local`
- **THEN** 应用解析使用 `local`
- **AND** Job 业务 routing context 仍包含 `sanjiu`

### Requirement: Channel入口执行明确的配置优先级
系统 MUST 在命中 Business Application 时采用应用 Publication 固定的 Agent 与已支持策略，并 MUST 在未命中应用时失败关闭，不得使用事件或默认 Agent 配置创建 Job。

#### Scenario: 应用和事件Agent一致
- **WHEN** 事件命中应用且两处 Agent 固定信息一致
- **THEN** 系统创建使用应用 Publication Agent 的 Job

#### Scenario: 应用和事件Agent冲突
- **WHEN** 事件命中应用但事件指定了不同的 Agent Publication
- **THEN** Channel ingress 阻止 Job 创建并记录配置冲突
- **AND** 不按事件值或默认值继续执行

#### Scenario: 未命中应用
- **WHEN** 路由结果为 `not_matched`
- **THEN** Channel ingress 不创建 Job 或发布 RabbitMQ 消息
- **AND** 请求向钉钉原会话发送安全配置错误

### Requirement: 应用会话上下文按业务应用隔离
系统 MUST 将命中的稳定 Business Application ID 纳入会话复用边界，并 SHALL 按应用 Publication 中已接线的 Session Policy 构造会话。

#### Scenario: 同一钉钉会话命中不同应用
- **WHEN** 两条事件具有相同外部 conversation ID 但命中不同 Business Application
- **THEN** 系统创建或复用不同的 Agent Session
- **AND** 两个应用的最近消息与会话摘要不相互泄露

#### Scenario: 同一应用升级Publication
- **WHEN** 同一应用激活新 Publication 后收到同一外部会话的新消息
- **THEN** 系统可继续复用该应用的会话
- **AND** 新 Job 单独保存新 Publication provenance

### Requirement: Channel入口对路由阻塞发送安全失败结果
系统 SHALL 将命中后的非重试配置错误交给已注册的 Channel 拒绝通知能力，MUST NOT 因失败通知异常而创建 Agent Job 或将配置错误改为可重试执行错误。

#### Scenario: 应用路由完整性失败
- **WHEN** Channel ingress 收到 `blocked` 路由结果
- **THEN** 系统记录路由失败并请求向原 Channel 发送安全错误
- **AND** 不创建 Job 或发布 RabbitMQ 消息

#### Scenario: 失败通知本身失败
- **WHEN** 原 Channel 失败通知无法送达
- **THEN** 系统记录独立 Delivery 或通知失败审计
- **AND** 不回退执行 Agent
