# platform-runtime-acceptance Specification

## Purpose
TBD - created by archiving change stabilize-platform-runtime-foundation. Update Purpose after archive.
## Requirements
### Requirement: JavaScript 构建与 CI 必须统一使用 npm
仓库 SHALL 以现有 npm lockfile 为唯一 JavaScript 依赖锁，CI 和容器构建 MUST 使用 `npm ci`，不得继续引用不存在或非权威的 pnpm lockfile。

#### Scenario: Pull Request 执行前端门禁
- **WHEN** CI 安装前端依赖
- **THEN** CI 必须使用 `npm ci` 并在 lockfile 与 package manifest 不一致时失败

### Requirement: 实施必须遵循六阶段 Gate
变更 MUST 按严格授权、Migrator/UoW/Outbox、Secret/Resource、资源重置/Oracle/热加载、管理界面、完整验收六阶段推进；前一阶段未取得测试与数据证据时不得切换下一阶段核心路径。

#### Scenario: 阶段 Gate 未通过
- **WHEN** 当前阶段仍有失败测试、未核验迁移或未解决的数据不变量
- **THEN** 后续阶段不得执行破坏性切换

### Requirement: 本地验收必须证明真实端到端业务链路
最终本地验收 MUST 使用真实本地 Grafana Webhook、Bearer 认证、Inbox/Outbox、RabbitMQ、Job/Worker、真实只读 MySQL 或 SQL Server 工具、结果、Delivery Outbox 和真实 DingTalk 回复形成一条新鲜链路。

#### Scenario: Grafana firing 告警成功处理
- **WHEN** 测试 Grafana 使用有效 Bearer Token 发送合成 firing 事件
- **THEN** 系统必须产生可关联的 ingress、Outbox、Job、tool-call、Delivery 和 DingTalk 回执证据

### Requirement: 验收必须覆盖关键拒绝和恢复路径
验收 MUST 覆盖无效 Webhook Token 不创建 Job、缺失 RBAC 被拒绝、RabbitMQ 中断后 Outbox 恢复、Worker 可重试与 DEAD、Delivery 中断后恢复及全链路 Secret 不泄漏。

#### Scenario: RabbitMQ 在 Outbox 提交后暂时不可用
- **WHEN** Job 与 Outbox 已提交但 RabbitMQ publish 失败
- **THEN** Dispatcher 必须有限重试并在 RabbitMQ 恢复后发布同一幂等 event

#### Scenario: 无效 Token 调用 Webhook
- **WHEN** 请求携带错误 Bearer Token
- **THEN** 系统必须拒绝，且不创建 Inbox、Job 或 Outbox 业务记录

### Requirement: 延期能力不得被误报为已验证
验收报告 MUST 明确声明本次未验证真实 Oracle 11.2.0.4、生产 HTTPS/HMAC、Worker 运行中崩溃恢复和任务取消。

#### Scenario: 本地没有 Oracle
- **WHEN** 本次验收仅完成 Oracle 静态、单元或测试替身检查
- **THEN** 报告必须把真实 Oracle 连接标为 deferred，Oracle Resource Revision 不得进入 PUBLISHED

#### Scenario: 本地 HTTP 链路通过
- **WHEN** Compose 内 HTTP Webhook 功能验证成功
- **THEN** 报告只能声明本地功能通过，不得声明公网生产安全

