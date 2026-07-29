## MODIFIED Requirements

### Requirement: Connector secrets are referenced, not persisted in job payloads
系统 SHALL 让新建和发布的 Connector 只保存 `secret://platform/<code>`；MUST NOT 将 Secret、Token、Webhook credential 写入 Job、audit、Delivery attempt 或 Resource Revision。旧 `env:` 只可显式导入。

#### Scenario: Connector uses platform secret reference
- **WHEN** Channel adapter 需要认证入口或发送 Delivery
- **THEN** infrastructure 层解析 Connector 的平台 Secret，并只记录 Connector ID 和 Secret configured 状态

#### Scenario: Audit summary is written
- **WHEN** 系统记录 Connector 相关审计
- **THEN** payload 不包含真实 Token、Secret、密文或敏感 URL 参数

#### Scenario: New Connector submits env reference
- **WHEN** 新建或发布 Connector 使用 `env:`、`vault:` 或 `kms:`
- **THEN** 系统必须拒绝并要求使用可用的平台 Secret

## ADDED Requirements

### Requirement: Connector 缺少 Secret 时必须进入 MISCONFIGURED
已配置 Connector 的必需 Secret 缺失、禁用或无法解析时，系统 MUST 保留配置与历史，将 Connector 标为 MISCONFIGURED，并停用 ingress 和 delivery；不得生成 Secret、使用空值或 fail open。

#### Scenario: DingTalk Connector Secret 消失
- **WHEN** active Secret 被禁用
- **THEN** Connector 停止接收和投递，管理端显示安全错误并允许重新绑定与测试

### Requirement: 外部 Webhook Connector 必须统一使用标准 Bearer
Grafana 和 Generic Webhook Connector MUST 使用标准 `Authorization: Bearer`；每个 binding 使用唯一 Token。旧 `X-Grafana-Token` 翻译入口和无认证入口 MUST 被删除。

#### Scenario: Grafana 使用标准 Bearer
- **WHEN** Grafana Webhook 配置发送有效 Authorization Header
- **THEN** 对应 binding 正常认证并处理事件

#### Scenario: 请求只发送旧 Grafana Header
- **WHEN** 请求只带 `X-Grafana-Token`
- **THEN** 系统必须拒绝且不走兼容翻译
