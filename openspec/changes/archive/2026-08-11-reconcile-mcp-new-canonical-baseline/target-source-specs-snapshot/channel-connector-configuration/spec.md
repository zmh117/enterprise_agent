# channel-connector-configuration Specification

## Purpose
TBD - created by archiving change add-channel-ingress-and-delivery. Update Purpose after archive.
## Requirements
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

### Requirement: DingTalk enterprise App connector uses secret references
系统 SHALL 使用 connector 配置表达钉钉企业 App 的 Client ID 和 Client Secret，真实值 MUST 通过环境变量或受控 secret reference 解析，不能明文写入 job、audit、delivery attempt 或仓库文件。

#### Scenario: Enterprise connector resolves credentials
- **WHEN** `dingtalk_enterprise_robot` delivery adapter 需要发送消息
- **THEN** 系统从 connector 的 secret references 解析 Client ID 和 Client Secret，并只在日志和审计中记录 connector ID

#### Scenario: Enterprise connector is missing credentials
- **WHEN** connector 未配置 Client ID 或 Client Secret
- **THEN** 系统将 delivery 标记为配置失败，返回安全错误摘要，且不发起钉钉网络请求

### Requirement: DingTalk webhook robot connector stores endpoint and signing secret safely
系统 SHALL 使用 connector 的 endpoint reference 和 secret reference 表达钉钉 webhook 群机器人 URL 与加签密钥，并在发送前执行 host allowlist 校验。

#### Scenario: Webhook endpoint is allowed
- **WHEN** webhook 群机器人 endpoint 的 host 匹配 connector host allowlist
- **THEN** 系统允许 delivery adapter 发送群消息

#### Scenario: Webhook endpoint is denied
- **WHEN** webhook 群机器人 endpoint 的 host 不在 connector host allowlist 中
- **THEN** 系统阻止外部请求、记录配置错误，并且不保存完整 webhook URL

### Requirement: Webhook robot connector is delivery-only
系统 SHALL 支持将 DingTalk webhook 群机器人 connector 配置为 `allow_ingress=false`、`allow_delivery=true`，并在运行时强制执行。

#### Scenario: Webhook robot configured for delivery
- **WHEN** Agent job 使用 webhook 群机器人 connector 作为 delivery connector
- **THEN** 系统允许投递流程继续执行

#### Scenario: Webhook robot configured for ingress
- **WHEN** 请求使用 webhook 群机器人 connector 作为入口 connector
- **THEN** 系统拒绝入口授权并记录安全审计事件

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

### Requirement: 钉钉企业 App 连接引用受治理企业
每个 `dingtalk_enterprise_stream` 连接 MUST 引用一个钉钉企业内部 ID，且 MUST NOT 使用管理员自由填写的租户字符串定义身份命名空间；连接名称、内部 Connector ID、Client ID 或机器人名称均不得代替企业 Corp ID。

#### Scenario: 创建首个钉钉应用连接
- **WHEN** 管理员为待验证企业提交应用连接名称、Client ID 和 Client Secret
- **THEN** 系统保存企业引用和受控 Secret reference，不要求或接受自由 `tenant_code`

#### Scenario: 创建后续应用连接
- **WHEN** 管理员为已验证企业创建第二个应用连接
- **THEN** 系统引用同一企业记录并在消息阶段校验真实 Corp ID，不创建新的租户命名空间

#### Scenario: 客户端仍提交旧租户字段
- **WHEN** 新建或编辑钉钉应用连接请求提交 `tenant_code` 试图覆盖企业归属
- **THEN** 系统拒绝该可信字段或明确忽略旧兼容输入，持久化关系只来自所选企业 ID

### Requirement: 连接可用性同时受连接和企业状态约束
钉钉应用连接只有在自身启用、运行凭据有效且所属企业为 `ACTIVE` 时才能用于业务入口；企业待验证时连接 MAY 建立 Stream 以收集验证证据，但 MUST NOT 被业务应用选为可运行入口。

#### Scenario: 待验证企业的连接已建立
- **WHEN** Stream SDK 已连接但所属企业仍为 `PENDING_VERIFICATION`
- **THEN** 管理页面显示“已连接，等待企业验证”，业务应用候选和运行时入口均不把该连接视为可用

#### Scenario: 企业被停用
- **WHEN** 应用连接自身仍启用但所属企业变为 `DISABLED`
- **THEN** 系统停止该连接的业务入口并将其从新业务应用渠道选择中排除

#### Scenario: 企业已启用但连接断线
- **WHEN** 企业为 `ACTIVE` 而某个连接处于 `RECONNECTING`
- **THEN** 系统分别报告企业启用和连接重连状态，不显示为“待注册”或“等待企业验证”

### Requirement: 删除连接不得改写历史发布来源
删除或测试数据重建钉钉连接时，系统 SHALL 使连接不再参与活动路由并撤销其专属 Secret；历史 Application Publication、Agent Job 和投递记录中的连接引用 MUST 保持原值并标记为不可用历史来源。

#### Scenario: 删除已被历史发布引用的连接
- **WHEN** 管理员清理一个已被旧应用发布引用的测试连接
- **THEN** 系统不把历史发布自动切换到其他连接，当前应用必须选择新连接并重新发布

#### Scenario: 查看历史运行记录
- **WHEN** 管理员查看由已清理连接产生的历史 Job 或投递记录
- **THEN** 页面显示历史连接名称或 ID 及“已清理／不可用”状态，记录本身仍可读取
