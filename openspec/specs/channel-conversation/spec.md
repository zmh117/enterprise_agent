# channel-conversation Specification

## Purpose
定义受管 Connector、钉钉 Stream、Webhook、Channel Event、Agent Session、消息和附件入口之间的契约，以及与原会话结果投递、文件投递和确认卡回调的交接。

身份与 RBAC 以 `identity-access` 为准，应用发布和激活路由以 `business-application` 为准；文件依赖、Manifest 和工作区授权见 `task-file-workspace`，格式、OCR 与处理状态见 `document-file-processing`，Job/Delivery 与外部操作确认状态机见 `execution-delivery`，钉钉业务 Tool 的 Provider 合同见 `governed-api-capability`。

## Requirements

### Requirement: Connector 方向由代码类型和配置共同约束
系统 SHALL 持久化 Connector 类型、启停状态、`allow_ingress`、`allow_delivery`、非敏感配置、revision 与受控凭据引用，并在使用时复核。`dingtalk_enterprise_stream`、Grafana 和受管 Webhook 来源只用于 ingress；企业机器人、webhook 群机器人、email、普通 webhook 和 none 等投递类型不得被配置为用户问题入口。代码能表达一种 Connector 不等于该类型已经过生产验收。

#### Scenario: Stream Connector 被用于普通 Delivery
- **WHEN** Job 请求把 `dingtalk_enterprise_stream` 作为通用 Delivery Connector
- **THEN** 系统拒绝该方向；原会话的专用回复和精确文件交付按各自受控路线处理

#### Scenario: delivery-only Connector 被用于入口
- **WHEN** Webhook 群机器人或企业机器人 Connector 被指定为 ingress
- **THEN** 系统在创建 Job 前拒绝，不把接入开关当作改变代码类型的权限

#### Scenario: Connector 已停用
- **WHEN** 新接收或投递使用已停用 Connector
- **THEN** 系统失败关闭并记录安全配置结果

### Requirement: Connector 认证材料只保存平台 Secret 引用
新建、编辑和发布 Connector SHALL 使用 `secret://platform/<code>` 引用受管 Secret；真实 Client Secret、Token、带凭据的 endpoint 与加签材料不得写入 Job、普通配置快照、审计或管理响应。Client ID、robot code 与用途模板 ID 可以作为非敏感配置管理。旧 `env:` 引用只能经过显式导入，`vault:`/`kms:` 不得被当作已实现 Provider。

#### Scenario: 保存和读取钉钉应用连接
- **WHEN** 管理员提交应用配置和认证材料
- **THEN** 后端在受控 Secret 边界保存认证材料，管理读取只返回非敏感字段和 `secret_configured` 等安全状态

#### Scenario: 必需 Secret 缺失停用或不可解析
- **WHEN** 使用 Connector 时不能解析其必需 Secret
- **THEN** 运行状态标为 `MISCONFIGURED`，停止 ingress/delivery，保留配置与历史，不生成空凭据或 fail open

### Requirement: 出站投递遵守受管目标与适用主机策略
Connector 型 HTTP Delivery SHALL 使用受管 endpoint、平台 Secret 引用或固定 Provider 路径，并执行对应 Adapter 的主机校验；配置了 Connector host allowlist 时，目标 host 不在列表 MUST 拒绝。用户消息与模型不得更改 endpoint、Connector 或认证 Header。原 Stream session webhook 是受信回调提供的专用短期回复路线，不等同于任意 Connector URL。

#### Scenario: 目标不在已配置 allowlist
- **WHEN** Delivery 的 endpoint host 未匹配该 Connector 配置的 host allowlist
- **THEN** 不发起请求，记录非重试安全配置错误，不记录带凭据完整 URL

#### Scenario: 原会话 webhook 过期
- **WHEN** 原回复路线的到期时间已经经过
- **THEN** 返回稳定中文过期错误，不改用默认群、其他用户或另一 Connector

### Requirement: 钉钉连接引用受治理企业
每个受管钉钉应用 Connector SHALL 引用且只能引用一个钉钉企业内部 ID，不接受自由 tenant 字符串改变企业命名空间。业务使用须同时满足连接启用、凭据可用和企业 `ACTIVE`；待验证企业可以连接 Stream 收集验证证据，但不得进入业务应用可运行来源。

#### Scenario: 同企业配置多个应用
- **WHEN** 管理员给已验证企业增加第二个 Connector
- **THEN** 两个应用共享企业身份命名空间，但各自维护凭据、配置和运行状态，并分别校验真实 Corp ID

#### Scenario: 企业停用但连接仍有心跳
- **WHEN** Connector 本身仍连接而企业为 DISABLED 或 ARCHIVED
- **THEN** 拒绝业务接收，不由心跳或重启恢复企业状态

#### Scenario: 删除或重建旧连接
- **WHEN** 旧 Connector 停用或被受保护测试重建清理
- **THEN** 其历史 Publication、Job、Tool 和 Delivery 引用保持原值，不自动切到新 Connector；重建保护与保留范围见 `platform-operations`

### Requirement: 管理端分别展示企业状态和 Connector Runtime 状态
渠道与触发器页面 SHALL 展示真实配置 revision、加载 revision、心跳、最近消息、安全错误和连接状态。Runtime 连接、SDK 注册、凭据可用性与企业验证 MUST 分别判断；`MISCONFIGURED`、`STALE`、`CONNECTED`、`READY`、`RECONNECTING`、`AUTH_FAILED` 等管理投影不得用“已部署”或“待注册”替代所有状态。

#### Scenario: 企业启用但应用断线
- **WHEN** 企业 ACTIVE 而一个应用处于 RECONNECTING
- **THEN** 页面同时展示企业已启用和连接重连，不回退企业为待验证

#### Scenario: SDK 已注册且心跳有效
- **WHEN** Connector 已启用、凭据正常，Runtime 报告 REGISTERED 和注册确认
- **THEN** 管理投影可显示 READY；缺失或陈旧心跳显示 STALE，不能仅凭数据库配置宣称运行正常

#### Scenario: 修改单个连接
- **WHEN** 一个 Connector revision 更新或管理员请求重启
- **THEN** Runtime 对应重建该连接，不重启无关 Connector

### Requirement: 唯一受管 Stream Runtime 按 lease 管理多个 Client
受管 `dingtalk-runtime` SHALL 通过内部控制 API 的服务认证与有效 lease 获取期望配置，按 Connector 管理 SDK Client；控制面复核 lease 后接收状态和事件。每个 Connector 的同一 Client MUST 同时注册机器人消息和官方卡片回调 topic，不为卡片另建同 Client ID 的连接。

#### Scenario: lease 失效或控制面无法续约
- **WHEN** Runtime 不再持有有效 lease
- **THEN** 不得继续作为有效接收者提交事件，按运行协议停止或恢复连接，不能绕过控制 API 写库

#### Scenario: 接收卡片点击
- **WHEN** 同一 SDK Client 收到卡片回调
- **THEN** Runtime 提取有界规范字段，在同一 lease 下交给内部控制面处理

### Requirement: Stream ACK 建立在持久接收或确认结果之后
机器人消息 SHALL 先由控制面完成企业校验、规范化事件和 Channel Inbox/Outbox 持久化，再向 SDK ACK。ACK 不等待 Agent、文件下载、OCR 或最终 Delivery。卡片回调只在确认服务持久接受幂等状态转换后 ACK；提交失败不得 ACK，以允许 Provider 重投。

#### Scenario: Channel Inbox 提交成功但队列暂不可用
- **WHEN** 数据库已保存事件与待发布记录
- **THEN** Stream 可以 ACK，Outbox 恢复发布，不依赖来源重新发送业务消息

#### Scenario: 持久化失败
- **WHEN** 控制 API 请求失败、lease 无效或事务未提交
- **THEN** Runtime 不 ACK，日志只记录状态和安全错误分类，不记录原 payload 或认证材料

#### Scenario: 卡片操作已批准
- **WHEN** 确认服务持久接受原主体的确认
- **THEN** Runtime 可返回按 key 更新卡片的 ACK，不等待 Provider 操作完成

### Requirement: Stream 规范化保留来源事实并限制输入大小
受管 Stream 接收 SHALL 从 SDK 消息保留稳定事件 ID、消息 ID、企业字段、实际 Staff ID、会话 ID/类型、机器人身份、当前文本、受支持附件、引用目标及安全时间。控制 API 提交的 `request_bytes` MUST 按规范化 JSON 的实际 UTF-8 字节数计算并校验，不能用字符数或含不同空白的重新序列化长度误拒绝中文消息。

#### Scenario: 中文紧凑 JSON 事件
- **WHEN** Runtime 提交含中文的规范化消息
- **THEN** 前后端按相同编码字节口径校验大小，合法有界消息进入持久接收

#### Scenario: 不完整或不支持事件
- **WHEN** 缺少必要稳定事件或会话事实、没有可用发送人，或富文本没有可读取内容
- **THEN** 返回稳定安全分类，不猜测身份、复制原报文到审计或创建模型任务

#### Scenario: 收到受信 Provider 标识
- **WHEN** 事件包含 union ID 或 open ID
- **THEN** 只按相应 Provider 字段解释，不把通用 senderId 伪装成 open ID；补全和冲突处理遵守 `identity-access`

### Requirement: 企业验证事件与普通业务事件幂等分离
待验证企业的合规首条消息 SHALL 只形成企业验证结果，同一验证事件重投不得在企业转为 ACTIVE 后创建业务 Job。ACTIVE 企业的业务消息 MUST 重新检查两个 Corp ID 与所属企业一致，再进入正式身份和应用路由处理。

#### Scenario: 验证消息重投
- **WHEN** 已用作企业验证的 Connector 与事件 ID 再次提交
- **THEN** 返回既有验证确认，不创建 Channel Outbox、候选、观察或 Job

#### Scenario: 重连后收到其他企业消息
- **WHEN** 受信消息 Corp ID 不匹配 Connector 已验证企业
- **THEN** 拒绝分发并写安全治理错误，重连成功不绕过企业校验

### Requirement: 钉钉应用路由使用受信机器人或群会话身份
私聊 SHALL 以受信机器人身份生成 `robot:<identity>` routing key，群聊以规范化群会话生成 `conversation:<id>`。当前用户身份仍由实际消息发送人解析，不能按整个群、机器人所有者或昵称授权。路由缺少稳定身份时不得从正文或群名推断。

#### Scenario: 两个群使用同一机器人
- **WHEN** 两个群具有不同 conversation ID
- **THEN** 可分别命中不同应用，但每条消息仍按各自实际发送人授权

#### Scenario: 私聊缺少消息级机器人身份
- **WHEN** 消息未提供 robotCode 或 chatbotUserId
- **THEN** 只可使用当前 Connector 或受控配置已声明的机器人身份；仍无法解析时失败关闭

### Requirement: Channel 在创建 Job 前解析活动业务应用
钉钉 Stream 和受管 Webhook SHALL 在 Job 创建前，以当前代码支持的 `local` deployment、Trigger 类型、Connector 和受信 routing key 解析活动业务应用。部署路由与用户业务 Environment/Base/Workshop 不是同一维度。命中后 MUST 使用不可变 Application Publication 的 Agent、Session、执行、文件和 Delivery 策略；与已固定事件 Agent 冲突或无活动匹配时失败关闭，不回退默认 Agent。

#### Scenario: 业务 Environment 与部署环境不同
- **WHEN** 消息 routing context 指向业务环境而控制面运行当前 local deployment 路由
- **THEN** 两者分别用于应用解析和受管数据范围校验，payload 不得更改 deployment

#### Scenario: Trigger 固定 Agent 与活动应用不一致
- **WHEN** Event 固定 Agent Publication 与命中应用不同
- **THEN** 阻止 Job 创建并记录配置冲突，不选择其中一个静默继续

#### Scenario: 未匹配或应用阻塞
- **WHEN** Resolver 返回 not_matched 或 blocked
- **THEN** 不创建 Job 或发布 Job 消息，通过已注册原渠道通知能力发送安全错误；通知失败独立记录，不回退运行 Agent

### Requirement: Channel 幂等贯穿事件消息附件和 Job
系统 SHALL 使用 Channel、Connector、稳定外部事件及各来源定义的事件语义生成幂等键，持久化事件、消息、附件和 Job 时复用既有事实。同一事件不得因 Runtime 重连、应用发布切换或队列重投产生第二次业务执行；Webhook 可配置冷却窗口的去重语义按其冻结配置执行。

#### Scenario: 钉钉消息重复投递
- **WHEN** 同一 Connector 重投同一稳定事件 ID
- **THEN** 返回既有接收结果，不新增 Message、Attachment、Job 或重复 Job Dispatch

#### Scenario: 两个 Connector 事件 ID 相同
- **WHEN** 不同 Connector 接收到同值外部事件 ID
- **THEN** 保持来源隔离，不错误合并为一个事件

### Requirement: 身份拒绝与应用拒绝不授予会话访问
钉钉 Channel SHALL 在 Job 和 Agent Session 创建前解析企业、当前外部身份与启用内部用户，并完成正式观察写入和应用访问检查。符合发现条件的身份拒绝交给 `identity-access` 的安全候选流程；它不能获得工作区、会话或 Tool 数据。ONES 凭据不可用只影响需要 ONES 的工具，不自动否定钉钉应用访问。

#### Scenario: 群成员没有可用身份或应用权限
- **WHEN** 同群一条消息的实际发送人未绑定或未授权
- **THEN** 返回安全提示，不创建 Job，也不泄露群工作区文件名、内容或其他成员凭据

#### Scenario: 正式身份观察写入失败
- **WHEN** 当前身份有效但必要观察事务失败
- **THEN** 不分发业务 Job，不把身份事实写入当作可选日志

### Requirement: Agent Session 使用完整通用隔离键
Agent Session SHALL 保存通用 Channel、Connector、外部 conversation、内部 requester、会话类型、Project、Business Application、Application Publication 和 execution scope hash。应用连续会话仅使用 `channel` 模式，旧 `application`/`actor` 共享模式不得创建新 Job。当前 v2 Session key 还包含 `external_identity_id`；群聊只从 requester scope 排除内部 requester，不排除该外部身份字段。

#### Scenario: 同一身份在同一边界连续提问
- **WHEN** Channel、Connector、会话、外部身份、应用版本和范围全部一致且允许连续会话
- **THEN** 原子复用 Session，为每个新事件创建独立幂等 Job

#### Scenario: 应用 Publication 或范围变化
- **WHEN** 同一外部会话命中新 Publication 或 execution scope hash 改变
- **THEN** 创建新 Session，不将旧 Session 消息或摘要自动放入新版本上下文

#### Scenario: 群聊的外部身份不同
- **WHEN** 同群两个已绑定成员具有不同 `external_identity_id`
- **THEN** 当前 v2 key 分别生成 Session；不得据“同群”宣称已实现跨成员共享 Agent 会话

#### Scenario: Webhook 事件创建 Job
- **WHEN** 受管 Webhook 通过授权进入 Job 创建
- **THEN** 按事件使用隔离会话，不将告警事件串为钉钉连续上下文

### Requirement: 会话消息保持幂等顺序归属与引用事实
Session 内消息 SHALL 分配单调 sequence，保存外部消息 ID、角色、实际发送人、安全显示名称、类型、时间和适用引用目标。`originalMsgId` MUST 持久化以支持被引消息附件解析；引用文本仅作为不可信上下文，不得替换当前用户文本、身份或成为任意文件访问授权。

#### Scenario: 引用同来源已保存消息
- **WHEN** 当前消息带可解析的引用目标
- **THEN** 可附带有界发送人和引用内容，并保留目标消息 ID 供任务文件硬证据解析

#### Scenario: 引用无法解析
- **WHEN** 被引消息不存在或不在允许边界
- **THEN** 使用当前消息和安全不可用状态继续既有判断，不猜测其他会话内容

### Requirement: 连续上下文有界且摘要失败可降级
系统 SHALL 只读取 Job 所属 Session 的最近消息与滚动摘要，排除本轮重复输入和 `attachment_intake` 消息，并遵守消息数、摘要和总字符预算。当前默认摘要器是确定性的有界消息摘录，不额外调用模型。摘要更新 MUST 使用版本与 sequence 游标并发控制；失败时使用受限最近窗口，不阻断当前 Job。

#### Scenario: 用户追问前一轮
- **WHEN** 同一允许 Session 中的 Job 构建上下文
- **THEN** 获得带发送人归属的最近消息或摘要，不混入其他 Project、私聊或 Session

#### Scenario: 私聊请求人不匹配
- **WHEN** Job requester 与私聊 Session requester 不同
- **THEN** 拒绝上下文读取，不返回摘要或消息

#### Scenario: 历史超过预算或摘要失败
- **WHEN** 会话消息超出预算或摘要推进异常
- **THEN** 按配置裁剪并保留截断状态，降级到最近窗口；完整文件表示不直接拼接进会话上下文

### Requirement: Channel 附件入口只承担受控下载交接
钉钉附件 SHALL 以安全类型、名称、声明大小和短期来源凭证进入异步文件链路，入口先校验数量、类型与声明上限，下载后仍须按 `document-file-processing` 校验真实内容。来源凭据仅可短期加密持久化，队列只传内部附件 ID；下载成功、拒绝、最终失败或过期后清除凭据。

#### Scenario: 附件下载重试
- **WHEN** 同一附件在来源下载或文件导入后发生重试
- **THEN** 通过稳定附件与精确版本事实复用，不产生重复对象或 Job

#### Scenario: 处理原件
- **WHEN** File Worker 获得合法源附件
- **THEN** 通过 File Service 导入，不能直接持有对象存储凭据；解析和 OCR 由受限处理链路执行，不阻塞 Stream ACK

#### Scenario: 图片文件名与真实格式不一致
- **WHEN** JPEG、PNG 或 WebP 可安全解码并重编码但渠道扩展名错误
- **THEN** 文件域用真实格式 canonical extension 生成安全名称；普通 Office/PDF 不套用该图片兼容规则

### Requirement: 纯附件暂存和文字轮次按明确文件证据衔接
启用任务文件能力与连续渠道会话时，纯附件消息 SHALL 只暂存到受管工作区并异步导入，不创建 Agent Job、普通结果 Delivery 或正常成功回复。文字到达时 SHALL 交给 `task-file-workspace` 的 Admission Plan 解析本轮确定性文件依赖；无证据不能因“刚上传过文件”而认领全部暂存附件。

#### Scenario: 上传多份文件后问无关问题
- **WHEN** 后续文字没有自身附件、引用、精确文件名或其他已注册绑定证据
- **THEN** 本轮依赖为空，正常创建无文件依赖 Job，暂存文件不被自动消费

#### Scenario: 文字只引用一份附件
- **WHEN** 当前消息确定引用一个文件版本
- **THEN** 仅按计划冻结该依赖，其余附件保持原状态，不混入当前 Job

#### Scenario: 纯附件导入被确定拒绝
- **WHEN** 已建立受治理回复路线的暂存附件因类型、编码或上限被拒绝
- **THEN** 可按附件 ID 幂等发送安全失败说明；这不是创建一个 Agent 执行轮次

### Requirement: 文件等待只绑定已冻结来源依赖
Channel 创建的 `WAITING_INPUT` Job SHALL 只等待本轮 Admission Plan 已冻结附件的来源下载或导入终态。唤醒 MUST 复用冻结依赖并重做能力门禁，不重新扫描认领其他附件，也不得以 WAITING_INPUT 等待 Docling。需要可读内容而表示尚未就绪或已失败时，发送固定中文系统说明，不发布 Agent 执行。

#### Scenario: 原件已导入但 Markdown 仍处理中
- **WHEN** 本轮要求 READABLE_CONTENT 而表示为 PENDING
- **THEN** 按文件能力门禁安全结束本轮，不等待 OCR、不调用模型，不返回原始 `agent_runtime_error` JSON

#### Scenario: 本轮只需要文件元数据或原件
- **WHEN** 对应精确版本已就绪而 Markdown 仍未生成
- **THEN** 不因不需要的可读表示阻挡本轮，不自动物化正文

#### Scenario: 群工作区请求
- **WHEN** 群成员请求同群工作区文件
- **THEN** 使用当前发送人授权及受信企业/Connector/群会话归属；不得共享个人 Credential、跨群文件或创建逐成员钉钉 ACL 副本，精确可访问边界以任务文件规格为准

### Requirement: 普通 Agent 结果回复冻结的原会话
钉钉 Stream 命中的应用 SHALL 配置且只解析一个 `reply_original` 绑定，并要求绑定 Connector 与来源一致。普通文字结果使用本事件受信 session webhook；短期回复凭据在持久接收与回复路线中受控加密，不进入 audit、API 或队列。失败说明与最终结果使用安全中文，接收 ACK 不代表 Agent 或 Delivery 成功。

#### Scenario: Agent 完成当前私聊问题
- **WHEN** Job 产生最终回答
- **THEN** 按冻结原私聊路线投递，不改发默认群或其他 Connector

#### Scenario: 应用 reply-original 配置不完整
- **WHEN** 绑定数量、来源 Connector 或路线类型不符
- **THEN** Job 创建失败并尝试安全原会话通知，不静默使用另一投递方式

#### Scenario: Delivery 需要重试
- **WHEN** 最终回答投递发生可重试故障
- **THEN** 只重试该 Delivery，不重新运行 Agent 或已完成的外部 mutation

### Requirement: 同会话文件交付冻结受信目标
Stream 入站 SHALL 同时冻结来源 Connector、会话类型和 robot code，私聊冻结实际 sender Staff ID，群聊冻结 openConversationId，供同一 Job 精确 File Version 的专用交付使用。文件交付 MUST 从这些持久事实解析，不能从模型参数指定接收人或群；复用来源应用凭据不开放 Stream 为通用 Delivery Connector。

#### Scenario: 私聊交付生成文件
- **WHEN** Job 提交获授权 TXT 或 Markdown 新版本
- **THEN** 文件交付使用冻结实际发送人和来源应用，普通文字仍使用原 session webhook

#### Scenario: 群聊原样交付 LOG
- **WHEN** Job 请求交付 Manifest 中已有授权 LOG 精确版本
- **THEN** 只发到冻结当前群，不改写 LOG、不创建新版本、不选择默认群

### Requirement: 主动消息的三种业务语义与普通 Delivery 分离
`dingtalk_send_message_to_group_by_robot` SHALL 只向当前 Job 的受信来源群发送受确认消息；`dingtalk_batch_send_message_to_users_by_robot` SHALL 对明确 `user_ids` 整批发送独立机器人单聊；`dingtalk_send_work_notification` SHALL 只在明确工作通知语义下向当前用户本人发送。旧 `dingtalk_send_robot_message` 已从当前注册合同排除，不得继续作为可调用工具。三者不得相互降级或替代普通 Agent 结果投递，具体参数、Provider 响应与确认规则见 `governed-api-capability` 和 `execution-delivery`。

#### Scenario: 当前来源群 Tool 被调用
- **WHEN** Agent 使用 `dingtalk_send_message_to_group_by_robot`
- **THEN** 只解析当前受信来源群，不读取批量 Tool 的 user_ids，不支持任意姓名或群 ID 指定目标；当前 Job 为私聊时拒绝该群工具

#### Scenario: 用户请求给明确员工发普通私信
- **WHEN** 用户直接明确一个或多个 userId，或按姓名通过本 Job 的搜索、详情核实与必要消歧得到稳定 userId，且批量消息 Tool 获授权
- **THEN** 冻结整批收件人并按确认流程执行，最终回答仍独立回复原发起会话

#### Scenario: 所需 Tool 缺失或目标有歧义
- **WHEN** 请求普通私信但只有工作通知 Tool，或姓名尚未唯一解析
- **THEN** 说明能力或目标限制，不改发通知、不缩小收件人、不用发送人昵称替代目标

### Requirement: 钉钉 Connector 只配置代码定义的卡片用途
受管 `dingtalk_enterprise_stream` Connector MAY 保存非敏感用途化模板绑定，当前唯一用途为 `external_action_confirmation`。模板 ID 与代码固定合同版本属于具体企业应用 Connector，前后端 SHALL 校验并展示该配置；Agent 不得选择模板，未知用途不得进入运行时。

#### Scenario: 保存有效确认卡模板
- **WHEN** 管理员提交合法模板 ID
- **THEN** Connector metadata 保存用途和固定合同版本，管理 API 返回可编辑的非敏感字段

#### Scenario: 新 mutation 没有可用确认模板
- **WHEN** 所用 Connector 未配置有效该用途模板
- **THEN** 确认 Intent 准备失败关闭，不用全局环境模板静默替代；此限制不应伪装成 Stream 已断线

#### Scenario: 切换到另一钉钉组织
- **WHEN** 应用需改用其他企业
- **THEN** 新建并验证对应企业和 Connector 后配置模板，不修改已验证 Corp ID 复用旧绑定

### Requirement: Webhook Trigger 使用真实草稿和不可变发布
管理端 SHALL 提供 Grafana Alertmanager 和通用 JSON Trigger 的创建、编辑、验证、发布、启停、回滚、public ID/凭据轮换与事件历史。草稿使用 revision，发布固定 adapter、源 Connector、服务账号、Agent Publication、routing、Delivery、幂等和限流配置；保存草稿不改变运行版本。

#### Scenario: 两人并发修改 Trigger
- **WHEN** 后提交者使用过期 expected revision
- **THEN** 返回版本冲突，不覆盖新草稿或运行 Publication

#### Scenario: 发布依赖缺失
- **WHEN** Connector、服务账号、固定 Agent、Delivery、Bearer Secret 或 schema 不可用
- **THEN** 返回中文字段错误，不创建 Publication

#### Scenario: 无副作用报文预览
- **WHEN** 管理员提交示例 JSON 测试映射
- **THEN** 只返回有界脱敏映射预览，不持久化原 body、不创建 Job、不发送 Delivery

### Requirement: 公共 Webhook 只接受有界 JSON 和唯一强 Bearer
公共入口 SHALL 通过不可预测 public ID 找到启用 Trigger 的有效 Publication，检查来源 Connector 和启用服务账号，并限定 Content-Type、UTF-8 body 大小、JSON 深度与集合数量。认证只支持 `bearer_v1`，每个 binding 使用唯一且至少符合代码强度要求的受管 Token，进行常量时间比较；缺失、弱值、不可解析或错误认证必须失败关闭。

#### Scenario: 使用合法标准 Bearer
- **WHEN** 有效 publication 收到符合大小和结构上限的 JSON 与匹配的 `Authorization: Bearer`
- **THEN** 继续映射和接收，不把认证成功当作业务授权成功

#### Scenario: 旧 Header 或其他认证模式
- **WHEN** 请求只提供 `X-Grafana-Token`，或配置 HMAC、timestamp、nonce 认证
- **THEN** 拒绝，不进入匿名或旧 Header 翻译兼容路径；事件去重不能表述为独立防重放认证

#### Scenario: 未知或轮换后的 public ID
- **WHEN** public ID 不存在或已失效
- **THEN** 返回统一安全未找到结果，不暴露历史配置或 Secret

### Requirement: Webhook 映射不能覆盖授权和目标事实
Webhook SHALL 使用冻结 typed adapter、JSON Pointer、声明式条件和有界模板生成 Channel message 与 routing；提取范围必须在配置 allowlist 内，文本始终是不可信外部数据。payload 不得控制服务账号、Agent、Tool、Connector、Secret、Delivery endpoint 或扩大业务范围。

#### Scenario: 通用 JSON 必填路径缺失
- **WHEN** 事件 ID、消息或要求的 routing 路径不存在或类型不匹配
- **THEN** 保存安全映射失败状态，不创建 Job

#### Scenario: payload 声明其他应用或目标
- **WHEN** 外部 body 含任意 actor、Agent、Connector 或投递字段
- **THEN** 规范化仅使用声明字段与冻结控制事实，其余排除或拒绝；不得把完整原 payload 放入 Session、Job 或 Prompt

### Requirement: Grafana 按 firing 告警组生成事件
`grafana_alertmanager_v1` SHALL 只对 firing 生成可分发事件，用 groupKey 或稳定排序 fingerprints 标识告警组；一个组生成一个有界消息，不按 alerts 条数逐个创建 Job。非 firing 记录 IGNORED 并返回忽略结果，`ea_*` labels 仅为有界映射和诊断输入，不能替代发布与范围授权。

#### Scenario: 多条 firing alerts 属于同组
- **WHEN** 合法 payload 包含一组多个 alerts
- **THEN** 生成一个事件，重复处理遵守该 Trigger 冻结去重/冷却配置

#### Scenario: resolved 告警
- **WHEN** payload status 为 resolved
- **THEN** 不进入 Job 调度，保留有界忽略事实

### Requirement: Webhook 持久受理与业务授权分阶段完成
接收服务 SHALL 在认证、结构、映射、过滤和限流通过后，用事务保存 Event 与 Outbox，成功后返回 `202 Accepted`。该响应只证明持久受理。Dispatcher SHALL 使用接收时固定的 Trigger/Agent Publication 与服务账号，并重新检查启停、完整性和 Channel/应用授权后创建 Job；不得把 Inbox 接受等同于业务授权已通过。

#### Scenario: 排队期间发布新 Trigger
- **WHEN** 已接受 Event 等待分发而管理员发布新版本
- **THEN** Dispatcher 仍读取 Event 固定的 Trigger/Agent Publication；若与当前活动应用路由冲突则安全失败，不静默替换版本

#### Scenario: 排队期间服务账号停用
- **WHEN** Dispatcher 处理已接受事件时账号或 Trigger 已停用
- **THEN** 记录分发失败，不创建 Job

#### Scenario: Broker 故障或重复消息
- **WHEN** Outbox 首次发送失败或 dispatcher 重复收到已有 Job 的 Event
- **THEN** 通过有界恢复重试发布或返回幂等成功，不创建第二个 Job

### Requirement: Webhook 限流去重和历史均有界
系统 SHALL 按 Trigger 配置执行每分钟速率、在途并发和冷却窗口。冷却启用时当前代码将时间窗编号加入 dedup key，同一窗口内重复事件幂等，跨窗口可产生新的诊断事件。历史仅保存 hash、大小、有界安全摘要、认证/过滤状态、固定版本、correlation、Job 关联与安全错误，不保存完整 raw body。

#### Scenario: 告警风暴超限
- **WHEN** Trigger 当前请求数或在途数达到发布限制
- **THEN** 返回限流结果且不创建额外可分发事件，不影响其他 Trigger 独立额度

#### Scenario: 管理员查看事件历史
- **WHEN** 有权管理员查询事件
- **THEN** 展示接收、忽略、分发与 Job/Delivery 状态的区别，不返回凭据、原 body 或 Provider 原响应

#### Scenario: 事件摘要到期
- **WHEN** 清理配置允许删除的过期摘要
- **THEN** 保持独立 Agent Job、审计与 Delivery 历史，不以摘要清理抹去执行事实

## 实现依据与验证边界

本基线于 2026-09-16 按当前代码、迁移和测试定义重组。`Confirmed-current` 仅指仓库中有对应实现；`Documented-intent` 或已归档计划不证明真实钉钉、Webhook、OCR 或 Delivery 验收通过。

- Connector 与 Runtime：`backend/app/modules/channel/infrastructure/connector_registry.py`、`backend/app/modules/managed_channel/application/service.py`、`infrastructure/repository.py`、`dingtalk-runtime/src/sdk-client.ts`、`runtime-manager.ts`、`control-api.ts`；静态覆盖见 `backend/tests/test_managed_multi_dingtalk_runtime.py`、`dingtalk-runtime/test/runtime-manager.test.ts`、`control-api.test.ts` 与 `lease-acquisition.test.ts`。
- 钉钉规范化、应用路由和 Session：`backend/app/modules/dingding/application/dingtalk_stream_service.py`、`backend/app/modules/channel/application/channel_ingress_service.py`、`backend/app/modules/job/application/create_agent_job_service.py`、`backend/app/modules/agent/application/conversation_context.py`；静态覆盖见 `backend/tests/test_dingtalk_stream_ingress.py`、`test_channel_ingress_and_delivery.py`、`test_dingtalk_identity_isolation_acceptance.py`。
- 附件和文件交接：`backend/app/modules/job/application/file_context.py`、`backend/app/modules/attachments/dingtalk_downloader.py`、`backend/app/modules/delivery/infrastructure/file_delivery_sender.py`；静态覆盖见 `backend/tests/test_dingtalk_media_downloader.py`、`test_dingtalk_attachment_names.py`、`test_dingtalk_file_delivery_sender.py`。
- 原会话 Delivery 与卡片：`backend/app/modules/delivery/infrastructure/adapters.py`、`backend/app/shared/dingtalk_card_templates.py`、`backend/migrations/128_expand_dingtalk_confirmation_card_templates.sql`、`frontend/src/contexts/applications/presentation/managed-channels-panel.tsx`；静态覆盖见 `backend/tests/test_dingtalk_delivery.py`、`test_dingtalk_mcp_runtime.py` 与前端 `managed-channels.test.tsx`。
- Webhook：`backend/app/modules/webhook/application/ingress_service.py`、`authentication.py`、`mapping.py`、`trigger_service.py`、`dispatch_service.py`；静态覆盖见 `backend/tests/test_webhook_api.py`、`test_webhook_mapping_security.py`、`test_webhook_ingress_dispatch.py`、`test_webhook_outbox_recovery.py`。
- 已明确修正的实现边界：应用 ingress 路由当前固定为 local；v2 群 Session key 包含 external_identity_id；当前摘要器是确定性摘录；Webhook 202 先于 Dispatcher 的业务授权；冷却按时间窗去重；旧 dingtalk_send_robot_message 已退役，当前群消息工具只支持受信来源群。配置 host allowlist 的校验不等于所有空 allowlist 或 Stream 临时回复路径都具有统一默认拒绝策略，当前代码不能据此宣称完整公网出站防护。
- 本次未调用真实钉钉、ONES 或公网 Webhook，未启动部署、运行数据库迁移或重放业务事件；测试文件只作为静态覆盖证据。本地 HTTP/Compose 功能不证明生产 HTTPS 终止或公网安全；真实环境验收与历史未完成任务继续单独保留。
