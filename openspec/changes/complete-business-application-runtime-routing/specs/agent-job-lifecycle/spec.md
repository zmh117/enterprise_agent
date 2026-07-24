## ADDED Requirements

### Requirement: Agent Job持久化业务应用运行来源
系统 MUST 为命中业务应用创建的 Agent Job 持久化 application ID/code、Application Publication ID、Deployment ID、route ID、应用 config hash 和运行时状态，并 MUST 在发布队列消息前完成持久化。

#### Scenario: 命中应用创建Job
- **WHEN** Channel event 成功解析到活动 Business Application
- **THEN** Job 与其消息、会话和路由信息一起保存完整应用 provenance
- **AND** 管理 API 能回答该 Job 由哪个应用版本处理

#### Scenario: 未命中应用不创建Job
- **WHEN** 钉钉 Channel event 未命中活动业务应用
- **THEN** 系统不创建 Agent Job 或 MQ 消息
- **AND** 既有迁移前 Job 的空 provenance 仍可只读显示为 `legacy_unattributed`

#### Scenario: 读取历史Job
- **WHEN** 管理端读取迁移前创建且没有应用 provenance 的 Job
- **THEN** API 返回 `legacy_unattributed` 或等效状态
- **AND** 不根据当前 Deployment 回填历史归属

### Requirement: Job固定的应用版本贯穿执行生命周期
系统 SHALL 让 Worker、重试和最终 Delivery 使用 Job 已固定的 Agent Publication 与应用 provenance，MUST NOT 在消费、重试或投递时重新解析当前 Business Application Deployment。

#### Scenario: Worker消费后应用已升级
- **WHEN** Job 入队后 Deployment 切换到新 Publication
- **THEN** Worker 仍使用 Job 固定的旧 Agent Publication
- **AND** Job 历史显示旧应用 Publication

#### Scenario: Agent执行重试
- **WHEN** 可重试执行错误触发 Agent Job 重试
- **THEN** 重试继续使用相同应用和 Agent Publication provenance
- **AND** 不因重新解析产生版本漂移

#### Scenario: Delivery单独重试
- **WHEN** Agent 已成功而结果投递失败
- **THEN** 系统只重试固定 reply route 的 Delivery
- **AND** 不重新执行 Agent 或重新解析业务应用

### Requirement: 应用会话策略在Job创建时冻结
系统 MUST 将本阶段已支持的 Session Policy 有效值传入会话和上下文构建流程，并 SHALL 在 Job 或安全运行摘要中记录策略版本来源。

#### Scenario: 应用启用连续对话
- **WHEN** 命中应用的 Publication 启用连续对话并设置最近消息上限
- **THEN** Job 使用应用隔离的 Session 并按该上限加载历史消息

#### Scenario: 应用禁用附件
- **WHEN** 命中应用的 Publication 将附件设为禁用
- **THEN** 系统按既有安全契约拒绝或忽略该事件附件
- **AND** 不使用全局默认重新启用附件

### Requirement: MQ载荷保持最小且不复制应用快照
系统 MUST 保持 RabbitMQ Agent Job 消息只携带 Job ID、correlation ID 和现有最小路由字段，MUST NOT 将 Business Application snapshot、session webhook、Secret 或消息原文复制到队列。

#### Scenario: 发布应用Job
- **WHEN** 命中应用的 Job 已在数据库事务中保存
- **THEN** Publisher 只发布可用于 Worker 回读 Job 的最小消息
- **AND** Worker 从持久化 Job 和固定 Publication 引用恢复运行配置
