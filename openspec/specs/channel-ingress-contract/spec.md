# channel-ingress-contract Specification

## Purpose
TBD - created by archiving change add-channel-ingress-and-delivery. Update Purpose after archive.
## Requirements
### Requirement: Channel requests are normalized before Agent job creation
系统 SHALL 在创建 Agent job 前，将所有外部入口请求归一化为包含 `from`、`delivery`、`routing`、`message` 的内部 Channel event。

#### Scenario: Generic channel request is accepted
- **WHEN** 一个已认证入口请求包含有效 `from`、`delivery`、`routing` 和 `message`
- **THEN** 系统使用归一化后的 Channel event 创建 Agent session、Agent job 和 user message

#### Scenario: Missing required channel fields
- **WHEN** 入口请求缺少 `from.type`、`message` 或必填 routing 字段
- **THEN** 系统拒绝请求、记录安全错误摘要，且不创建 Agent job 或 RabbitMQ 消息

### Requirement: Channel ingress is idempotent by external event identity
系统 SHALL 基于 Channel 类型、connector、外部事件 ID 和事件语义生成稳定幂等键，避免 webhook 重试创建重复 Agent job。

#### Scenario: Duplicate channel delivery is received
- **WHEN** 同一个 connector 重复投递相同外部事件 ID 的请求
- **THEN** 系统返回已有 Agent job acknowledgement，不创建第二个 Agent job 或第二条队列消息

#### Scenario: Different channel events use different idempotency keys
- **WHEN** 同一个 connector 收到两个不同外部事件 ID 的请求
- **THEN** 系统为两个请求创建不同幂等键并允许分别创建 Agent job

### Requirement: Grafana alert ingress only creates jobs for firing alerts
系统 SHALL 只为 Grafana `status=firing` 告警创建 Agent job；`resolved` 或其他状态 MUST 被忽略并审计。

#### Scenario: Grafana firing alert creates job
- **WHEN** Grafana webhook payload 的状态为 `firing` 且包含必填专用 routing labels
- **THEN** 系统创建 Agent job、持久化告警摘要并发布 `job_id` 到消息总线

#### Scenario: Grafana resolved alert is ignored
- **WHEN** Grafana webhook payload 的状态为 `resolved`
- **THEN** 系统返回 ignored acknowledgement、记录 `channel.grafana.ignored` 审计事件，且不创建 Agent job

### Requirement: Grafana routing uses dedicated Enterprise Agent labels
系统 SHALL 从 Grafana labels 中读取专用字段 `ea_project_code`、`ea_environment`、`ea_base`、`ea_workshop`、`ea_service` 来构造 routing context。

#### Scenario: Grafana alert has complete Enterprise Agent labels
- **WHEN** Grafana firing alert 包含所有必填 `ea_*` routing labels
- **THEN** 系统将这些字段持久化到 job 的 routing context，并传递给 Agent 工具上下文

#### Scenario: Grafana alert misses routing label
- **WHEN** Grafana firing alert 缺少任一必填 `ea_*` routing label
- **THEN** 系统拒绝创建 Agent job、记录缺失字段摘要，且不发布队列消息

### Requirement: Channel adapters verify source-specific authentication
系统 SHALL 在解析和持久化请求前执行各 Channel adapter 的签名、token 或 connector 认证校验。

#### Scenario: Valid channel credential
- **WHEN** 入口请求提供与 connector 配置匹配的签名或 token
- **THEN** 系统继续执行 Channel event 解析和权限检查

#### Scenario: Invalid channel credential
- **WHEN** 入口请求签名、token 或 connector ID 无效
- **THEN** 系统拒绝请求，且不持久化 Agent session、Agent job 或 user message

