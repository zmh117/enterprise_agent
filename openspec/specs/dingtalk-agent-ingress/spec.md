# dingtalk-agent-ingress Specification

## Purpose
TBD - created by archiving change add-readonly-diagnostic-agent-mvp. Update Purpose after archive.
## Requirements
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

### Requirement: DingTalk robots can be configured for ingress and delivery
The system SHALL support DingTalk enterprise robots and DingTalk webhook robots as configurable connectors that can allow ingress, delivery, or both.

#### Scenario: DingTalk robot is ingress enabled
- **WHEN** a DingTalk robot connector is configured with `allow_ingress=true`
- **THEN** valid messages from that connector can create Agent jobs through the Channel ingress service

#### Scenario: DingTalk robot is delivery enabled
- **WHEN** a DingTalk robot connector is configured with `allow_delivery=true`
- **THEN** Agent results can be delivered through that connector's DingTalk adapter

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

