## Why

系统虽然已经能接收 Grafana `firing` 告警和标准化 Channel 请求，并通过 RabbitMQ 触发只读诊断 Agent 后投递到钉钉，但入口仍依赖固定路由、固定报文结构和 seed 配置，管理员无法安全地接入其他系统、发布映射规则或追踪每次触发。现在需要把现有 Webhook 入口提升为可治理、可审计、可回滚的 Web 管理能力，同时保持统一身份、Agent 发布快照和只读工具边界。

## What Changes

- 增加 Webhook Trigger 定义、草稿 revision、不可变 publication、启停和回滚模型，第一版支持 Grafana Alertmanager 与通用 JSON 两类入站模板。
- 增加管理端 Webhook 列表、创建/编辑、认证、报文映射、触发条件、诊断范围、默认诊断 Agent、固定 Delivery、测试预览、发布历史和事件历史页面。
- 为每个 Webhook 提供不可变公开入口标识；请求先执行大小限制、Content-Type、Bearer Token 或 HMAC-SHA256 认证、时间窗/防重放、限流和幂等校验，再进入持久化 Inbox。
- 使用安全的声明式字段映射和模板把第三方 JSON 转换为内部 Channel event；外部报文不得覆盖已发布的 Agent、工具权限、服务账号或 Delivery 目标，只允许在配置明确授权的 routing 字段范围内提供值。
- 为 Webhook 绑定不可登录的受管服务账号，并复用统一 RBAC 校验其项目、Agent、工具和平台数据范围；禁用服务账号或 Trigger 后立即拒绝新事件。
- 持久化 Webhook event、认证/过滤/去重结果、Trigger publication、payload hash、安全摘要、correlation ID 和 Agent job 关联；成功持久化后返回 `202 Accepted`，异步创建和执行 Agent job。
- Grafana 第一版继续只为 `firing` 创建 Agent job，`resolved` 仅记录并返回 ignored；默认按 `groupKey` 或稳定 fingerprint 去重，避免告警风暴。
- Webhook 创建的 job 固定 Trigger publication 和当时的 Agent publication；配置更新不得改变已接收或已排队事件的执行语义。
- 结果继续复用 ResultDeliveryService，按已发布配置发送到固定钉钉 Connector/目标，长报告沿用分片投递，Delivery 失败不得重跑 Agent。
- 第一版仅允许使用代码注册、已启用、已分配且通过 RBAC 的现有只读诊断工具；不在本 change 中支持动态创建任意 HTTP API、MCP、代码、Shell、写 SQL 或其他可执行工具。

## Capabilities

### New Capabilities

- `webhook-trigger-management`: Webhook Trigger 的定义、草稿、校验、发布、回滚、Web 管理页面以及 Grafana/通用 JSON 配置模型。
- `webhook-event-processing`: 外部 Webhook 的安全认证、持久化 Inbox、声明式映射、过滤、限流、幂等、异步 acknowledgement 和事件执行状态。
- `service-account-identity`: 不可交互登录的服务账号、Webhook 绑定和统一 RBAC 权限边界。

### Modified Capabilities

- `channel-ingress-contract`: 允许已发布 Webhook Trigger 将不同第三方报文安全归一化为 Channel event，并在 job 创建前固定来源配置版本。
- `channel-connector-configuration`: 入站 Connector 增加 fail-closed 的 Bearer/HMAC 认证策略、防重放参数和受控密钥引用要求。
- `agent-job-lifecycle`: Webhook job 关联固定 Trigger publication、Webhook event 和服务账号，并保持队列载荷最小化。
- `agent-audit-permission`: 非人类服务账号必须通过与 Web/钉钉一致的 Agent、项目、工具和平台范围授权后才能创建和执行 job。
- `result-delivery-routing`: 受管 Webhook 的 Delivery 由已发布 Trigger 固定，外部 payload 不得任意选择 Connector 或目标。

## Impact

- PostgreSQL 新增 Webhook Trigger/revision/publication/event、认证防重放和服务账号相关持久化字段或表，并为 Agent job 增加 Webhook 来源版本关联。
- FastAPI 新增版本化 Webhook 公共入口和认证/映射/Inbox 服务；现有 `/webhooks/grafana/alert` 需要兼容迁移到受管 Trigger，通用标准化入口继续作为受控兼容接口而不是面向任意外部系统的配置面。
- `ChannelIngressService`、job 创建、统一权限、Agent publication 固定、RabbitMQ 发布和 ResultDeliveryService 将复用现有链路并增加 Webhook 来源上下文。
- React 管理端新增 Webhook 配置、测试、发布和事件审计页面，以及对应的管理权限 action。
- Secret 继续只保存引用或加密值；原始 payload 不进入 RabbitMQ、Agent prompt、普通日志或不受控审计字段。
- 本 change 依赖统一用户/RBAC 与默认 Agent publication 能力完成落地；不新增向量库、Redis 依赖或动态 HTTP API 工具执行器。
