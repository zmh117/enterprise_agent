## MODIFIED Requirements

### Requirement: Connectors declare allowed directions
系统 SHALL 为每个 Channel/Delivery connector 配置 `allow_ingress` 和 `allow_delivery`，并在运行时强制校验。Webhook ingress 还 MUST 绑定已启用 Connector、已发布 Trigger Binding 和已发布业务应用版本，不得依赖全局 `FEATURE_WEBHOOK_TRIGGERS` 作为长期启停事实源。

#### Scenario: Connector allows ingress
- **WHEN** 请求使用 `allow_ingress=true`、状态已启用且被已发布 Trigger Binding 引用的 connector 作为 `from.connector_id`
- **THEN** 系统允许该 connector 进入签名校验和 Channel 解析流程

#### Scenario: Connector ingress is not published
- **WHEN** connector 允许 ingress 但 Trigger Binding 或业务应用版本仍为草稿、禁用或未发布
- **THEN** 系统不接受该 Webhook 创建 Agent job
- **AND** 系统记录不含凭据的配置拒绝原因

#### Scenario: Connector is not allowed for delivery
- **WHEN** 请求使用 `allow_delivery=false` 的 connector 作为 `delivery.connector_id`
- **THEN** 系统拒绝创建使用该 delivery 的 Agent job 或将 delivery 标记为配置错误

#### Scenario: Legacy webhook flag is present during compatibility
- **WHEN** 兼容期部署仍配置 `FEATURE_WEBHOOK_TRIGGERS`
- **THEN** 系统输出迁移到 Connector/Trigger 发布状态的弃用告警
- **AND** 兼容适配不得自动创建、启用或发布 Connector、Trigger Binding 或业务应用
