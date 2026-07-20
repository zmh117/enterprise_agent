## ADDED Requirements

### Requirement: 公共入站 Connector 必须配置强制认证策略
系统 SHALL 要求受管 Webhook ingress Connector 使用 Bearer Token 或 HMAC-SHA256 secret reference，MUST NOT 在 secret 为空、无法解析或认证策略未知时允许请求。

#### Scenario: Connector secret 正常解析
- **WHEN** 已发布 Trigger 引用启用的 ingress Connector 和可解析 secret
- **THEN** 系统可以使用该 secret 执行配置的认证策略且审计只记录引用

#### Scenario: Connector secret 配置为空
- **WHEN** 公共 Webhook Connector 没有 secret reference
- **THEN** Trigger 校验/发布失败，运行时也拒绝请求

### Requirement: Connector 认证和 Delivery 方向保持隔离
系统 SHALL 分别校验 Trigger 来源 Connector 的 `allow_ingress` 和固定结果 Connector 的 `allow_delivery`，外部 payload MUST NOT 改变任一 Connector ID 或方向。

#### Scenario: payload 提供另一个 Delivery Connector
- **WHEN** 已认证 payload 包含与 Trigger publication 不同的 delivery connector 字段
- **THEN** 系统忽略该字段并继续使用已发布的固定 Delivery，或在严格映射下拒绝报文

#### Scenario: Trigger 引用 delivery-only Connector 作为来源
- **WHEN** 草稿把钉钉 webhook 机器人等 delivery-only Connector 配置为 ingress
- **THEN** 发布校验拒绝该配置

### Requirement: HMAC Connector 配置声明签名协议版本
系统 SHALL 为 HMAC ingress Connector 保存签名版本、时间戳 header、nonce header、签名 header 和允许时间窗，MUST 使用受支持的 canonical body 规则。

#### Scenario: 未知签名版本
- **WHEN** Trigger 引用未注册的 HMAC 签名协议版本
- **THEN** 系统拒绝发布而不是猜测厂商签名格式
