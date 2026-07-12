## MODIFIED Requirements

### Requirement: Docker Compose 必须可验证完整闭环
系统 SHALL 提供 Docker Compose 级验证方式，证明 `api-server`、PostgreSQL 18、RabbitMQ 4 Management 和 `agent-worker` 能协同完成 Agent Job，并保持正常发布、消费确认、重试和 dead-letter 语义。

#### Scenario: curl 验证成功闭环
- **WHEN** 使用 Docker Compose 启动服务并通过 curl 提交调试问题
- **THEN** 系统返回 `job_id`，worker 经 RabbitMQ 4 消费后将 job 更新为 `SUCCEEDED`，查询 job 能看到最终诊断报告

#### Scenario: 验证 RabbitMQ 4 失败路由
- **WHEN** smoke 测试分别触发可重试错误和不可重试错误
- **THEN** RabbitMQ 4 中的 retry/dead-letter 路由与 job 状态、重试元数据和审计记录保持一致
