## ADDED Requirements

### Requirement: Connectors declare allowed directions
系统 SHALL 为每个 Channel/Delivery connector 配置 `allow_ingress` 和 `allow_delivery`，并在运行时强制校验。

#### Scenario: Connector allows ingress
- **WHEN** 请求使用 `allow_ingress=true` 的 connector 作为 `from.connector_id`
- **THEN** 系统允许该 connector 进入签名校验和 Channel 解析流程

#### Scenario: Connector is not allowed for delivery
- **WHEN** 请求使用 `allow_delivery=false` 的 connector 作为 `delivery.connector_id`
- **THEN** 系统拒绝创建使用该 delivery 的 Agent job 或将 delivery 标记为配置错误

### Requirement: Connector secrets are referenced, not persisted in job payloads
系统 SHALL 通过 secret reference、环境变量或受控配置读取 connector 密钥，MUST NOT 将 secret/token/webhook secret 写入 Agent job、audit payload 或 delivery attempt 摘要。

#### Scenario: Connector uses secret reference
- **WHEN** Channel adapter 需要验证签名或发送 delivery
- **THEN** 系统通过 connector 配置中的 secret reference 读取密钥，并只在审计中记录 connector ID

#### Scenario: Audit summary is written
- **WHEN** 系统记录 connector 相关审计事件
- **THEN** 审计 payload 不包含真实 token、secret 或 webhook URL 中的敏感参数

### Requirement: Delivery connectors enforce endpoint allowlists
系统 SHALL 在执行 HTTP delivery 前校验 connector 的 endpoint host allowlist 或等效安全策略。

#### Scenario: Delivery target host is allowed
- **WHEN** delivery target host 匹配 connector allowlist
- **THEN** 系统允许 delivery adapter 发起请求

#### Scenario: Delivery target host is denied
- **WHEN** delivery target host 不在 connector allowlist 中
- **THEN** 系统阻止外部请求、记录非重试配置错误，且不泄露完整 URL

### Requirement: Connector configuration supports DingTalk, Grafana, email, webhook, and none
系统 SHALL 至少能表达 DingTalk webhook robot、DingTalk enterprise robot、Grafana alert webhook、email、generic webhook 和 none 这些 connector 或 route 类型。

#### Scenario: DingTalk connector is both ingress and delivery
- **WHEN** DingTalk connector 同时配置 `allow_ingress=true` 和 `allow_delivery=true`
- **THEN** 系统允许该 connector 接收用户问题并发送结果

#### Scenario: Grafana connector is ingress only
- **WHEN** Grafana connector 配置 `allow_ingress=true` 且 `allow_delivery=false`
- **THEN** 系统允许 Grafana 告警创建 job，但拒绝把结果投递回 Grafana connector
