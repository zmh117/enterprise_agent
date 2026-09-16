# channel-conversation Specification

## Purpose
定义 Channel、钉钉、Webhook、会话、消息和附件的受治理入口、持久化、幂等处理与投递契约，确保外部事件只能通过已发布路由进入系统。
## Requirements

<!-- Reconciled from mcp_new capability: `channel-connector-configuration` -->

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

### Requirement: Connector 认证和 Delivery 方向保持隔离
系统 SHALL 分别校验 Trigger 来源 Connector 的 `allow_ingress` 和固定结果 Connector 的 `allow_delivery`，外部 payload MUST NOT 改变任一 Connector ID 或方向。

#### Scenario: payload 提供另一个 Delivery Connector
- **WHEN** 已认证 payload 包含与 Trigger publication 不同的 delivery connector 字段
- **THEN** 系统忽略该字段并继续使用已发布的固定 Delivery，或在严格映射下拒绝报文

#### Scenario: Trigger 引用 delivery-only Connector 作为来源
- **WHEN** 草稿把钉钉 webhook 机器人等 delivery-only Connector 配置为 ingress
- **THEN** 发布校验拒绝该配置


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

<!-- Reconciled from mcp_new capability: `channel-ingress-contract` -->

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

### Requirement: Channel附件信封保护短期凭证
系统 SHALL 只在受控媒体下载边界使用附件短期来源凭证。为支持可恢复异步下载，系统 MAY 使用平台主密钥短期加密凭证并保存类型和过期时间，但 MUST NOT 持久化明文或把明文/密文写入RabbitMQ、日志、审计、API或调试输出；终态或过期后 MUST 清除密文。

#### Scenario: Adapter receives temporary media credential
- **WHEN** 外部payload包含下载附件所需的短期凭证
- **THEN** 数据库只可保存短期密文、类型和过期时间，其他持久化输出只保留内部attachment ID及安全来源摘要

### Requirement: Channel附件事件保持端到端幂等
系统 SHALL 将Channel、connector、外部事件、外部消息和附件序号纳入稳定幂等语义。

#### Scenario: Attachment event is redelivered
- **WHEN** connector重复投递同一附件事件
- **THEN** 系统返回已有确认且不新增message、attachment、对象或任务

### Requirement: 受管 Webhook 在进入 Channel 前固定来源配置
系统 SHALL 从已发布 Trigger 生成 Channel event，并 MUST 固定 Trigger publication、Agent publication、服务账号、routing policy 和 Delivery 引用后再调用通用 Channel ingress。

#### Scenario: 受管 Webhook 生成 Channel event
- **WHEN** Webhook event 通过认证、映射、过滤、幂等和服务账号权限预检
- **THEN** dispatcher 使用事件中固定的 publication 引用生成 Channel event 并创建 Agent job

#### Scenario: Trigger 在排队期间发布新 revision
- **WHEN** event 已进入 Inbox 后管理员发布新的 Trigger revision
- **THEN** 该 event 仍使用接收时固定的 Trigger 和 Agent publication，不读取新草稿或当前指针

### Requirement: 标准化 Channel event 不携带原始 Webhook payload
系统 SHALL 只把有界 message、受控 routing、来源标识和固定 reply route 交给 Channel ingress，MUST NOT 将完整原始 payload、认证 header、nonce 或 secret 写入 session、job、消息队列或 Agent prompt。

#### Scenario: 第三方 payload 包含敏感扩展字段
- **WHEN** Webhook body 除映射字段外还包含 token、URL、个人信息或大对象
- **THEN** 标准化 Channel event 排除这些未声明字段，只保留脱敏安全摘要

### Requirement: Channel入口在创建Job前解析业务应用路由
系统 SHALL 在完成 Channel event 规范化和外部身份解析后、创建 Agent Job 前执行受信 Business Application route 解析，并 MUST 将业务应用解析与用户业务 routing context 分开。

#### Scenario: 规范化事件命中业务应用
- **WHEN** 受信 Channel event 的部署环境、Trigger type、connector ID 和 routing key 命中活动应用
- **THEN** Channel ingress 使用解析得到的不可变应用运行快照创建 Job
- **AND** 用户消息或模型不能修改应用路由键

#### Scenario: 业务数据环境与部署环境不同
- **WHEN** 事件 routing context 包含 `environment=sanjiu` 且服务运行环境为 `local`
- **THEN** 应用解析使用 `local`
- **AND** Job 业务 routing context 仍包含 `sanjiu`

### Requirement: Channel入口执行明确的配置优先级
系统 MUST 在命中 Business Application 时采用应用 Publication 固定的 Agent 与已支持策略，并 MUST 在未命中应用时失败关闭，不得使用事件或默认 Agent 配置创建 Job。

#### Scenario: 应用和事件Agent一致
- **WHEN** 事件命中应用且两处 Agent 固定信息一致
- **THEN** 系统创建使用应用 Publication Agent 的 Job

#### Scenario: 应用和事件Agent冲突
- **WHEN** 事件命中应用但事件指定了不同的 Agent Publication
- **THEN** Channel ingress 阻止 Job 创建并记录配置冲突
- **AND** 不按事件值或默认值继续执行

#### Scenario: 未命中应用
- **WHEN** 路由结果为 `not_matched`
- **THEN** Channel ingress 不创建 Job 或发布 RabbitMQ 消息
- **AND** 请求向钉钉原会话发送安全配置错误

### Requirement: 应用会话上下文按业务应用隔离
系统 MUST 将稳定 Business Application ID、命中的 Application Publication ID 和 execution scope hash 纳入会话复用边界，并 SHALL 按该 Publication 中已接线的 Session Policy 构造会话。Application Publication 或 execution scope 变化时 MUST 创建新会话，历史会话保持只读可追溯。
#### Scenario: 同一钉钉会话命中不同应用
- **WHEN** 两条事件具有相同外部 conversation ID 但命中不同 Business Application
- **THEN** 系统创建或复用不同的 Agent Session
- **AND** 两个应用的最近消息与会话摘要不相互泄露
#### Scenario: 同一应用升级Publication
- **WHEN** 同一应用激活新 Publication 后收到同一外部会话的新消息
- **THEN** 系统为新 Publication 创建新 Agent Session
- **AND** 旧 Session、消息和摘要保持历史只读，不进入新 Publication 的上下文
#### Scenario: 应用执行范围发生变化
- **WHEN** 同一应用 Publication 的有效 execution scope hash 与既有 Session 不同
- **THEN** 系统创建隔离 Session 并按新范围重新执行授权和上下文边界校验

### Requirement: Channel入口对路由阻塞发送安全失败结果
系统 SHALL 将命中后的非重试配置错误交给已注册的 Channel 拒绝通知能力，MUST NOT 因失败通知异常而创建 Agent Job 或将配置错误改为可重试执行错误。

#### Scenario: 应用路由完整性失败
- **WHEN** Channel ingress 收到 `blocked` 路由结果
- **THEN** 系统记录路由失败并请求向原 Channel 发送安全错误
- **AND** 不创建 Job 或发布 RabbitMQ 消息

#### Scenario: 失败通知本身失败
- **WHEN** 原 Channel 失败通知无法送达
- **THEN** 系统记录独立 Delivery 或通知失败审计
- **AND** 不回退执行 Agent

### Requirement: 钉钉身份拒绝事件生成安全发现记录

系统 SHALL 在已认证且已持久化的钉钉 Channel event 明确因身份从未绑定、身份停用或解绑、或所属用户停用而拒绝时，幂等生成安全的未绑定身份发现记录，并 SHALL 保持拒绝响应、不创建 Agent session、Agent Job、user message 或 RabbitMQ Job 消息。

#### Scenario: 未绑定身份事件被拒绝

- **WHEN** 一个有效钉钉 Channel event 无法解析到任何历史外部身份
- **THEN** 系统 SHALL 在返回现有未授权结果前持久化安全发现记录，且不得进入 Agent 调度链路

#### Scenario: 历史身份不可用事件被拒绝

- **WHEN** 一个有效钉钉 Channel event 对应停用、已解绑身份或停用系统用户
- **THEN** 系统 SHALL 持久化可关联原人员的安全发现记录，且不得把身份解析为其它用户

#### Scenario: 重复拒绝事件

- **WHEN** 同一来源渠道事件因重试再次进入身份拒绝处理
- **THEN** 系统 SHALL 幂等确认已有发现记录，不得创建重复发现消息、Agent Job 或 RabbitMQ Job 消息

#### Scenario: 发现投影提交失败

- **WHEN** 系统无法在身份拒绝事务中安全提交发现投影
- **THEN** 系统 SHALL 保持 fail-closed、不得创建 Agent Job，并返回不含消息正文或敏感信息的可重试错误分类

### Requirement: 外部Webhook当前使用强Bearer且本地HTTP不代表生产安全
本地/Compose 阶段 Webhook 契约 MUST 只要求强 Bearer Token，不实现 HMAC、timestamp、nonce 或 HTTPS；运行边界必须标明仅限本地功能测试。

#### Scenario: Grafana 在本地 Compose 调用 HTTP
- **WHEN** Grafana 使用有效 Bearer Token 调用本地 HTTP endpoint
- **THEN** 系统可以正常处理，且验收不得将其表述为公网生产安全

<!-- Reconciled from mcp_new capability: `continuous-agent-conversation` -->

### Requirement: 群聊和私聊使用稳定且隔离的会话身份
系统 SHALL 根据Channel、connector、project、会话类型和外部身份生成稳定session key并原子解析或创建session。群聊 MUST 以外部群conversation为边界，私聊 MUST 以请求人和机器人身份为边界。

#### Scenario: 同一群聊连续提问
- **WHEN** 同一connector、project和群conversation先后发送不同事件
- **THEN** 系统将消息关联到同一session，并为每个新事件创建幂等job

#### Scenario: 同一用户连续私聊
- **WHEN** 同一用户通过同一connector和project连续私聊同一机器人
- **THEN** 系统复用该用户的私聊session

#### Scenario: 会话标识跨范围碰撞
- **WHEN** 相同外部标识出现在不同会话类型、project或connector
- **THEN** 系统创建隔离session且不共享上下文

### Requirement: 会话消息保持幂等顺序和发送人归属
系统 SHALL 为session内消息分配单调sequence，保存外部消息ID、角色、发送人身份、展示名、类型和时间，并通过外部事件幂等阻止重复消息。

#### Scenario: 群内不同成员依次提问
- **WHEN** 两名群成员在同一群session中先后发送消息
- **THEN** 系统按确定顺序保存两条消息并保留各自发送人

#### Scenario: 钉钉重投同一消息
- **WHEN** connector重复投递相同事件或消息ID
- **THEN** 系统返回已有结果且不新增session、message、attachment或job

### Requirement: Agent获得有界连续上下文
系统 SHALL 从PostgreSQL读取当前session的滚动摘要、摘要游标后的最近消息和可用附件文本，并按配置的消息数、单附件和总上下文预算构造conversation context。

#### Scenario: 用户追问上一轮结论
- **WHEN** 同一session中的问题依赖前序问题和回答
- **THEN** Agent上下文包含相关最近消息或覆盖这些消息的滚动摘要

#### Scenario: 群聊上下文被注入
- **WHEN** Agent为群session构建上下文
- **THEN** 历史用户消息带发送人归属且不混入其他群、私聊、project或connector内容

#### Scenario: 上下文超过预算
- **WHEN** 历史消息和附件文本超过配置预算
- **THEN** 系统优先保留当前问题与最近消息，使用摘要覆盖更早内容并标记截断

### Requirement: 滚动摘要可并发安全推进并允许降级
系统 SHALL 使用摘要版本和覆盖到的message sequence原子更新摘要；摘要失败 MUST NOT 阻止使用最近消息窗口执行当前job。

#### Scenario: 并发job更新摘要
- **WHEN** 同一session的两个job并发推进摘要
- **THEN** 系统只提交当前版本的有效摘要且不倒退摘要游标

#### Scenario: 摘要生成失败
- **WHEN** ConversationSummarizer超时或失败
- **THEN** 系统记录安全失败并使用受限最近消息窗口继续

### Requirement: 连续上下文读取遵守权限和审计
系统 SHALL 在读取历史消息或附件文本前校验session、project、connector和请求人权限，并记录不含正文的读取审计。

#### Scenario: 请求读取其他私聊
- **WHEN** 请求人没有目标私聊session权限
- **THEN** 系统拒绝读取且不泄漏消息、摘要或附件内容

#### Scenario: 合法上下文读取
- **WHEN** worker为授权job读取所属session历史
- **THEN** 系统返回有界上下文并审计消息范围和截断状态

<!-- Reconciled from mcp_new capability: `dingtalk-agent-ingress` -->

### Requirement: DingTalk message identity is parsed
The system SHALL parse and persist the DingTalk Stream conversation identity, actual DingTalk sender identity, source channel, connector identity, external event identity, and user message content needed to resolve an active Business Application Publication and create an Agent session and Agent job. Private and group messages MUST resolve the actual sender independently and MUST NOT use a group-level shared user, administrator, or service account as the external execution subject.

#### Scenario: User asks a diagnostic question
- **WHEN** a verified DingTalk Stream message contains a user diagnostic question
- **THEN** the system persists the conversation identity, actual sender identity, source channel, connector identity, external event identity, original user message and resolved Application Publication context

#### Scenario: Two users send messages in one group
- **WHEN** two DingTalk group messages have different actual senders
- **THEN** the system resolves and persists two independent internal users and never shares an ONES subject snapshot between them

### Requirement: DingTalk ingress is idempotent
The system SHALL use DingTalk Stream event identifiers, message identifiers, or a deterministic idempotency key to avoid creating duplicate Agent jobs for retried or redelivered Stream events.

#### Scenario: Duplicate Stream event is received
- **WHEN** the same DingTalk Stream event or message is delivered more than once
- **THEN** the system returns the existing Agent job acknowledgement instead of creating another Agent job

### Requirement: DingTalk receives immediate acknowledgement
The system SHALL send a quick DingTalk Stream acknowledgement after a job is persisted and dispatched, without waiting for Claude Code Agent execution to finish.

#### Scenario: Job is created successfully
- **WHEN** the system creates and dispatches an Agent job from a DingTalk Stream message
- **THEN** DingTalk receives an acknowledgement indicating the task has been accepted and analysis is starting

### Requirement: DingTalk receives final Agent results
The system SHALL send the final Agent report or failure notice through the configured DingTalk delivery route after asynchronous job execution completes.

#### Scenario: Agent job succeeds
- **WHEN** an Agent job reaches SUCCEEDED with a final report
- **THEN** the system sends the report to the configured DingTalk delivery target, defaulting to the originating DingTalk conversation when no override is configured

#### Scenario: Agent job fails
- **WHEN** an Agent job reaches FAILED or TIMEOUT
- **THEN** the system sends a failure notice with a safe failure reason to the configured DingTalk delivery target

### Requirement: DingTalk ingress与delivery使用不同Connector类型
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

### Requirement: DingTalk enterprise App can receive final Agent results
系统 SHALL 支持通过钉钉企业 App 出口将最终报告或失败通知发送回配置的钉钉目标，目标可以来自 reply route 或 connector 默认配置。

#### Scenario: Reply route contains enterprise target
- **WHEN** Agent job 的 reply route 指定企业 App 钉钉目标
- **THEN** 系统使用该目标发送最终报告，并将投递结果关联到原 Agent job

#### Scenario: Reply route omits enterprise target
- **WHEN** Agent job 的 reply route 使用 `dingtalk_enterprise_robot` 但未显式指定目标
- **THEN** 系统使用 connector metadata 中的默认钉钉目标；若默认目标缺失则标记 delivery 配置失败

### Requirement: DingTalk webhook robot is not a user-question ingress
系统 SHALL 将钉钉 webhook 群机器人限定为结果出口能力，MUST NOT 通过该 connector 接收用户问题或创建 Agent job。

#### Scenario: User sends message to webhook robot
- **WHEN** webhook 群机器人相关请求到达系统入口
- **THEN** 系统不会把该请求解析为用户问题，也不会创建 Agent job

#### Scenario: Webhook robot receives final report
- **WHEN** Agent job 使用 `dingtalk_webhook_robot` 作为 delivery route
- **THEN** 系统把最终报告作为群消息发送到配置的钉钉群机器人 webhook

### Requirement: DingTalk delivery uses safe acknowledgement and failure semantics
系统 SHALL 将钉钉投递结果与 Agent 执行结果分离，钉钉发送失败 MUST NOT 改写已经成功或失败的 Agent job 执行状态。

#### Scenario: DingTalk delivery fails after Agent success
- **WHEN** Agent job 已经 SUCCEEDED 但钉钉企业 App 或 webhook 群机器人发送失败
- **THEN** 系统只更新 delivery attempt/chunk 状态并记录安全错误摘要，Agent job 保持 SUCCEEDED

### Requirement: DingTalk Stream支持MVP媒体入站
系统 SHALL 将钉钉JPEG/PNG/WebP图片及DOCX/XLSX/PPTX/Markdown文件归一化为Channel附件，并安全拒绝未支持媒体。

#### Scenario: Supported DingTalk image arrives
- **WHEN** Stream adapter收到有效的MVP图片媒体引用
- **THEN** adapter创建图片attachment并进入受控下载和存储流程

#### Scenario: Supported DingTalk document arrives
- **WHEN** Stream adapter收到有效现代Office或Markdown媒体引用
- **THEN** adapter创建文档attachment并保留事件、消息和附件序号幂等关系

#### Scenario: Unsupported DingTalk media arrives
- **WHEN** adapter收到DOC/XLS/PPT、PDF、压缩包、音视频或未知媒体
- **THEN** 系统不解析内容并返回不会触发无穷重投的安全确认

### Requirement: 附件处理不阻塞Stream快速确认
系统 SHALL 在持久化session、message、attachment和WAITING_INPUT job后快速ACK，并异步下载与提取附件。

#### Scenario: Supported document is accepted
- **WHEN** 文档符合入口数量和声明大小限制
- **THEN** Stream入口先确认接收，job等待附件终态后再进入Agent队列

### Requirement: 钉钉媒体凭证保持短寿命
系统 SHALL 使用受控钉钉客户端获取媒体。download code MAY 使用平台主密钥短期加密落库以支持异步恢复，但明文和密文 MUST NOT进入队列、日志、审计、API或调试输出，并 MUST 在下载终态或过期后清除。临时URL、access token和session webhook MUST NOT作为媒体来源凭证持久化。

#### Scenario: Media download succeeds
- **WHEN** adapter使用有效临时凭证下载附件
- **THEN** 系统只保存内部对象引用、散列和安全来源摘要，并清除加密来源凭证

### Requirement: DingTalk identity resolution is tenant isolated
The system SHALL resolve DingTalk identities using the tenant/corp associated with the ingress connector and MUST NOT share a binding solely because another tenant uses the same `senderStaffId`.

#### Scenario: Same staff ID appears in two tenants
- **WHEN** two enabled connectors from different tenants receive messages with the same `senderStaffId`
- **THEN** each message resolves only through its own tenant binding

### Requirement: DingTalk permission uses internal user roles
The system SHALL evaluate DingTalk Agent, tool and platform access using the resolved internal user and enabled roles, while preserving the external identity and connector only as source context and audit evidence.

#### Scenario: Web role grant enables DingTalk request
- **WHEN** an administrator grants an internal user's role access to the default diagnostic Agent and the user's bound DingTalk identity sends a request
- **THEN** DingTalk ingress observes the same role grant without duplicating a DingTalk-specific permission record

### Requirement: 钉钉应用访问来自活动路由和启用用户
第一版 DingTalk Application Access MUST 在消息命中绑定活动 Application Publication 的启用连接器，且实际发送人解析为启用内部用户时成立；系统 MUST NOT 要求额外应用用户白名单、应用访问角色或Capability `use` Grant。

#### Scenario: 活动路由和用户均有效
- **WHEN** 钉钉消息命中唯一活动Application Publication且发送人映射到启用内部用户
- **THEN** 系统允许创建Job，并以该应用Publication的Capability Allowlist作为运行资格上限

#### Scenario: 路由未配置活动应用
- **WHEN** 连接器没有唯一活动Application Publication
- **THEN** 系统按现有路由失败关闭语义拒绝Job，不回退到默认Capability配置

#### Scenario: 内部用户已停用
- **WHEN** 发送人的钉钉身份存在但所属内部用户已停用
- **THEN** 系统拒绝创建Job并通过安全投递路径返回中文账户状态提示

### Requirement: 未绑定钉钉身份返回安全自助提示
当实际发送人无法解析为启用内部用户时，系统 MUST 不创建Agent Job或外部执行主体，并 SHALL 通过受控钉钉回复给出不暴露内部用户、应用或权限信息的绑定提示。

#### Scenario: 未知发送人访问应用
- **WHEN** 钉钉消息来自未绑定发送人
- **THEN** 系统不创建Job，并返回安全中文提示引导完成内部账号/钉钉身份绑定

### Requirement: ONES 可用性不改变钉钉应用访问判定
用户缺少 ONES 身份、default Team或有效Token时，系统 SHALL 保留其对已命中钉钉应用的基础访问，但 MUST 不暴露或执行依赖ONES的Capability，并 SHALL 在相关请求中返回安全自助绑定提示。

#### Scenario: 用户可访问应用但未绑定 ONES
- **WHEN** 启用用户命中活动应用且应用允许ONES Capability，但用户没有有效个人凭据
- **THEN** Job或对话可继续处理不依赖ONES的能力，ONES Tool不进入可用目录，并向用户说明需要绑定ONES

#### Scenario: 应用没有配置 ONES Capability
- **WHEN** 用户已绑定ONES但Application Allowlist不包含搜索能力
- **THEN** 系统不得暴露该Capability，也不得因用户已绑定而扩大应用权限

### Requirement: Agent 入口按企业和钉钉用户解析身份
钉钉 Agent 入口 MUST 使用规范化事件中的钉钉企业内部 ID 和 `senderStaffId` 查找当前身份，并 MUST 同时确认企业、身份和内部用户均处于可用状态；Connector ID 不得作为身份唯一键或人员归属条件。

#### Scenario: 同一用户从第二个应用访问
- **WHEN** 启用用户通过同企业另一个绑定活动应用发布的连接发送消息
- **THEN** 系统解析到同一人员，并继续按该连接命中的 Application Publication 计算访问

#### Scenario: 身份启用但企业停用
- **WHEN** 消息对应身份和人员启用，但所属企业已停用
- **THEN** 系统拒绝创建 Agent Job，不允许身份状态绕过企业治理

#### Scenario: 企业和 Staff ID 不匹配任何身份
- **WHEN** 受信消息无法解析到当前启用身份
- **THEN** 系统进入未绑定候选或恢复候选流程，返回安全提示且不创建 Agent Job

### Requirement: 应用观察不授予 Application Access
系统 MUST 根据消息实际命中的连接、活动 Application Publication 和当前启用用户计算 DingTalk Application Access；应用观察记录只能说明历史来源，不得扩大或恢复应用访问。

#### Scenario: 身份曾通过应用 A 被观察但消息命中应用 B
- **WHEN** 当前消息来自应用 B 且应用 B 没有绑定活动 Application Publication
- **THEN** 系统不得因为存在应用 A 的观察记录而路由到应用 A 或授予访问

#### Scenario: 消息命中已发布应用
- **WHEN** 当前连接绑定活动 Application Publication 且实际发送人解析为启用用户
- **THEN** 系统授予该应用访问并继续计算 Agent 能力上限、应用能力子集和用户 Capability 可用状态

### Requirement: 正式身份观察与昵称先于 Job 创建
对已解析身份的消息，Agent 入口 MUST 在创建 Job 前幂等写入身份最近使用、应用观察以及符合事件游标的昵称和昵称审计，并 MUST 在写入后再次使用当前企业、身份和用户状态计算访问。

#### Scenario: 新昵称消息创建 Job
- **WHEN** 业务消息携带晚于当前游标的非空昵称且所有治理条件满足
- **THEN** 系统在同一处理链中先保存昵称和观察，再创建并分发 Agent Job

#### Scenario: 昵称更新后身份被并发停用
- **WHEN** 身份事实写入完成后、Job 创建前身份被管理员停用
- **THEN** 最终状态复核拒绝 Job，不以先前解析结果继续

#### Scenario: 身份事实写入失败
- **WHEN** 最近使用、观察或应写昵称审计无法持久化
- **THEN** 系统不创建 Job，并通过现有安全失败投递路径返回可理解结果

### Requirement: 群聊继续按实际发送人隔离身份
群聊中的企业、身份、应用访问和 ONES Capability 可用性 MUST 按每条消息的实际 `senderStaffId` 独立计算；同群成员、机器人应用或历史观察记录不得共享身份与个人凭据。

#### Scenario: 同一群两个用户先后提问
- **WHEN** 两个钉钉用户在同一群通过同一应用发送消息
- **THEN** 系统分别解析各自企业身份和内部用户，分别计算 ONES 绑定、默认 Team 和个人凭据

#### Scenario: 群中一个用户未绑定
- **WHEN** 已绑定用户和未绑定用户处于同群，而未绑定用户发送消息
- **THEN** 系统只为实际发送人形成候选并拒绝 Job，不复用已绑定群成员身份

<!-- Reconciled from mcp_new capability: `dingtalk-stream-ingress` -->

### Requirement: DingTalk Stream ingress connects with configured enterprise app credentials
系统 SHALL 由单个 `dingtalk-runtime` 使用控制面中所有已启用且配置完整的钉钉企业 App Connector，为每个 Connector 建立独立 DingTalk Stream Client。

#### Scenario: 多个 Stream Connector 启动成功
- **WHEN** Runtime 取得活动租约且控制面返回多个已启用的有效 Connector
- **THEN** 系统分别建立 Stream 连接、在注册完成后上报 READY，并开始接收各 Connector 的消息事件

#### Scenario: 单个 Stream Connector 缺少凭据
- **WHEN** 一个已启用 Connector 缺少有效 Client ID 或 Client Secret
- **THEN** 系统只将该 Connector 标记为配置或认证失败，不影响其他 Connector，且不创建其 Channel 事件

#### Scenario: 动态启用 Stream Connector
- **WHEN** 管理员在 Runtime 运行期间启用一个配置完整的钉钉 Connector
- **THEN** Runtime 在协调周期内建立新连接，不要求修改或重启 Compose

### Requirement: DingTalk Stream messages are normalized as Channel events
系统 SHALL 将 DingTalk Stream 用户消息事件归一化为包含 `from`、`delivery`、`routing`、`message`、`external_event_id` 和 connector metadata 的内部 Channel event。

#### Scenario: User message is received from Stream
- **WHEN** DingTalk Stream 推送一条受支持的用户文本消息
- **THEN** 系统生成 Channel event，并保留钉钉会话 ID、用户 ID、消息 ID、原始文本、connector ID 和默认 delivery 配置

#### Scenario: Unsupported Stream event is received
- **WHEN** DingTalk Stream 推送不受支持的事件类型或消息类型
- **THEN** 系统忽略该事件、记录 ignored 审计事件，且不创建 Agent job 或 RabbitMQ 消息

### Requirement: DingTalk Stream ingress works without public HTTP callback
系统 SHALL 允许本地或内网部署通过 DingTalk Stream 接收钉钉用户消息，不要求配置公网 HTTPS HTTP webhook 回调地址。

#### Scenario: Local Stream worker receives a message
- **WHEN** 开发者在本地启动 Stream ingress worker 且企业 App 已允许 Stream 事件
- **THEN** 系统可以接收钉钉用户消息并创建 Agent job，而无需暴露 `/webhooks/dingding/agent` 到公网

### Requirement: DingTalk Stream acknowledgement follows durable ingress persistence
系统 SHALL 在 Connector 级幂等判断、标准化 Channel 事件和 Inbox/Outbox 事务持久化成功后向 DingTalk Stream 确认；不得等待 Agent 执行完成。

#### Scenario: Stream message is durably accepted
- **WHEN** DingTalk Stream 用户消息通过基础校验并成功写入 Channel Inbox/Outbox
- **THEN** Runtime 向 DingTalk 返回成功确认，并记录关联的 channel event ID

#### Scenario: Duplicate Stream message is received
- **WHEN** 相同 Connector 重复投递相同 external event ID
- **THEN** 系统返回已有事件的成功确认，不写入第二条 Inbox 或 Outbox

#### Scenario: Durable persistence fails
- **WHEN** Inbox/Outbox 事务失败或内部接入 API不可用
- **THEN** Runtime 不返回成功持久化确认，记录安全错误并允许钉钉按协议重试

### Requirement: DingTalk Stream ingress handles reconnects safely
系统 SHALL 为每个 Stream Connector 独立执行有界退避重连，并确保一个 Connector 的断线、认证失败或 revision 变化不影响其他 Connector。

#### Scenario: 单个 Stream 连接断开
- **WHEN** Connector A 的 Stream 连接断开而 Connector B 保持健康
- **THEN** Runtime 只将 A 标记为 RECONNECTING 并执行退避，B 保持 READY

#### Scenario: Event is redelivered after reconnect
- **WHEN** 同一个 Connector 的相同事件在重连后再次送达
- **THEN** 系统使用 Connector 和 external event ID 组成的稳定幂等键返回已有事件，不创建重复 Channel 事件或 Job

#### Scenario: Connector revision changes during reconnect
- **WHEN** Connector 正在自动重连且控制面提供了更高 revision
- **THEN** Runtime 串行终止旧重连状态并以新 revision 重建一个 Client

### Requirement: DingTalk Stream Connector 状态可被管理端观测
系统 SHALL 为每个钉钉 Stream Connector 提供期望状态、有效观测状态、加载 revision、注册状态、心跳、最近消息和安全错误摘要。

#### Scenario: Connector 正常可用
- **WHEN** Runtime 正在续约且 SDK 已注册
- **THEN** 管理端显示 READY、当前 loaded revision、最近心跳和最近消息时间

#### Scenario: Runtime 失联
- **WHEN** Runtime 心跳过期
- **THEN** 管理端显示 STALE，而不是沿用上一次 READY

### Requirement: DingTalk webhook robot remains delivery-only
系统 SHALL 将钉钉 webhook 群机器人作为结果出口能力处理，不得将其作为钉钉用户消息入口。

#### Scenario: Webhook robot connector is configured
- **WHEN** connector 配置类型为钉钉 webhook 群机器人
- **THEN** 系统只允许该 connector 用于 delivery，不启动 Stream ingress 或 HTTP ingress

### Requirement: 钉钉Stream私聊使用机器人身份路由应用
系统 MUST 为钉钉 Stream 私聊从受信 payload 或 Connector 配置解析稳定 bot identity，并 SHALL 生成 `bot:<normalized_bot_identity>` 作为应用 routing key。

#### Scenario: 私聊payload包含robotCode
- **WHEN** Stream 私聊事件包含受信 `robotCode`
- **THEN** 适配器将其规范化为 bot identity 并生成私聊 routing key
- **AND** 同一机器人收到的不同用户私聊使用同一应用 route

#### Scenario: payload缺少robotCode但Connector已配置
- **WHEN** 私聊事件没有可用 robotCode 且来源 Connector 配置了固定 bot identity
- **THEN** 适配器使用 Connector bot identity 生成 routing key

#### Scenario: 无法取得受信bot identity
- **WHEN** payload 和 Connector 都不能提供 bot identity
- **THEN** 事件不得使用发送人、会话名或消息内容猜测 routing key
- **AND** 系统记录未解析原因并按无匹配兼容规则处理

### Requirement: 钉钉Stream群聊使用会话身份路由应用
系统 MUST 为钉钉 Stream 群聊生成 `conversation:<normalized_conversation_id>` routing key，并 MUST 使用当前消息发送人的统一身份执行 RBAC。

#### Scenario: 群聊中机器人被提及
- **WHEN** 合法群聊消息满足现有提及规则并包含 conversation ID
- **THEN** 适配器按 connector 与 conversation routing key 解析应用
- **AND** Agent/API 权限仍按当前发送人而不是整个群计算

#### Scenario: 两个群使用同一机器人
- **WHEN** 两个群具有不同 conversation ID 且使用同一 Stream Connector
- **THEN** 系统允许它们分别绑定到不同业务应用

### Requirement: 业务应用路由不改变Stream快速确认和幂等语义
系统 SHALL 在现有 Stream ACK 时限内完成接收确认，并 MUST 保持基于来源 connector 与外部事件 ID 的幂等边界；应用路由与版本切换不得为同一事件创建第二个 Job。

#### Scenario: 同一消息重复投递
- **WHEN** 钉钉重复投递相同外部事件 ID
- **THEN** 系统至多创建一个 Agent Job
- **AND** 重复事件不会因为应用 Publication 已切换而创建新版本 Job

#### Scenario: 路由解析耗时或失败
- **WHEN** 应用路由解析未能在 Stream 回调处理窗口完成或返回配置错误
- **THEN** 适配器遵循现有快速 ACK 与异步处理契约
- **AND** 记录可定位的接收、路由和通知状态

### Requirement: 钉钉Stream应用错误回复原会话
系统 SHALL 对已命中应用后的安全配置错误使用当前事件的有效 session webhook 向原私聊或群聊发送失败说明，并 MUST 遮蔽内部异常、hash、凭据和堆栈。

#### Scenario: 命中应用但Delivery配置无效
- **WHEN** 钉钉消息命中应用但 reply-original Delivery 校验失败
- **THEN** 用户收到简短的“应用配置暂不可用”或等效错误
- **AND** 审计保存稳定 reason code 供管理员排查

### Requirement: Stream 消息携带并校验企业上下文
系统 MUST 从受信钉钉 Stream 消息提取应用连接、`senderCorpId`、`chatbotCorpId`、`senderStaffId`、`senderNick`、事件时间和稳定事件 ID，并在进入身份解析前校验连接所属企业；企业字段不得由客户端管理请求或消息正文覆盖。

#### Scenario: 已验证企业收到正常消息
- **WHEN** 启用连接收到 SDK 认证消息，且两个 Corp ID 与所属 `ACTIVE` 企业一致
- **THEN** 系统将企业内部 ID 和受信身份字段写入规范化 Channel Event，继续身份解析

#### Scenario: 消息缺少 Staff ID
- **WHEN** 受信事件缺少可用 `senderStaffId`
- **THEN** 系统拒绝身份解析且不创建候选、身份、观察或 Agent Job

### Requirement: 待验证企业消息只能形成验证证据
所属企业为 `PENDING_VERIFICATION` 时，Stream worker MUST 将满足条件的受信测试消息交给企业验证流程，并 MUST 阻止其进入普通 Channel Dispatch、身份发现、Application Access 和 Agent Job 流程。

#### Scenario: 待验证消息完成 Corp ID 验证
- **WHEN** 同一受信测试消息包含非空且相等的 `senderCorpId` 与 `chatbotCorpId`
- **THEN** 系统固化企业 Corp ID 并确认消息，不创建 Channel Outbox、身份候选或 Agent Job

#### Scenario: 待验证消息包含业务问题
- **WHEN** 测试消息正文同时看起来像普通 Agent 请求
- **THEN** 系统仍只执行企业验证，不调用模型或 API Capability，并提示管理员验证成功后重新发送业务消息

### Requirement: Corp ID 不一致时失败关闭并治理告警
已验证企业的任何应用连接收到缺失或不匹配的 Corp ID 时，系统 MUST 拒绝该消息、阻止身份与 Job 写入并产生安全治理告警；系统不得自动修改企业或连接归属。

#### Scenario: 后续应用实际属于另一企业
- **WHEN** 新应用连接收到的受信消息 Corp ID 与所选企业不同
- **THEN** 系统拒绝消息并把连接标记为企业校验错误，告警不包含消息正文或认证材料

#### Scenario: 重连后收到不匹配消息
- **WHEN** Stream 重连成功后第一条消息的 Corp ID 与企业不一致
- **THEN** 重连状态不得绕过企业校验，系统仍拒绝分发

### Requirement: 非活动企业不处理业务 Stream 消息
所属企业为 `DISABLED` 或 `ARCHIVED` 时，系统 MUST 停止或拒绝其全部应用连接的业务入口；已有连接心跳或 SDK 回调不得使企业自动恢复。

#### Scenario: 企业停用时仍收到 SDK 回调
- **WHEN** 停用动作与在途 Stream 消息并发
- **THEN** 消息在持久化 Job 前重新校验企业状态并失败关闭

#### Scenario: 只重新启动 Runtime
- **WHEN** 管理员重启已停用或归档企业的连接 Runtime
- **THEN** 系统不恢复业务处理，必须完成显式企业恢复和 Corp ID 复验

### Requirement: 企业校验参与 Stream 幂等确认
Stream 重试和重连 MUST 使用稳定事件 ID 保持企业验证与业务分发幂等；同一事件不得既被用作企业验证又在重试时创建业务 Job。

#### Scenario: 企业验证事件被重投
- **WHEN** 完成企业验证的测试事件再次到达
- **THEN** 系统返回已有验证确认且不进入业务分发

#### Scenario: 正常业务事件被重投
- **WHEN** `ACTIVE` 企业的同一业务事件重复到达
- **THEN** 系统复用现有 Channel Event 或 Job 结果，不重复更新昵称审计、观察记录或创建 Job

<!-- Reconciled from mcp_new capability: `multimodal-message-storage` -->

### Requirement: 系统分层保存MVP多模态消息
系统 SHALL 在PostgreSQL保存消息正文、附件元数据、来源状态、可读性状态、精确File/Version绑定及处理/表示血缘，并在File Service管理的私有S3兼容对象存储保存原始二进制和派生表示。完整原始二进制、Markdown、Docling JSON、对象位置和凭据 MUST NOT写入PostgreSQL、RabbitMQ、日志或审计payload；旧Publication兼容路径中既有有界提取文本只可用于历史读取，不得成为启用文档处理Profile后的新事实源。
#### Scenario: 文本和文档一起到达
- **WHEN** 消息包含文本和一个受支持文档且命中启用文档处理Profile的应用
- **THEN** 系统保存一条user message、一条attachment记录、原始File Version和processing run
- **AND** 原件与后续派生表示均只能由File Service写入私有bucket
#### Scenario: 仅图片到达
- **WHEN** 消息没有文本但包含受支持图片且应用启用文档处理Profile
- **THEN** 系统保存消息、图片原件和OCR处理状态
- **AND** 不把OCR能力描述为完整图片内容理解

### Requirement: MVP只接受现代白名单格式
系统 SHALL 按代码固定`text-v2`支持UTF-8 TXT、LOG和Markdown，并仅在Publication冻结`docling-layout-ocr-v2`时支持PDF、DOCX、XLSX、PPTX、JPEG、PNG和WebP原件；系统 MUST 根据真实内容探测MIME、校验格式、数量、文件大小、解压后大小及结构上限。渠道提供文件名时，系统 MUST 保留其安全规范化后的 basename 作为用户可见名称基础；原生图片消息不提供文件名时，系统 MUST 按消息时间和固定 `Asia/Shanghai` 时区生成可读名称，不得伪造原名。对成功安全解码、像素校验并重新编码的JPEG、PNG和WebP，系统 MUST 以规范化后的真实媒体类型与文件签名确定源格式，并使用真实格式的canonical extension创建受治理文件名，同时保留安全规范化后的来源名称作为来源元数据；该兼容行为不得用于PDF、Office或其他格式。同一工作区的同名文件 MUST 使用 ` (2)`、` (3)` 递增后缀消歧，不得暴露内部 attachment ID。源文档单文件 MUST 不超过25MiB；Agent可读文本仍 MUST 不超过15MiB。系统 MUST 拒绝DOC、XLS、PPT、宏文件及其他未支持格式。
#### Scenario: 渠道提供可用原始文件名
- **WHEN** 渠道附件提供可安全规范化的原始文件名
- **THEN** 任务工作区保留其安全basename和经真实内容校正的canonical extension
- **AND** 同名时使用 ` (2)`、` (3)` 递增后缀，不展示不透明内部标识
#### Scenario: DingTalk原生图片没有原始文件名
- **WHEN** 原生picture消息只提供`downloadCode`和消息时间
- **THEN** 系统生成 `图片-YYYYMMDD-HHMMSS.<canonical extension>` 作为用户可见文件名
- **AND** 时间按`Asia/Shanghai`解释，扩展名由实际文件签名决定
#### Scenario: 现代Office附件通过受治理校验
- **WHEN** DOCX、XLSX或PPTX的扩展名、MIME、大小和结构符合固定源文件策略且应用启用文档处理Profile
- **THEN** File Worker通过File Service保存原件并创建异步processing run
- **AND** 不使用旧正文数据库写入作为该附件的新内容事实
#### Scenario: UTF-8 TXT进入任务工作区
- **WHEN** `.txt`内容为有效UTF-8且大小不超过15MiB
- **THEN** 系统允许File Worker通过File Service导入并进入现有文本工作区链路
- **AND** 不为TXT调用Docling
#### Scenario: TXT编码或大小不合法
- **WHEN** `.txt`是GBK、UTF-16、无效UTF-8或超过15MiB
- **THEN** 系统将attachment标记为REJECTED并保存安全错误码
- **AND** 对已建立受治理回复路由的纯附件暂存事件，系统按attachment身份幂等投递安全通知，说明该文件未进入工作区、展示安全文件名与安全原因并要求修正后重新发送
#### Scenario: 类型伪装或超限
- **WHEN** PDF或Office扩展名与真实MIME/结构冲突，图片无法安全解码为白名单格式，或附件数量、大小、页数、解压后大小、行列、像素或幻灯片超过对应固定策略
- **THEN** 系统将attachment或processing run标记为确定拒绝
- **AND** 不调用模型、不静默截断或降级到宽松解析器
#### Scenario: 渠道把JPEG或WebP命名为PNG
- **WHEN** 渠道附件名以`.png`结尾，但图片字节可安全解码并规范化为JPEG或WebP且满足全部资源上限
- **THEN** File Service按规范化后的真实媒体类型和签名保存原件，并把受治理display name改为`.jpg`或`.webp`
- **AND** 原始渠道名称只作为来源元数据保留，不因错误扩展名拒绝合法图片或覆盖同名文件
#### Scenario: 旧版Office或其他格式到达
- **WHEN** 消息包含DOC、XLS、PPT、宏文件、压缩包、音视频、SVG、脚本、可执行文件或未知格式
- **THEN** 系统不解析内容并返回不泄漏内部信息的格式说明
#### Scenario: PDF进入未启用Profile的应用
- **WHEN** 应用Publication未选择文档处理Profile而消息包含PDF
- **THEN** 系统不创建processing run并返回当前应用未启用文档读取能力的安全状态
#### Scenario: 现代Office附件通过现有兼容校验
- **WHEN** DOCX、XLSX或PPTX的扩展名、MIME、大小和结构符合现有附件策略
- **THEN** 系统保存对象并进入现有受限文本提取
- **AND** 该文件不进入直接文本任务工作区编辑能力
#### Scenario: text-v2文本进入任务工作区
- **WHEN** `.txt`、`.log`或`.md`内容为有效UTF-8、无NUL且大小不超过15 MiB
- **THEN** 系统按冻结策略和format操作矩阵允许File Worker通过File Service导入
- **AND** `.log`只获得读取与既有精确版本交付能力
#### Scenario: 上游以通用MIME声明LOG
- **WHEN** 文件名为`.log`、声明MIME为`application/octet-stream`且真实内容通过严格UTF-8文本验证
- **THEN** `text-v2`可以把它规范化为`LOG`
- **AND** 任何NUL、二进制或编码失败仍必须拒绝
#### Scenario: Markdown声明允许的文本MIME
- **WHEN** 文件名为`.md`、声明MIME为`text/markdown`或`text/plain`且真实内容为合法UTF-8
- **THEN** `text-v2`可以把它规范化为`MARKDOWN`
- **AND** File Worker不渲染HTML、执行链接或抓取远程资源
#### Scenario: 文本编码或大小不合法
- **WHEN** `.txt`、`.log`或`.md`是GBK、UTF-16、无效UTF-8、包含NUL、二进制内容或超过15 MiB
- **THEN** 系统将attachment标记为REJECTED并保存安全错误码

### Requirement: 下载和对象写入幂等且短期凭证受保护
系统 SHALL 使用内部attachment ID驱动下载和存储并以SHA-256校验完整性。download code或等价来源凭证只允许使用平台主密钥短期加密落库，MUST NOT保存明文或将明文/密文暴露到队列、日志、审计、API和调试输出，并 MUST 在下载完成、拒绝、失败或过期后清除。session webhook、access token和对象存储凭证 MUST NOT作为attachment来源凭证持久化。

#### Scenario: 外部事件被重投
- **WHEN** 钉钉重复投递包含同一附件的事件
- **THEN** 系统复用已有message、attachment和对象且不重复创建job

#### Scenario: 对象写入后任务重试
- **WHEN** 下载任务在对象完整写入后发生确认超时
- **THEN** 重试校验已有对象散列并继续状态机，不产生第二份对象

#### Scenario: 下载凭证到达终态
- **WHEN** attachment下载完成、被拒绝、最终失败或来源凭证过期
- **THEN** 系统清除加密来源凭证且后续读取只能获得凭证已清除状态

### Requirement: 文档在受限worker中提取
系统 SHALL 由非root、禁外网、受CPU、内存、临时空间和时间限制的`file-processing-worker`与内部`docling-serve`处理PDF、DOCX、XLSX、PPTX及图片文字；File Worker只负责来源下载、前置校验和通过File Service导入原件。TXT、LOG和Markdown继续执行现有有界文本校验而不调用Docling。处理组件 MUST NOT执行公式、宏、嵌入对象或远程资源，也不得启用VLM、图片语义描述、自定义模型或插件。
#### Scenario: 受支持文档提取成功
- **WHEN** 受支持PDF或现代Office文档在Profile资源上限内完成处理
- **THEN** 系统通过File Service保存Markdown和Docling JSON不可变表示并标记可读性为AVAILABLE
- **AND** 不把完整提取正文写入`attachment_content`或直接注入模型
#### Scenario: TXT校验成功
- **WHEN** 任务工作区文本附件通过大小、MIME和UTF-8校验
- **THEN** File Worker通过File Service保存原始内容并标记可用于精确版本物化
- **AND** 不声称调用了Docling或其它文档解析器
#### Scenario: 加密、宏格式或损坏文档
- **WHEN** 文档加密、属于宏格式、包含禁止结构、损坏或触发资源限制
- **THEN** 系统停止处理并把可读性标记为UNAVAILABLE
- **AND** 保存安全错误码且不向Agent暴露正文或原始异常
#### Scenario: Docling暂时不可用
- **WHEN** 原件已安全导入但Docling或processing worker暂时不可用
- **THEN** processing run进入有限重试且不回退到旧提取器、直接正文注入或假成功
- **AND** 需要可读正文的本轮由能力门禁给出系统说明，不把无关 Agent Job保持为等待 Docling
#### Scenario: 现有文档提取成功
- **WHEN** 受支持Office或旧兼容Markdown文档在资源上限内完成现有解析
- **THEN** 系统保存有界纯文本、分段信息、解析器版本和截断状态并标记READY
#### Scenario: 任务工作区文本校验成功
- **WHEN** `text-v2`任务工作区`.txt/.log/.md`通过策略、大小和UTF-8校验
- **THEN** File Worker通过File Service保存原始内容并标记可用于精确版本物化
- **AND** 不声称调用Docling、渲染Markdown或执行其它文档解析器
#### Scenario: 加密、主动内容或损坏文档
- **WHEN** 文档加密、属于宏格式、包含禁止结构、损坏或触发资源限制
- **THEN** 系统停止处理并标记REJECTED或FAILED，不向Agent暴露内容

### Requirement: 图片只安全存储而不宣称可理解
系统 SHALL 对JPEG、PNG和WebP执行真实格式、文件大小和像素限制校验，去除不需要的元数据后通过File Service保存原件；仅当应用Publication冻结`docling-layout-ocr-v2`时，系统 SHALL 允许Docling对图片执行OCR文字提取。系统 MUST NOT把OCR结果等同于架构图、流程图、仪表盘、照片或其它视觉语义理解，也不得调用VLM或生成虚构描述。
#### Scenario: 图片OCR产生文字
- **WHEN** 图片通过校验、应用启用Profile且OCR生成非空Markdown
- **THEN** 系统保存只读Markdown和Docling JSON表示并把可读性标记为AVAILABLE或PARTIAL
- **AND** Agent只可把其中的文字作为不可信数据读取
#### Scenario: 文本加无文字图片消息执行
- **WHEN** 消息包含可用用户文本且图片OCR结果为NO_TEXT
- **THEN** Agent使用用户文本执行并收到固定的图片未提取到文字notice
- **AND** 不声称已经理解图片
#### Scenario: 仅图片且没有文字
- **WHEN** 消息只有图片且OCR为NO_TEXT或UNAVAILABLE
- **THEN** 系统不调用模型并通过原reply route说明未获得可阅读文字
#### Scenario: 应用未启用文档处理
- **WHEN** 图片通过安全存储校验但应用Publication的Profile为NONE
- **THEN** 系统保持不解释图片内容的安全状态
- **AND** 不因平台部署了Docling而自动扩大该应用能力
#### Scenario: File Service拒绝图片原件导入
- **WHEN** File Service以稳定安全错误码拒绝图片导入
- **THEN** File Worker把该机器码保存到`message_attachment.failure_code`并将附件置为确定终态
- **AND** 不以本地化提示文字替代机器码，不记录File Service原始响应、文件字节或内部异常

### Requirement: Agent job等待附件达到终态
系统 SHALL 让本轮已绑定附件的Job等待来源下载/导入达到终态；`WAITING_INPUT` MUST NOT 用于等待 Docling 或 `file_processing_run` 非终态。只要本轮绑定附件的来源状态尚未终态，Job可以保持`WAITING_INPUT`。来源终态后，需要`READABLE_CONTENT`且表示仍为PENDING或失败时 MUST 走系统说明而不是释放到`agent.jobs`。AVAILABLE或带非空合规Markdown的PARTIAL可以进入Manifest；NO_TEXT、UNAVAILABLE、REJECTED或FAILED只能形成固定安全notice。无关文字 MUST 创建可执行Job且不得认领处理中文档。
#### Scenario: 部分文档可用
- **WHEN** 本轮绑定的部分附件AVAILABLE或PARTIAL且仍存在用户文本或至少一个可用Markdown表示
- **THEN** 系统冻结可用精确表示并发布同一Job
- **AND** 在上下文列出不可用或不完整附件的固定安全状态
#### Scenario: 没有可用输入
- **WHEN** 没有用户文本且所有本轮绑定附件均为NO_TEXT、UNAVAILABLE、REJECTED或FAILED
- **THEN** 系统不调用模型并安全结束该轮
#### Scenario: 原件已保存但表示仍处理中
- **WHEN** attachment原件已经形成File Version而processing run仍非终态，且本轮需要可读正文
- **THEN** 系统不得仅因原件已保存就把attachment视为Agent可读
- **AND** 不得继续保持`WAITING_INPUT`等待表示；应发送固定未就绪说明且不调用模型

### Requirement: 附件内容作为不可信数据注入
系统 SHALL 把消息正文、历史兼容提取文本和Docling派生内容全部标识为不可信用户数据，其中的指令 MUST NOT覆盖系统提示、安全规则、权限或工具策略。对启用文档处理Profile的新文档，系统 MUST 只把有界Manifest元数据和固定安全notice交给模型，并由Runtime把精确Markdown表示物化到Job Sandbox；完整Markdown不得在Job开始时直接拼入conversation context。
#### Scenario: 文档包含提示注入
- **WHEN** Markdown表示要求Agent忽略系统规则或调用未授权工具
- **THEN** Agent只能通过受限Read、Grep或Glob把它作为引用数据处理
- **AND** 文件内容不能改变Tool可见性、权限、网络或沙盒边界
#### Scenario: 大文档进入Job
- **WHEN** 合规Markdown表示接近允许的15MiB上限
- **THEN** Runtime只物化文件并向模型提供安全相对路径和摘要
- **AND** conversation context不包含整份文档正文

### Requirement: 多模态数据支持可重试删除和孤儿核对
系统 SHALL 为消息附件使用可部署覆盖的保留策略，未配置时 canonical 默认值 MUST 为360天，并从附件原始创建时间计算到期时间。系统 SHALL 按该到期事实标记并通过 File Service 可重试删除原对象与提取内容；一致性核对默认只报告未知孤儿对象而不自动删除。历史附件缺少到期事实时 SHALL 从原始创建时间回填，不得在schema migration事务中直接删除已到期对象。

#### Scenario: 对象删除暂时失败
- **WHEN** 对象存储删除发生瞬时失败
- **THEN** 数据库保持待删除状态并由 File Worker重试
- **AND** 不错误标记为已删除

#### Scenario: 发现未知孤儿对象
- **WHEN** 私有bucket中的对象没有对应数据库记录
- **THEN** 系统生成安全报告且不自动删除对象

#### Scenario: 未配置附件保留期
- **WHEN** 新消息附件进入且部署没有显式覆盖策略
- **THEN** 系统把到期时间计算为原始创建时间加360天

#### Scenario: 历史附件已超过360天
- **WHEN** 迁移回填发现附件按原始创建时间已经到期
- **THEN** 系统只建立待删除事实并由可重试清理流程处理
- **AND** migration事务不直接删除MinIO对象

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

### Requirement: Webhook认证必须使用强Bearer并失败关闭
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

### Requirement: 第三方 payload 通过声明式配置归一化
系统 SHALL 使用 Trigger publication 中的 typed adapter、JSON Pointer、声明式条件和有界模板生成内部 Channel event，MUST 将提取内容标记为不可信外部数据。

#### Scenario: 通用 JSON 映射成功
- **WHEN** payload 满足必填路径、类型、过滤条件和 routing allowlist
- **THEN** 系统生成有界 message、稳定 external event ID、受控 routing 和固定来源/投递引用

#### Scenario: 必填映射字段缺失
- **WHEN** payload 缺少事件 ID、消息或 Trigger 要求的 routing 值
- **THEN** 系统记录映射拒绝状态并且不创建 Agent job

#### Scenario: payload 试图覆盖控制字段
- **WHEN** payload 包含 Agent、工具、服务账号、Connector、secret 或 Delivery endpoint 字段
- **THEN** 系统忽略这些控制字段并只使用 Trigger publication 中的固定值

### Requirement: Grafana 只为 firing 告警创建一个 group 级事件
系统 SHALL 对 `grafana_alertmanager_v1` 只执行 `status=firing`，并 MUST 使用 `groupKey` 或稳定排序后的 fingerprints 表示一个告警组。

#### Scenario: Grafana firing group
- **WHEN** 一个已认证 firing payload 包含 groupKey 和多条 alerts
- **THEN** 系统创建一个 Webhook event 和一个 Agent job，并使用有界告警组摘要作为消息

#### Scenario: Grafana resolved group
- **WHEN** 一个已认证 payload 的状态为 resolved
- **THEN** 系统持久化或审计 `IGNORED` 结果、返回 ignored acknowledgement 且不创建 Agent job

#### Scenario: Grafana 重复发送同一 firing group
- **WHEN** 同一 Trigger 重试相同 groupKey/fingerprint firing 事件
- **THEN** 系统返回已有事件 acknowledgement，不创建第二个 job

### Requirement: 接收成功后通过持久化 Inbox 异步分发
系统 SHALL 在同一 PostgreSQL 事务中保存 Webhook event 和 outbox dispatch 记录，提交成功后 MUST 返回 `202 Accepted`，再异步创建 Agent job。

#### Scenario: Inbox 事务成功
- **WHEN** firing 事件通过认证、过滤、映射、权限预检和幂等校验
- **THEN** 系统保存固定 Trigger/Agent publication 引用并返回 event ID、correlation ID 和 `202 Accepted`

#### Scenario: RabbitMQ 临时不可用
- **WHEN** Inbox 已提交但首次 outbox 发布失败
- **THEN** 系统保留 `DISPATCH_PENDING` 状态并由恢复扫描器重试，不要求来源系统重新生成事件

#### Scenario: Dispatcher 重复收到 event ID
- **WHEN** RabbitMQ 重投递已经关联 job 的 Webhook event
- **THEN** dispatcher 返回幂等成功且不创建或执行第二个 job

### Requirement: Webhook 入口执行限流、并发和冷却策略
系统 SHALL 按 Trigger publication 执行请求速率、在途并发和相同事件冷却限制，并 MUST 在超限时避免创建额外 Agent job。

#### Scenario: 告警风暴超过速率上限
- **WHEN** Trigger 在配置窗口内接收数量超过发布上限
- **THEN** 系统返回限流响应、记录指标和安全摘要且不继续创建事件/job

#### Scenario: 不同 Trigger 同时接收事件
- **WHEN** 一个 Trigger 达到限流而另一个 Trigger 未达到自身限制
- **THEN** 系统只限制前者，不共享或扩大后者权限

### Requirement: 事件历史可审计且不保存原始 payload
系统 SHALL 保存 payload hash、受控提取字段、脱敏有界摘要、认证/过滤结果、Trigger/Agent publication、correlation ID、job ID 和安全错误，MUST NOT 保存或传播完整原始 body。

#### Scenario: 管理员查看成功事件
- **WHEN** 授权管理员打开 Webhook event
- **THEN** 页面展示来源、固定版本、映射摘要、job/tool/delivery 链接和状态，不展示原始 payload 或 secret

#### Scenario: 认证失败事件
- **WHEN** 已知 Trigger 收到无效凭证
- **THEN** 系统只记录 payload hash、大小、远端安全摘要和错误码，不记录正文

#### Scenario: 清理过期事件摘要
- **WHEN** Webhook event 超过配置保留期
- **THEN** 系统清理可删除摘要，同时保留 Agent job、审计和 Delivery 的独立事实记录

<!-- Reconciled from mcp_new capability: `webhook-trigger-management` -->

### Requirement: 管理员可以管理 Webhook Trigger 草稿和发布版本
系统 SHALL 为 Webhook Trigger 保存定义、可编辑草稿 revision、校验结果、不可变 publication、当前 publication 指针和回滚历史，并 MUST 使用 expected revision 防止并发覆盖。

#### Scenario: 管理员保存新的草稿
- **WHEN** 具有 Webhook 编辑权限的管理员提交合法配置和当前 expected revision
- **THEN** 系统创建新的草稿 revision、记录配置 hash 和审计事件，且不改变运行中的 publication

#### Scenario: 两个管理员并发编辑
- **WHEN** 后提交者使用已经过期的 expected revision 保存
- **THEN** 系统返回版本冲突并要求刷新，不覆盖较新的草稿

#### Scenario: 管理员回滚 Trigger
- **WHEN** 具有发布权限的管理员选择历史有效 publication 回滚
- **THEN** 系统原子切换当前 publication 指针并保留全部历史快照

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

### Requirement: 第一版支持 Grafana Alertmanager 和通用 JSON 模板
系统 SHALL 提供 `grafana_alertmanager_v1` 和 `generic_json_v1` 两种 typed Trigger schema，并 MUST 拒绝未知 schema version 或包含脚本执行能力的配置。

#### Scenario: 创建 Grafana Trigger
- **WHEN** 管理员选择 Grafana Alertmanager 模板
- **THEN** 页面提供 status、groupKey、labels、annotations、routing 和 firing-only 的类型化配置

#### Scenario: 创建通用 JSON Trigger
- **WHEN** 管理员选择通用 JSON 模板
- **THEN** 页面允许用受限 JSON Pointer 和声明式条件配置事件 ID、消息字段、过滤和受控 routing

#### Scenario: 配置可执行模板
- **WHEN** 草稿包含 JavaScript、Python、Shell、任意函数调用或未支持模板语法
- **THEN** 系统拒绝保存或校验该执行性配置

### Requirement: 管理端提供无副作用的报文预览
系统 SHALL 允许授权管理员提交有界测试 JSON，并返回认证之外的映射、过滤、routing、消息、幂等键、固定 Agent 和 Delivery 安全预览；预览 MUST NOT 创建 Webhook event、Agent job、工具调用或外部投递。

#### Scenario: 预览 firing 告警
- **WHEN** 管理员对未发布或已发布 revision 提交测试 Grafana firing payload
- **THEN** 系统返回标准化结果和将使用的固定配置摘要，不触发 Agent

#### Scenario: 预览 resolved 告警
- **WHEN** 管理员提交 Grafana resolved payload
- **THEN** 系统返回 `IGNORED` 过滤结果并说明不会创建 job

### Requirement: Web UI 管理 Trigger 和事件历史
系统 SHALL 提供 Webhook 列表、创建/编辑、校验、发布、回滚、public ID 轮换、预览和事件历史页面，并 MUST 根据独立管理 action 控制可见操作。

#### Scenario: 只读管理员查看事件
- **WHEN** 当前管理员只有 Webhook 查看权限
- **THEN** 页面允许查看脱敏配置和事件状态，但隐藏编辑、发布、轮换和 secret 操作

#### Scenario: 第一版选择 Agent
- **WHEN** 管理员编辑 Trigger 的 Agent 绑定
- **THEN** UI 只展示默认诊断 Agent 的有效 publication，后端快照仍保存通用 Agent code 和 publication ID

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

### Requirement: Channel 文件输入绑定任务工作区
Channel ingress SHALL 把没有非空文字的受支持附件消息作为附件暂存事件：解析真实身份和 Business Application Publication，创建或复用当前 Channel Session 与活动任务工作区，持久化并异步导入附件，但 MUST NOT 创建 Agent Job、Job Dispatch、Result Delivery、占位文字指令或用户回复。同一 Session 中连续到达的纯附件消息 SHALL 进入同一任务工作区，各自形成精确文件版本候选。后续非空文字 MUST 只认领本轮确定性绑定命中的附件或版本；系统 MUST NOT 因出现非空文字就原子认领该 Session/工作区下全部 `job_id` 为空的附件。未被本轮绑定的附件 MUST 保持未挂接 Agent Job，其文件版本继续作为工作区候选。消息附件身份与任务工作区引用 MUST 分离，工作区过期不得提前删除仍在独立保留期内的原始附件。
#### Scenario: 连续发送多个纯附件消息
- **WHEN** 已授权用户在同一钉钉会话依次发送三个合法文件且都没有非空文字
- **THEN** 系统创建或复用当前任务工作区并异步导入三个附件
- **AND** 不创建 Agent Job、Job Dispatch、Result Delivery 或用户回复
#### Scenario: 后续文字统一触发
- **WHEN** 用户随后在同一Session发送非空文字指令
- **THEN** 系统只创建一个Agent Job并原子认领此前尚未消费的三个附件
- **AND** Job File Manifest冻结每个可用附件的精确版本、format和允许操作并只回复一次
#### Scenario: 文字先于附件导入完成
- **WHEN** 后续文字到达时一个或多个已暂存附件仍在导入
- **THEN** 系统创建同一个`WAITING_INPUT` Job并绑定完整待处理集合
- **AND** File Worker只在该集合全部进入安全终态后释放该Job一次，不为单个附件创建额外Job
#### Scenario: 已消费附件不会再次自动认领
- **WHEN** 已有文字Job认领并处理暂存附件后，用户再发送无显式文件引用的普通文字
- **THEN** 新Job不再次把这些附件作为本次新上传文件自动物化
- **AND** 文件仍可作为当前工作区的有界候选按需选择
#### Scenario: 工作区先于附件到期
- **WHEN** 任务工作区到期但关联消息附件仍在360天保留期内
- **THEN** 系统删除工作区临时内容并保留消息附件及其消息来源关系
#### Scenario: 连续发送三种纯文本附件
- **WHEN** 已授权用户在同一钉钉会话依次发送合法`.txt`、`.log`和`.md`且都没有非空文字，并命中`text-v2`
- **THEN** 系统创建或复用当前任务工作区并异步导入三个附件
- **AND** 不创建Agent Job、Job Dispatch、Result Delivery或用户回复
#### Scenario: 后续无关文字不认领暂存附件
- **WHEN** 用户随后在同一 Session 发送不含附件、引用、精确文件名或近指代的非空文字
- **THEN** 系统创建一个 Agent Job 且不认领此前暂存附件
- **AND** 三个文件版本仍作为当前工作区的有界候选
#### Scenario: 后续文字显式绑定其中一个附件
- **WHEN** 用户随后发送引用了第二个暂存文件消息的非空文字，或文字包含该文件的精确显示名
- **THEN** 系统只认领被绑定的那一个附件
- **AND** 其余暂存附件继续保持未挂接 Agent Job
#### Scenario: 本轮绑定附件的来源仍在导入
- **WHEN** 本轮绑定的附件来源下载或导入尚未进入安全终态
- **THEN** 系统可为该绑定集合创建同一个 `WAITING_INPUT` Job
- **AND** File Worker 只在该绑定集合的来源状态全部进入安全终态后唤醒一次门禁，不为单个附件创建额外 Agent Job，也不得把未绑定附件并入该集合

### Requirement: Stream 入站冻结同会话文件交付事实
钉钉Stream入站在普通回复使用`sessionWebhook`时，MUST同时从受信回调冻结会话类型、来源Stream Connector、`robotCode`，并按私聊冻结实际`senderStaffId`、按群聊冻结`openConversationId`，供同一Job的精确文件版本交付使用。文件交付不得从模型参数获取这些事实，也不得因为复用来源应用凭据而把Stream Connector开放为通用Delivery Connector。新提交的`.txt/.md`与当前Manifest中获授权的既有`.txt/.log/.md`精确版本都必须使用相同冻结reply route；交付`.log`不得创建或修改文件版本。
#### Scenario: 私聊生成文件
- **WHEN** 私聊 Stream 消息触发的 Job 成功提交一个新 TXT
- **THEN** 文件 Delivery 使用冻结的实际发送人和来源 Stream 应用调用私聊机器人文件消息接口
- **AND** 普通文字最终回复仍使用原 `sessionWebhook`
#### Scenario: 群聊生成文件
- **WHEN** 群聊 Stream 消息触发的 Job 成功提交一个新 TXT
- **THEN** 文件 Delivery 使用冻结的 `openConversationId`、`robotCode` 和来源 Stream 应用调用群机器人文件消息接口
- **AND** 不把文件发送到默认群或其它 Connector
#### Scenario: 私聊生成Markdown文件
- **WHEN** 私聊Stream消息触发的Job成功提交一个新Markdown版本
- **THEN** 文件Delivery使用冻结的实际发送人和来源Stream应用调用私聊机器人文件消息接口
- **AND** 普通文字最终回复仍使用原`sessionWebhook`
#### Scenario: 群聊原样交付LOG
- **WHEN** 群聊Job按用户请求交付Manifest中获授权的既有LOG精确版本
- **THEN** 文件Delivery使用冻结的`openConversationId`、`robotCode`和来源Stream应用调用群机器人文件消息接口
- **AND** 不修改LOG、创建新版本或把文件发送到其它Connector

### Requirement: 群聊工作区使用实际发送人和群会话双边界
钉钉群聊的任务工作区 MUST 使用受信企业、Connector 和规范化 conversation ID 作为共享会话边界，并在每条消息创建 Job 前使用实际 `senderStaffId` 解析内部用户和业务应用访问。群成员可共同编辑同群工作区文件，但系统 MUST NOT 保存群成员清单、复制钉钉逐成员 ACL、共享个人外部凭据或允许跨群文件访问。

#### Scenario: 同群另一成员继续任务
- **WHEN** 同群另一名已绑定且获应用授权的发送人要求修改工作区文件
- **THEN** 系统以该发送人的内部身份创建新 Job并授予同群工作区访问

#### Scenario: 群成员未绑定或无应用权限
- **WHEN** 当前发送人来自同群但没有可用内部身份或业务应用访问
- **THEN** 系统拒绝创建文件 Job并返回安全身份或授权提示
- **AND** 不向其暴露工作区文件名或内容

### Requirement: File Worker 兼容现有附件队列
系统 MUST 用 `file-worker` 替换 `attachment-worker` 服务名，同时继续消费现有附件队列和兼容在途消息。File Worker SHALL 使用短期来源凭证下载附件并通过 File Service 内部流式接口导入，MUST NOT 获得 MinIO 凭据或直接写对象存储；附件下载终态仍须清除来源凭证。尚未被本轮绑定认领的纯附件只进入 `staged` 终态而不释放或创建 Job。已经绑定唯一 `WAITING_INPUT` Job 的**本轮绑定**附件集合在来源导入全部进入安全终态后，File Worker 才唤醒该 Job 一次；唤醒后 MUST 重新执行能力门禁，MUST NOT 仅因可读表示仍为 `PENDING` 而继续保持 `WAITING_INPUT` 或释放到 `agent.jobs`。
#### Scenario: 切换时存在旧附件消息
- **WHEN** 部署切换到 `file-worker` 时原附件队列仍有合法消息
- **THEN** File Worker 使用原幂等 attachment ID继续处理
- **AND** 不产生重复消息、附件、对象或 Job
#### Scenario: 来源导入完成后表示仍在处理
- **WHEN** 本轮 `WAITING_INPUT` Job 绑定的文档原件已保存但 Markdown 表示仍为 `PENDING`，且所需能力为 `READABLE_CONTENT`
- **THEN** 系统发送固定未就绪说明并安全终结该 Job，不发布到 Agent 队列
- **AND** 不把该终结表现为 `agent_runtime_error`

### Requirement: Agent Session 必须使用通用 Channel 身份事实
系统 SHALL 以通用 `source_channel`、Connector ID、外部 conversation ID、内部 requester ID、会话类型、Project、Business Application ID、Application Publication ID 和 execution scope hash 作为 Agent Session 的持久化及复用事实。完成 contract 后，系统 MUST NOT 读取或写入钉钉专用 conversation/user 影子列来补全这些事实。

#### Scenario: 钉钉事件创建新会话
- **WHEN** 一个通过身份和应用路由校验的钉钉事件需要创建 Agent Session
- **THEN** 系统将钉钉来源归一为通用 Channel、Connector、conversation 与 requester 字段
- **AND** 后续上下文读取不依赖钉钉专用影子列

#### Scenario: 通用会话事实缺失
- **WHEN** contract 后的新入站事件无法唯一解析通用 Connector、conversation、requester、应用 Publication 或执行范围
- **THEN** 系统在创建 Session 和 Job 前失败关闭
- **AND** 不得通过旧影子字段或当前可变配置猜测缺失事实

<!-- Integrated from archived change: `2026-08-23-decouple-document-readiness-from-agent-turns/specs/channel-conversation` -->

### Requirement: 每条文字消息按确定性证据绑定文件依赖
系统 MUST 在创建 Agent Job 或给出本轮系统说明之前，为当前非空文字解析本轮依赖的精确 `file_version` 以及所需能力。绑定 MUST 只使用下列硬证据，且按此优先顺序命中即停：当前消息自身附件；钉钉引用/回复目标消息上已持久化的附件；当前任务工作区内规范化后全等（含扩展名）且唯一的 `display_name`；代码注册的近指代词且工作区内最近一次来源导入成功的文件版本唯一。系统 MUST NOT 使用隐式意图分类器、语义相似度或「刚上传过文件」本身作为绑定证据。无硬证据时本轮文件依赖集合 MUST 为空。近指代或多个同名命中无法得到唯一版本时，系统 MUST 发出固定澄清说明且 MUST NOT 创建 Agent Job、MUST NOT 猜测绑定。

本轮所需能力 MUST 属于 `METADATA`、`ORIGINAL` 或 `READABLE_CONTENT`。当前消息带附件且同时有非空问题时默认 `READABLE_CONTENT`，除非文字命中代码注册的元数据或原件模式。问文件名、大小、格式或上传时间只要求 `METADATA`；要求转发或下载原件只要求 `ORIGINAL`；总结、抽取、统计或询问正文要求 `READABLE_CONTENT`。能力拿不准时 MUST 偏向 `READABLE_CONTENT`；绑定对象拿不准时 MUST 偏向不绑定。钉钉 `originalMsgId` MUST 随用户消息持久化，以便解析被引消息上的附件；系统 MUST NOT 只把引用正文拼进 prompt 而不建立文件绑定。

#### Scenario: 本条消息同时上传文档并提问
- **WHEN** 用户在同一条钉钉消息中发送受支持文档和非空问题
- **THEN** 系统把该消息附件的精确版本列入本轮依赖
- **AND** 所需能力为 `READABLE_CONTENT`，除非文字只命中元数据或原件模式

#### Scenario: 用户回复带文件的历史消息
- **WHEN** 用户通过钉钉引用一条已成功导入附件的历史消息并发送非空文字
- **THEN** 系统用持久化的 `originalMsgId` 解析到被引消息附件的精确版本并列入本轮依赖
- **AND** 不把工作区里其它未引用文件自动列入本轮依赖

#### Scenario: 文字出现精确文件名
- **WHEN** 用户文字包含工作区中恰好一份文件的完整显示名（含扩展名）
- **THEN** 系统绑定该文件当前精确版本
- **AND** 子串、无扩展名或工作区内重名 MUST 不自动绑定

#### Scenario: 近指代指向唯一最近活动文件
- **WHEN** 用户文字命中代码注册近指代词，且当前工作区最近一次来源导入成功的文件版本唯一
- **THEN** 系统绑定该版本
- **AND** 不扫描其它会话或其它工作区

#### Scenario: 近指代在多份文件之间歧义
- **WHEN** 用户说「这个表」但工作区存在多份最近导入且无法唯一确定的表格文件
- **THEN** 系统通过原 reply route 发出固定澄清说明
- **AND** 不创建 Agent Job，也不把任一候选标为已消费

#### Scenario: 无硬证据的后续问题
- **WHEN** 用户刚上传过文档，随后发送不含附件、引用、精确文件名或近指代的普通问题
- **THEN** 本轮文件依赖集合为空
- **AND** 系统不得因工作区存在处理中文档而拒绝创建 Agent Job

<!-- Integrated from archived change: `2026-08-23-decouple-document-readiness-from-agent-turns/specs/channel-conversation` -->

### Requirement: 文件能力未就绪时用系统说明结束本轮
当本轮依赖需要某精确版本的 `READABLE_CONTENT`，且该版本可读性为 `PENDING` 或处理失败终态时，系统 MUST 通过原 reply route 发送固定中文 Markdown 说明，MUST NOT 调用模型，MUST NOT 把该轮释放到 `agent.jobs`。说明 MUST 只包含安全文件名和允许的状态短语（正在生成可读内容 / 可读内容生成失败），MUST NOT 包含对象键、Docling task ID、堆栈、内部 run ID 或 `agent_runtime_error` JSON。需要 `METADATA` 或 `ORIGINAL` 且原件已安全入库时，系统 MUST NOT 因 Markdown 表示未就绪而阻挡本轮。纯附件且无非空文字的行为保持既有暂存、不回复。

#### Scenario: 处理中询问文档内容
- **WHEN** 本轮已绑定一份 `readability_status=PENDING` 的文档且所需能力为 `READABLE_CONTENT`
- **THEN** 系统不创建或不释放 Agent Job 到 Agent 队列
- **AND** 用户收到固定说明：该文件正在生成可读内容，其它问题可以继续发送

#### Scenario: 处理失败后询问文档内容
- **WHEN** 本轮已绑定文档且可读性为 `NO_TEXT`、`UNAVAILABLE` 或处理 `FAILED`
- **THEN** 系统不调用模型
- **AND** 用户收到固定失败说明，而不是 Agent 运行时错误 JSON

#### Scenario: 处理中询问文件名
- **WHEN** 本轮绑定文档只需要 `METADATA` 且原件已形成 File Version
- **THEN** 系统创建 Agent Job 并允许回答元数据
- **AND** 不把未就绪 Markdown 自动物化进该 Job

<!-- Integrated from archived change: `2026-08-23-recall-retained-files-by-time-window/specs/channel-conversation` -->

### Requirement: 时段硬证据可召回仍在保留期的历史附件
系统 MUST 在创建 Agent Job 或给出本轮系统说明之前，把代码可解析的时段作为文件绑定硬证据。时段证据 MUST 排在当前消息自身附件、钉钉引用/回复目标附件、规范化后全等且唯一的完整 `display_name` 之后。当文字同时命中时段词与近指代词时，系统 MUST 按时段窗口召回，MUST NOT 用当前活动工作区里最近一份文件顶替窗口内的版本。系统 MUST NOT 使用隐式意图分类器、语义相似度或大模型日期理解作为绑定证据。

时段硬证据 MUST 同时满足：

1. 文字命中代码注册的时段模式；
2. 文字同时命中代码注册的文件指代词（至少覆盖「文件 / 附件 / 图 / 图片 / 文档 / 表 / 材料」及常见扩展名）。

仅有日期或「附近有什么安排」而没有文件指代词时，本轮文件依赖集合 MUST 保持为空，系统 MUST NOT 因出现日期就召回附件。

已注册时段 MUST 至少覆盖：

- 「上周 / 上星期 / 这周 / 本周」：按 Asia/Shanghai **自然周**，周一 `00:00` 含、下周一 `00:00` 不含，与任务工作区 `WEEK` 到期时钟对齐；
- 「上月 / 上个月」：上一个日历月；
- 「今天 / 今日 / 昨天 / 昨日」：上海自然日；
- 可解析的日历日与闭区间，例如 `8月12日`、`8月12号`、`2026年8月12日`、`2026-08-12`、`8月10日到15日`、`8月10日至15日`。缺省年份 MUST 取当前上海年；若该日期尚未到来，MUST 解释为上一年同一日。「附近」MUST NOT 把单日扩成模糊窗口。

过滤字段 MUST 是原始聊天附件的 `source_received_at`，MUST NOT 使用 File Worker 导入完成时间、版本创建时间、工作区加入时间或 Manifest 冻结时间。召回范围 MUST 限制为同一 Channel Session、同一私聊所有者或同一群会话归属边界、聊天附件保留未到期、精确版本记录仍在的附件。系统 MUST NOT 跨 Session、跨群或跨租户召回。

窗口内唯一且所需能力已就绪时，系统 MUST 绑定该精确版本。窗口内多份且所需能力为 `READABLE_CONTENT` 或无法唯一确定时，系统 MUST 发出固定澄清说明且 MUST NOT 创建 Agent Job、MUST NOT 猜测其中一份。窗口内多份且所需能力仅为 `METADATA` 时，系统 MUST 把不超过工作区文件数量上限（20）的命中版本全部列入本轮依赖且不得自动物化正文；超过该上限时 MUST 发出缩小范围的固定说明且 MUST NOT 创建 Agent Job。窗口内零份仍可访问文件时，系统 MUST 发出固定说明且 MUST NOT 创建 Agent Job。

#### Scenario: 自然周「上周的图」召回唯一附件
- **WHEN** 当前上海时间为某周周一之后，用户发送「上周的图什么内容」，且同一 Session 在上一自然周恰好有一份仍在 360 天保留期内的图片附件
- **THEN** 系统绑定该附件当时的精确版本
- **AND** 不把已到期工作区改回 `ACTIVE`，也不把该文件重新 `link` 进当前工作区

#### Scenario: 日历日与日期区间
- **WHEN** 用户发送「8月12日的文件」或「8月10日到15日的附件」且文字含文件指代词
- **THEN** 系统只绑定 `source_received_at` 落在对应上海自然日或闭区间内、仍可访问的精确版本
- **AND** 不把「附近」解释为额外前后缓冲天

#### Scenario: 无文件指代词的日期闲聊不召回
- **WHEN** 用户发送「8月12日附近有什么安排」或「上周怎么样」，文字不含文件指代词、附件、引用、精确文件名或近指代
- **THEN** 本轮文件依赖集合为空
- **AND** 系统不得因出现日期而查询或冻结历史附件

#### Scenario: 时段词优先于当前工作区近指代
- **WHEN** 用户发送「上周这张图」，当前活动工作区另有一份最近上传的图片，上一自然周也有一份仍可访问的图片
- **THEN** 系统按上周窗口绑定历史图片
- **AND** 不得把当前工作区最近图片当作本轮依赖

#### Scenario: 窗口内多份内容问题必须澄清
- **WHEN** 用户询问「上周的文件什么内容」，窗口内有两份以上仍可访问文件
- **THEN** 系统通过原 reply route 发出固定澄清说明，列出有界安全文件名
- **AND** 不创建 Agent Job，也不把任一候选标为已消费

#### Scenario: 窗口内多份只问元数据
- **WHEN** 用户询问「上周发了哪些文件」，窗口内有不超过 20 份仍可访问文件
- **THEN** 系统把这些精确版本列入本轮 `METADATA` 依赖
- **AND** 不得把整窗正文标为自动物化

#### Scenario: 空窗固定说明
- **WHEN** 用户询问「上周的附件」且同一 Session 该自然周没有仍可访问的文件
- **THEN** 系统通过原 reply route 发出固定说明：该时段没有仍可访问的文件
- **AND** 不创建 Agent Job
- **AND** 说明 MUST NOT 写成「没发过文件」或「会话里从来没有文件」

<!-- Integrated from change: `add-governed-dingtalk-mcp-mvp/specs/channel-conversation` -->

### Requirement: 唯一 DingTalk Stream Client 必须同时接收卡片回调
每个已启用 Connector 的现有 `dingtalk-runtime` Stream Client SHALL 在机器人消息 topic 之外注册固定 `/v1.0/card/instances/callback` topic。系统 MUST NOT 为卡片回调启动同 Client ID 的第二个 Stream Client。

#### Scenario: 同一 Connector 收到卡片点击
- **WHEN** 已注册的 Stream Client 收到卡片回调
- **THEN** runtime 在同一 lease 下将有限规范字段交给内部控制 API

### Requirement: 卡片回调 ACK 必须建立在持久状态转换之后
`dingtalk-runtime` SHALL 只在控制面完成幂等校验和 Action Intent 状态事务后 ACK；ACK MAY 更新卡片状态，但 MUST NOT 等待 Agent Job 或 Provider 执行完成。提交失败时不得 ACK，以允许钉钉重投。

#### Scenario: 合法同意被持久接受
- **WHEN** 控制面把意图从待确认原子转为已批准
- **THEN** runtime 返回包含按 key 更新卡片数据的成功 ACK

#### Scenario: 控制面暂时不可用
- **WHEN** runtime 无法持久提交回调
- **THEN** runtime 不 ACK 且日志只记录安全错误分类
