# result-delivery-routing Specification

## Purpose
TBD - created by archiving change add-channel-ingress-and-delivery. Update Purpose after archive.
## Requirements
### Requirement: Agent results are delivered through reply routes
系统 SHALL 在 Agent 结果或安全失败通知持久化的同一事务内创建 Delivery Outbox event，并由独立 Delivery Dispatcher 按 Job 固化的 reply route 执行；Agent runtime 不得直接调用特定平台 client。

#### Scenario: Successful job has DingTalk delivery
- **WHEN** Agent Job 成功且固化 route 为受支持 DingTalk binding
- **THEN** 系统将 Job 标为 SUCCEEDED 并创建 Delivery Outbox，随后由 Dispatcher 发送并记录结果

#### Scenario: Failed job has failure delivery
- **WHEN** Agent Job 最终失败且配置了授权 Delivery binding
- **THEN** 系统创建安全失败通知的 Delivery Outbox，不在 Job 失败事务中调用外部 adapter

### Requirement: Delivery supports explicit none route
系统 SHALL 支持 `delivery.type=none`，用于 Debug API 或只需要查询接口读取结果的任务。

#### Scenario: None delivery route is used
- **WHEN** Agent job 完成且 `reply_route.type` 为 `none`
- **THEN** 系统不调用外部投递 adapter，但记录 delivery skipped 状态供审计和查询

### Requirement: Long reports are delivered in chunks
系统 SHALL 在最终报告超过目标平台单条消息限制时，将报告分片发送并持久化每个分片状态。

#### Scenario: Report exceeds DingTalk chunk limit
- **WHEN** DingTalk delivery 的报告长度超过配置的单片字符限制
- **THEN** 系统按顺序发送多个分片，每片包含 `part x/y` 标识，并记录每个 delivery chunk

#### Scenario: Report fits in one chunk
- **WHEN** 报告长度未超过目标平台单片字符限制
- **THEN** 系统发送一个分片并将 delivery attempt 标记为成功

### Requirement: Delivery failures do not re-execute Agent jobs
系统 SHALL 将 Delivery 状态机与 Agent Job 分离；Delivery 瞬时失败进入有限 RETRY_WAIT，耗尽后进入 DEAD，均不得重新执行 Agent 或把 SUCCEEDED Job 改为 FAILED。

#### Scenario: Delivery adapter returns transient failure
- **WHEN** Agent Job 已 SUCCEEDED 但 adapter 超时或返回瞬时错误
- **THEN** Delivery 进入 RETRY_WAIT，Job 保持 SUCCEEDED

#### Scenario: Duplicate Delivery event after successful result
- **WHEN** 已 SUCCEEDED 的 Delivery event 被重复消费
- **THEN** 幂等状态阻止重复发送已成功 attempt/chunk

#### Scenario: Delivery reaches DEAD
- **WHEN** Delivery 耗尽最大重试次数
- **THEN** Delivery 状态为 DEAD 并可被精确 CLI replay，Job 状态不变

### Requirement: Delivery attempts are auditable
系统 SHALL 持久化每次 delivery attempt 的目标类型、connector、目标安全摘要、状态、错误摘要、开始和结束时间。

#### Scenario: Delivery attempt completes
- **WHEN** 任一 delivery adapter 完成投递
- **THEN** 系统保存 delivery attempt 和 chunk 记录，并关联到 Agent job

#### Scenario: Delivery attempt fails
- **WHEN** 任一 delivery adapter 投递失败
- **THEN** 系统保存安全错误摘要，不记录 token、webhook secret 或敏感目标地址

### Requirement: DingTalk enterprise App delivery sends final reports directly
系统 SHALL 支持 `reply_route.type=dingtalk_enterprise_robot`，通过钉钉企业 App 凭据获取访问令牌并把 Agent 最终报告或安全失败通知直接发送到钉钉目标。

#### Scenario: Enterprise App delivery succeeds
- **WHEN** Agent job 完成且 `reply_route.type` 为 `dingtalk_enterprise_robot`
- **THEN** 系统使用该 route 的 delivery connector 获取 access token、发送钉钉消息，并记录成功的 delivery attempt 和 chunk

#### Scenario: Enterprise App token request fails
- **WHEN** 钉钉企业 App access token 获取失败
- **THEN** 系统将 delivery attempt 标记为失败、保存安全错误摘要，并保持 Agent job 原有执行状态不变

### Requirement: DingTalk webhook robot delivery sends group messages only
系统 SHALL 支持 `reply_route.type=dingtalk_webhook_robot`，按钉钉群机器人 webhook 协议把 Agent 报告发送到群，且该 route MUST NOT 创建 Agent job 或处理用户入口消息。

#### Scenario: Webhook robot delivery succeeds
- **WHEN** Agent job 完成且 `reply_route.type` 为 `dingtalk_webhook_robot`
- **THEN** 系统向 connector 配置的 webhook endpoint 发送群消息，并记录 delivery attempt 和 chunk 状态

#### Scenario: Webhook robot is used as ingress
- **WHEN** 外部请求尝试使用 webhook 群机器人 connector 作为 `from.connector_id`
- **THEN** 系统拒绝该入口请求，不创建 Agent job，也不发布 RabbitMQ 消息

### Requirement: DingTalk delivery chunks preserve ordering
系统 SHALL 对 DingTalk 企业 App 和 webhook 群机器人出口复用统一报告分片逻辑，按顺序发送并持久化每个分片状态。

#### Scenario: DingTalk report exceeds chunk limit
- **WHEN** DingTalk delivery 的报告超过配置的 `DELIVERY_CHUNK_MAX_CHARS`
- **THEN** 系统按顺序发送多个分片，每个分片包含 `part x/y` 标识，并记录每个 chunk 的状态

#### Scenario: One chunk fails
- **WHEN** DingTalk delivery 中任一分片发送失败
- **THEN** 系统记录失败分片和安全错误摘要，delivery attempt 标记为失败，Agent job 不重新执行

### Requirement: 终态失败通知必须安全且幂等
系统 SHALL 对每个 Job 的终态失败通知实施持久化幂等；通知内容 MUST 不包含堆栈、API key、认证 token、完整 provider URL、完整 session webhook、内部原始 payload 或私有推理。

#### Scenario: 同一终态失败被处理两次
- **WHEN** 重复 dead-letter、Worker 重启或恢复操作再次处理已经成功发送失败通知的 Job
- **THEN** 系统检测已完成 delivery attempt，不再次发送相同终态通知

#### Scenario: 安全失败原因被构建
- **WHEN** Claude runtime 因 `claude_inconsistent_result` 最终失败
- **THEN** 用户通知说明模型运行暂时失败并附 Job 追踪标识，不直接输出矛盾的 `error result: success`、CLI stderr 或内部异常堆栈

### Requirement: 受管 Webhook 的结果路由由 Trigger publication 固定
系统 SHALL 使用 Webhook event 固定的 Trigger publication 构造 reply route，MUST NOT 接受外部 payload 提供任意 Delivery type、Connector、endpoint、token 或目标会话。

#### Scenario: Grafana 告警完成诊断
- **WHEN** Webhook Agent job 成功并生成最终报告
- **THEN** ResultDeliveryService 使用 Trigger publication 固定的钉钉 Connector 和安全目标分片投递结果

#### Scenario: payload 包含钉钉 Webhook URL
- **WHEN** 外部 payload 包含自定义 Webhook URL 或 delivery target
- **THEN** 系统不把该值写入 reply route、job 或外部请求

### Requirement: Trigger Delivery 失败不得重新执行 Agent
系统 SHALL 把受管 Webhook 的 Agent 执行状态与 Delivery attempt 分开；投递失败 MUST NOT 将 Webhook event重新分发或重跑 Agent。

#### Scenario: 钉钉临时不可用
- **WHEN** Agent job 已成功但固定钉钉 Delivery 返回临时错误
- **THEN** 系统保留 job 成功状态并按 Delivery 策略重试或标记投递失败，不创建新 job

### Requirement: Webhook 事件页关联 Delivery 证据
系统 SHALL 允许授权管理员从 Webhook event 查看关联 job、Delivery attempt 和 chunk 状态的安全摘要，而不复制完整目标凭证或报告正文。

#### Scenario: 查看分片投递结果
- **WHEN** 长报告被拆分为多个钉钉消息
- **THEN** 事件页展示分片总数、成功/失败状态和安全错误摘要

### Requirement: 业务应用约束钉钉回复原会话投递
系统 MUST 在业务应用路由命中后要求存在唯一、启用且与 ingress source connector 一致的 `reply_original` Delivery Binding，并 SHALL 使用事件生成的受信临时 reply route 完成实际投递。

#### Scenario: 有效回复原会话Binding
- **WHEN** 应用包含唯一 `reply_original` Binding，connector 与钉钉 Stream 来源一致，事件包含有效 session webhook
- **THEN** 系统将受信 reply route 固定到 Job
- **AND** Delivery Worker 将结果回复到原私聊或群聊

#### Scenario: 缺少回复原会话Binding
- **WHEN** 钉钉 Trigger 命中应用但没有启用的 `reply_original` Binding
- **THEN** 运行时将 route 标记为 `blocked/missing_delivery_binding`
- **AND** 不改用全局固定群或其他 Delivery 类型

#### Scenario: Binding connector不一致
- **WHEN** `reply_original` Binding 的 connector ID 与 ingress source connector ID 不同
- **THEN** 激活预检或运行时校验拒绝该配置
- **AND** 不把临时 session webhook 发送给不匹配的 Connector

### Requirement: 应用Delivery Binding不得持久化临时凭据
系统 MUST 将 Business Application Delivery Binding 作为投递授权和策略，不得在草稿、Publication、runtime status 或审计中保存 session webhook、访问 Token 或完整敏感 URL。

#### Scenario: 发布回复原会话配置
- **WHEN** 管理员发布包含 `reply_original` 的应用
- **THEN** Publication 只保存 delivery type、connector ID 和非敏感策略
- **AND** 临时投递目标只从每次受信钉钉事件进入受保护 Job reply route

#### Scenario: 管理端查看Delivery状态
- **WHEN** 管理员查看应用或 Job 的 Delivery 摘要
- **THEN** 页面显示类型、connector、状态和安全目标摘要
- **AND** 不显示可直接调用的 session webhook

### Requirement: 应用投递失败不得改变Agent执行结果
系统 SHALL 延续 Delivery 与 Agent 执行分离的生命周期，MUST 在应用投递失败时记录并重试 Delivery，而不是创建新 Job、切换应用版本或重新执行 Agent。

#### Scenario: Agent成功但钉钉投递暂时失败
- **WHEN** Agent Job 已成功生成结果而 session webhook 投递发生可重试错误
- **THEN** 系统保留 Agent 成功状态并按现有策略重试 Delivery
- **AND** 重试使用原 Job 的应用 Publication 和 reply route

#### Scenario: session webhook已过期
- **WHEN** Delivery 检测到原 session webhook 永久过期
- **THEN** 系统将投递标记为不可重试失败并记录安全原因
- **AND** 不改发到应用未授权的钉钉群或用户

### Requirement: 业务结果投递前重新校验当前应用权限
系统 SHALL 在发送可能包含业务数据的最终结果前，使用 job 持久化的用户、业务应用和路由上下文重新校验当前应用访问权限。权限已撤销、成员已到期、用户已停用或命中高级拒绝时 MUST 阻止业务结果投递。

#### Scenario: 投递前权限仍有效
- **WHEN** Agent job 已生成结果且请求者仍有目标业务应用权限
- **THEN** 系统按原 reply route 投递结果并记录投递前授权成功

#### Scenario: 投递前权限已撤销
- **WHEN** Agent job 已生成结果但请求者的目标业务应用权限已撤销
- **THEN** 系统不得发送业务结果，只向支持的原会话发送“权限已发生变化，本次结果未投递，请联系管理员”的中文安全通知，并记录“执行完成但投递被权限拦截”

#### Scenario: 安全通知也无法投递
- **WHEN** 权限拦截后原 reply route 已不可用
- **THEN** 系统记录安全通知投递失败，不回退到其它未授权目标，也不重新执行 Agent job

### Requirement: Delivery 查询必须展示独立生命周期
管理 API 和 Job 详情 MUST 展示 Delivery event、attempt、chunk、重试次数、下次重试时间、终态和安全错误，不得把“已请求投递”显示为“已送达”。

#### Scenario: Delivery 尚未被 Dispatcher 领取
- **WHEN** Job 已完成但 Delivery Outbox 为 PENDING
- **THEN** 页面显示 Agent 已完成、投递待处理

### Requirement: Delivery replay 必须使用原始持久化意图
授权 CLI replay MUST 复用原 Job 固化的 binding、目标安全摘要和结果 artifact，不允许输入任意目标或消息体。

#### Scenario: 运维尝试改变 DingTalk 目标
- **WHEN** replay 请求提交不同 Connector 或 recipient
- **THEN** 系统必须拒绝并记录审计

