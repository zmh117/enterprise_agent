## MODIFIED Requirements

### Requirement: Channel requests are normalized before Agent job creation
系统 SHALL 在创建 Agent Job 前将外部请求归一化为 Channel event，但 requester、业务应用发布、Connector binding 和 Execution Scope MUST 由服务端已发布绑定与身份解析产生，外部 payload 不得覆盖这些授权事实。

#### Scenario: Generic channel request is accepted
- **WHEN** 一个已通过 Connector 认证的请求包含有效事件 ID 和消息内容
- **THEN** 系统从 binding 解析身份、应用、范围和 Delivery，并创建隔离 Session、Job 与 Outbox

#### Scenario: Payload attempts to override scope
- **WHEN** 请求 payload 提交与 binding 不同的 user、application、environment、base 或 workshop
- **THEN** 系统必须拒绝或忽略越权字段，且不得扩大 Execution Scope

#### Scenario: Missing required channel fields
- **WHEN** 入口请求缺少事件 ID、消息或 adapter 必需字段
- **THEN** 系统拒绝请求、记录安全错误摘要，且不创建 Job 或 Outbox

### Requirement: Grafana routing uses dedicated Enterprise Agent labels
系统 SHALL 把 Grafana `ea_*` labels 作为告警分类和诊断元数据，但授权身份、业务应用发布和允许的 Execution Scope MUST 来自已发布 Webhook binding。Payload labels 不得选择任意应用或扩大 scope。

#### Scenario: Grafana labels match binding scope
- **WHEN** firing alert 的 `ea_*` labels 位于 binding 允许范围
- **THEN** 系统持久化安全告警摘要并使用 binding 固化的应用与 Execution Scope 创建 Job

#### Scenario: Grafana label exceeds binding scope
- **WHEN** alert label 指向 binding 未授权的 environment、base 或 workshop
- **THEN** 系统拒绝创建 Job 并记录范围不匹配

#### Scenario: Optional diagnostic label is missing
- **WHEN** alert 缺少非授权用途的诊断 label
- **THEN** adapter 可以按已发布 binding 的 schema 决定拒绝或记录缺失，但不得从 payload 猜测授权范围

### Requirement: Channel adapters verify source-specific authentication
系统 SHALL 在解析和持久化前认证来源。所有外部 HTTP Webhook MUST 使用各 binding 唯一的强 Bearer Token；DingTalk Stream 等非 HTTP Webhook Channel 继续使用其受支持的 Provider 认证。

#### Scenario: Valid Webhook Bearer Token
- **WHEN** 请求使用标准 `Authorization: Bearer <token>` 且与 binding 的平台 Secret 匹配
- **THEN** 系统继续解析、幂等和权限检查

#### Scenario: Invalid or missing credential
- **WHEN** Token、Provider credential 或 Connector ID 无效
- **THEN** 系统拒绝请求，且不持久化 Session、Job、消息或 Outbox

#### Scenario: Webhook binding has no resolvable Secret
- **WHEN** binding 的 Token Secret 缺失或禁用
- **THEN** binding 必须为 MISCONFIGURED，入口不得 fail open

## ADDED Requirements

### Requirement: 外部 Webhook 本次不得要求 HMAC 或 HTTPS
本地/Compose 阶段 Webhook 契约 MUST 只要求强 Bearer Token，不实现 HMAC、timestamp、nonce 或 HTTPS；运行边界必须标明仅限本地功能测试。

#### Scenario: Grafana 在本地 Compose 调用 HTTP
- **WHEN** Grafana 使用有效 Bearer Token 调用本地 HTTP endpoint
- **THEN** 系统可以正常处理，且验收不得将其表述为公网生产安全
