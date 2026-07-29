## MODIFIED Requirements

### Requirement: Real-tools smoke test shall verify platform and agent layers
系统 SHALL 提供分层 smoke test，并在最终 Gate 使用新鲜合成事件验证 Grafana Bearer Webhook、Inbox/Job Outbox、RabbitMQ、Agent Worker、真实只读 MySQL 或 SQL Server 工具、Job 结果、Delivery Outbox 与真实 DingTalk 回复。

#### Scenario: 平台层 smoke test
- **WHEN** 开发者执行 real-tools 平台测试
- **THEN** 可以验证 schema head、Internal API service Token、Job fact authorization、published resource snapshot、只读目标解析和安全工具结果

#### Scenario: Agent 层 smoke test
- **WHEN** 开发者通过受保护 Debug 入口提交 Job
- **THEN** 可以查询 Job、steps、tool-calls、dispatch Outbox 和独立 Delivery 状态

#### Scenario: Grafana 到 DingTalk 真实闭环
- **WHEN** 本地 Grafana 使用有效 Bearer Token 发送合成 firing 事件
- **THEN** 同一 correlation 链必须产生真实只读工具证据和真实 DingTalk 送达证据

## ADDED Requirements

### Requirement: Real-tools 验收必须覆盖拒绝与恢复
smoke/integration 验收 MUST 证明无效 Webhook Token 不创建 Job、缺少严格 RBAC 被拒绝、RabbitMQ 恢复后 Outbox 可继续、Worker 错误进入有限 retry/DEAD、Delivery 可独立恢复且 Secret 不泄漏。

#### Scenario: 无效 Bearer Token
- **WHEN** Grafana 请求使用错误 Token
- **THEN** 不得创建 Agent Job 或 Job Dispatch Outbox

#### Scenario: RabbitMQ 短暂中断
- **WHEN** Outbox 已提交而 RabbitMQ 暂时不可用
- **THEN** RabbitMQ 恢复后同一幂等 event 被发布且只产生一个业务结果

### Requirement: Real-tools 报告必须说明本地边界和延期测试
验收报告 MUST 明确 HTTP 仅用于本地/Compose，并将真实 Oracle 11.2.0.4、Worker RUNNING 崩溃恢复、任务取消和生产 HTTPS 标为未实现或延期。

#### Scenario: 本地闭环全部通过
- **WHEN** MySQL/SQL Server 与 DingTalk 链路通过
- **THEN** 报告不得因此声称 Oracle 或公网生产安全已通过
