## MODIFIED Requirements

### Requirement: Agent sessions and jobs are persisted
系统 SHALL 在相关生命周期事件发生前或发生时，将 Agent session、Agent Job、用户消息、助手消息、重试元数据、结果摘要、失败原因、来源渠道、请求主体、routing context、reply route，以及每个 Job 固定且符合当前 schema 的请求与有效执行策略持久化到 PostgreSQL。系统 MUST NOT 创建缺少有效 Execution Policy 快照的新 Job。

#### Scenario: New diagnostic request is accepted
- **WHEN** 一个已验证的 Channel 请求通过 Connector 与权限检查
- **THEN** 系统在发布消息总线任务前持久化 Agent session、Agent Job、用户消息、来源渠道、请求主体、routing context 和 reply route

#### Scenario: 业务应用请求固定执行策略
- **WHEN** Channel 请求命中 Business Application Publication
- **THEN** 系统在发布 Job 前持久化不可变的执行策略版本、请求值、有效值和来源 Publication
- **AND** RabbitMQ payload 仍只包含内部 Job 标识与 correlation ID

#### Scenario: Worker重试业务应用Job
- **WHEN** 同一个业务应用 Job 进入延迟重试或被 RabbitMQ 重投递
- **THEN** Worker 继续读取 Job 已保存的执行策略
- **AND** 不重新查询当前活动 Business Application Deployment 来改变限制

#### Scenario: Agent result is produced
- **WHEN** Agent 执行产生最终答案
- **THEN** 系统持久化助手消息、结果摘要、Job 完成时间和可投递结果产物

#### Scenario: Legacy DingTalk request is accepted
- **WHEN** 现有钉钉 webhook 请求使用旧入口且没有业务应用策略
- **THEN** 系统持久化等价的通用渠道字段并保留已有钉钉兼容字段
- **AND** Job 创建服务从固定 Agent Publication 或运行时默认值生成并持久化 v1 Execution Policy

#### Scenario: 迁移旧运行数据
- **WHEN** 升级前数据库包含没有 v1 Execution Policy 的旧 Job
- **THEN** 维护迁移删除旧 Job 及其关联运行数据而不是生成推测性策略
- **AND** 新 schema 对后续 Job 强制要求非空合法策略
