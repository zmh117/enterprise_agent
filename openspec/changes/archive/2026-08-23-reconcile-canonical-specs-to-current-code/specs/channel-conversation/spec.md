## MODIFIED Requirements

### Requirement: Connector configuration supports DingTalk, Grafana, email, webhook, and none
系统 SHALL 至少能表达 DingTalk enterprise Stream ingress、DingTalk callback ingress、DingTalk enterprise robot delivery、DingTalk webhook robot delivery、Grafana alert webhook、email、generic webhook 和 none 这些代码注册 connector 或 route 类型。每种 connector 的方向 MUST 由代码注册表固定，配置不得把 ingress-only 类型改成 delivery，也不得把 delivery-only 类型改成 ingress。

#### Scenario: DingTalk enterprise Stream connector is ingress only
- **WHEN** 配置使用 `dingtalk_enterprise_stream`
- **THEN** 系统允许该 connector 接收受信 Stream 消息
- **AND** 拒绝把它作为 Delivery connector

#### Scenario: DingTalk webhook robot is delivery only
- **WHEN** 配置使用 `dingtalk_webhook_robot`
- **THEN** 系统允许该 connector 发送群消息
- **AND** 拒绝把它作为用户问题 ingress

#### Scenario: Grafana connector is ingress only
- **WHEN** 配置使用 Grafana alert webhook
- **THEN** 系统允许合法告警创建 Job
- **AND** 拒绝把结果投递回该 ingress connector

### Requirement: 公共入站 Connector 必须配置强制认证策略
系统 SHALL 要求受管 Grafana 和 Generic Webhook ingress Connector 使用唯一的强 Bearer Token secret reference，MUST NOT 在 secret 为空、无法解析、认证模式不是 `bearer_v1` 或认证失败时允许请求。

#### Scenario: Connector secret 正常解析
- **WHEN** 已发布 Trigger 引用启用的 ingress Connector、`bearer_v1` 和可解析的唯一 Token
- **THEN** 系统使用标准 `Authorization: Bearer` 执行认证且审计只记录引用和安全结果

#### Scenario: Connector secret 配置为空
- **WHEN** 公共 Webhook Connector 没有 secret reference
- **THEN** Trigger 校验或发布失败，运行时也拒绝请求

#### Scenario: 请求使用HMAC认证
- **WHEN** 请求或配置声明 HMAC、timestamp、nonce 或签名 Header
- **THEN** 系统拒绝该认证模式且不进入 payload 归一化或 Job 创建

### Requirement: DingTalk robots can be configured for ingress and delivery
系统 SHALL 通过不同代码注册 connector 类型区分钉钉 ingress 与 delivery：enterprise Stream 和 callback 类型只用于 ingress，enterprise robot 与 webhook robot 只用于 delivery。系统 MUST NOT 允许同一钉钉 connector 通过配置获得代码未声明的另一方向。

#### Scenario: DingTalk Stream ingress
- **WHEN** 已启用的 `dingtalk_enterprise_stream` 收到合法企业消息
- **THEN** 消息可以进入 Channel ingress 服务
- **AND** 该 connector 不能作为结果投递目标

#### Scenario: DingTalk enterprise robot delivery
- **WHEN** Agent 结果使用 `dingtalk_enterprise_robot` delivery route
- **THEN** 结果可以通过对应 delivery adapter 投递
- **AND** 该 connector 不能接收用户问题创建 Job

#### Scenario: DingTalk webhook robot delivery
- **WHEN** Agent 结果使用 `dingtalk_webhook_robot` delivery route
- **THEN** 结果可以通过对应群机器人 adapter 投递
- **AND** 任何把它配置为 ingress 的请求均失败关闭

### Requirement: 公共 Webhook 入口只接收有界 JSON 请求
系统 SHALL 通过不可预测的 `public_id` 解析已启用 Trigger publication，并 MUST 在处理前执行 Content-Type、请求大小、JSON 结构深度和集合数量限制。本地/Compose HTTP 入口只用于功能测试；当前应用代码不得宣称或替代生产反向代理的 HTTPS 终止。

#### Scenario: 合法JSON请求
- **WHEN** 已发布 Trigger 收到符合上限的 `application/json` 请求
- **THEN** 系统继续执行该 Trigger 的 Bearer 认证和映射流程

#### Scenario: 超大或非JSON请求
- **WHEN** 请求超过配置上限或 Content-Type/JSON 结构不受支持
- **THEN** 系统拒绝请求、记录安全错误摘要且不创建 Agent Job

#### Scenario: 未知public ID
- **WHEN** 请求使用不存在或已轮换的 public ID
- **THEN** 系统返回统一拒绝响应且不泄漏 Trigger 是否曾经存在

### Requirement: Webhook 认证必须 fail closed 并支持防重放
系统 SHALL 只支持 `bearer_v1`，并 MUST 使用 secret reference 解析每个 binding 唯一的强 Bearer Token 后做常量时间比较。Token 缺失、无法解析、格式错误、不匹配或认证模式未知时 MUST 失败关闭。当前实现没有 HMAC、timestamp、nonce 或独立防重放状态；事件重复由认证后的 external event identity 幂等处理。

#### Scenario: Bearer Token验证成功
- **WHEN** `Authorization` Header 中的 Bearer Token 与已发布 binding 引用的 secret 匹配
- **THEN** 系统记录认证成功并继续解析事件

#### Scenario: Secret缺失或解析失败
- **WHEN** Trigger 的 secret 无法解析或请求未提供合法 Bearer 凭证
- **THEN** 系统拒绝请求且不得退化成匿名允许

#### Scenario: 非Bearer认证
- **WHEN** 请求或配置声明 HMAC、timestamp、nonce 或其它认证模式
- **THEN** 系统在 payload 映射和 Job 创建前拒绝

#### Scenario: 已认证事件重复投递
- **WHEN** 同一 binding 再次收到相同 external event identity 的已认证事件
- **THEN** Inbox 幂等返回既有事实且不创建第二个 Event 或 Job

### Requirement: Trigger 发布前必须执行完整安全校验
系统 SHALL 在发布前校验 adapter schema、`bearer_v1` secret reference、服务账号、Agent Publication、routing 约束、来源 Connector、固定 Delivery、幂等和限流配置，任何依赖无效或认证模式不是 Bearer 时 MUST 拒绝发布。

#### Scenario: 发布完整有效的Grafana Trigger
- **WHEN** 草稿引用启用的 ingress Connector、可解析 Bearer secret、启用服务账号、默认诊断 Agent Publication 和允许的钉钉 Delivery
- **THEN** 系统创建不可变 Trigger Publication 并记录 revision、schema version、config hash 和发布人

#### Scenario: 发布缺少认证secret的Trigger
- **WHEN** 草稿选择 Bearer 认证但 secret reference 为空或不可解析
- **THEN** 系统返回字段级校验错误且不创建 Publication

#### Scenario: 发布HMAC Trigger
- **WHEN** 草稿选择 HMAC 或其它非 `bearer_v1` 认证
- **THEN** 系统返回字段级校验错误且不创建 Publication

#### Scenario: 发布越界routing映射
- **WHEN** `project_code`、`environment`、`base` 或 `workshop` 使用 payload 提取但没有非空 allowlist
- **THEN** 系统拒绝发布并指出无界 routing 字段

### Requirement: 管理 API 和页面不得泄漏敏感材料
系统 SHALL 只返回 secret reference、Bearer 凭证配置状态和脱敏摘要，MUST NOT 返回 Bearer Token、完整 Webhook URL 中的敏感参数、密码材料或原始测试 payload，也不得展示不存在的 HMAC 配置与 nonce 状态。

#### Scenario: 管理员读取Trigger详情
- **WHEN** 管理员打开认证配置
- **THEN** 页面仅显示固定 Bearer 认证类型、secret reference 和是否可解析
- **AND** 不显示 secret value

#### Scenario: 管理员轮换public ID
- **WHEN** 授权管理员确认轮换公共入口标识
- **THEN** API 只返回新的 public ID 和失效时间等非 secret 事实
- **AND** 不返回认证 Token

## REMOVED Requirements

### Requirement: HMAC Connector 配置声明签名协议版本
**Reason**: 当前 Webhook authentication schema 与实现只支持 `bearer_v1`，并由测试显式拒绝非 Bearer 认证；不存在 HMAC 配置字段、nonce 状态或验证器。

**Migration**: 受管 Grafana 和 Generic Webhook 使用每 binding 唯一强 Bearer Token；未来如需 HMAC 必须另建 change 并实现完整认证与防重放合同。

## RENAMED Requirements

- FROM: `外部 Webhook 本次不得要求 HMAC 或 HTTPS`
- TO: `外部Webhook当前使用强Bearer且本地HTTP不代表生产安全`
- FROM: `DingTalk robots can be configured for ingress and delivery`
- TO: `DingTalk ingress与delivery使用不同Connector类型`
- FROM: `Webhook 认证必须 fail closed 并支持防重放`
- TO: `Webhook认证必须使用强Bearer并失败关闭`
