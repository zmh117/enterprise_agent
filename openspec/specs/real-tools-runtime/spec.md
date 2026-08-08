# real-tools-runtime Specification

## Purpose
TBD - created by archiving change stabilize-real-tools-runtime-and-loki-diagnostics. Update Purpose after archive.
## Requirements
### Requirement: Real-tools profile shall start the topology-aware platform
系统 SHALL 提供明确的 `real-tools` 运行模式，用于启动拓扑化 `internal-api-platform`，并使 `api-server` 与 `agent-worker` 通过 `INTERNAL_API_BASE_URL=http://internal-api-platform:9000` 调用该平台。

#### Scenario: 启动 real-tools 主线
- **WHEN** 开发者按文档使用 `real-tools` profile 启动 Docker Compose
- **THEN** 系统启动 `internal-api-platform`、`api-server`、`agent-worker`、`postgres` 和 `rabbitmq`
- **AND** `agent-worker` 环境变量中的 `INTERNAL_API_BASE_URL` 指向 `http://internal-api-platform:9000`

#### Scenario: real-tools 不依赖 local platform
- **WHEN** 系统运行在 `real-tools` 模式
- **THEN** Agent 工具请求 SHALL 进入 `internal-api-platform`
- **AND** 系统 MUST NOT 要求同时启动 `local-internal-api-platform`

### Requirement: Runtime modes shall be documented and distinguishable
系统 SHALL 文档化 fake、mock-tools、local-tools、real-tools 四种运行模式的用途、启动命令、关键环境变量和验收标准。

#### Scenario: 开发者选择运行模式
- **WHEN** 开发者阅读 README 或等价文档
- **THEN** 文档明确说明 fake 用于无外部工具、mock-tools 用于假证据、local-tools 用于宿主 Loki 快速联调、real-tools 用于正式拓扑化工具平台

#### Scenario: 错误 profile 配置可被识别
- **WHEN** `FEATURE_REAL_INTERNAL_TOOLS=true` 但 `INTERNAL_API_BASE_URL` 没有指向当前已启动的平台服务
- **THEN** 文档和 smoke test SHALL 提供检查命令帮助开发者发现配置不一致

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

### Requirement: Missing real-tools configuration shall fail safely
系统 SHALL 在 real-tools 缺少 topology、secret、Loki base URL 或访问授权时返回安全错误，不得误报为成功查询。

#### Scenario: 缺少平台 secret
- **WHEN** real-tools 请求需要的 secret env 未配置
- **THEN** Internal API Platform MUST 返回非敏感错误摘要
- **AND** 响应 MUST NOT 泄露 secret 名称对应的真实值

#### Scenario: 未授权用户访问目标
- **WHEN** 请求用户无权访问指定 environment/base/workshop
- **THEN** Internal API Platform SHALL 拒绝请求并记录访问决策

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

