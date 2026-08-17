## ADDED Requirements

### Requirement: Channel 文件输入绑定任务工作区
Channel ingress SHALL 把没有非空文字的受支持 `.txt` 消息作为附件暂存事件：解析真实身份和 Business Application Publication，创建或复用当前 Channel Session 与活动任务工作区，持久化并异步导入附件，但 MUST NOT 创建 Agent Job、Job Dispatch、Result Delivery、占位文字指令或用户回复。同一 Session 中连续到达的纯附件消息 SHALL 进入同一未消费附件集。第一条后续非空文字消息 MUST 在创建唯一 Agent Job 的事务中原子认领该集合；已经认领的附件 MUST NOT 被后续无关 Job 再次自动认领，但其文件版本可以继续作为工作区候选。消息附件身份与任务工作区引用 MUST 分离，工作区过期不得提前删除仍在独立保留期内的原始附件。

#### Scenario: 连续发送多个纯附件消息
- **WHEN** 已授权用户在同一钉钉会话依次发送三个合法 `.txt` 且都没有非空文字
- **THEN** 系统创建或复用当前任务工作区并异步导入三个附件
- **AND** 不创建 Agent Job、Job Dispatch、Result Delivery 或用户回复

#### Scenario: 后续文字统一触发
- **WHEN** 用户随后在同一 Session 发送非空文字指令
- **THEN** 系统只创建一个 Agent Job并原子认领此前尚未消费的三个附件
- **AND** Job File Manifest冻结每个可用附件的精确版本并根据该文字只回复一次

#### Scenario: 文字先于附件导入完成
- **WHEN** 后续文字到达时一个或多个已暂存附件仍在导入
- **THEN** 系统创建同一个 `WAITING_INPUT` Job并绑定完整待处理集合
- **AND** File Worker只在该集合全部进入安全终态后释放该 Job一次，不为单个附件创建额外 Job

#### Scenario: 已消费附件不会再次自动认领
- **WHEN** 已有文字 Job认领并处理暂存附件后，用户再发送无显式文件引用的普通文字
- **THEN** 新 Job不再次把这些附件作为本次新上传文件自动物化
- **AND** 文件仍可作为当前工作区的有界候选按需选择

#### Scenario: 工作区先于附件到期
- **WHEN** 任务工作区到期但关联消息附件仍在360天保留期内
- **THEN** 系统删除工作区临时内容并保留消息附件及其消息来源关系

### Requirement: Stream 入站冻结同会话文件交付事实
钉钉 Stream 入站在普通回复使用 `sessionWebhook` 时，MUST 同时从受信回调冻结会话类型、来源 Stream Connector、`robotCode`，并按私聊冻结实际 `senderStaffId`、按群聊冻结 `openConversationId`，供同一 Job 的精确文件版本交付使用。文件交付不得从模型参数获取这些事实，也不得因为复用来源应用凭据而把 Stream Connector 开放为通用 Delivery Connector。

#### Scenario: 私聊生成文件
- **WHEN** 私聊 Stream 消息触发的 Job 成功提交一个新 TXT
- **THEN** 文件 Delivery 使用冻结的实际发送人和来源 Stream 应用调用私聊机器人文件消息接口
- **AND** 普通文字最终回复仍使用原 `sessionWebhook`

#### Scenario: 群聊生成文件
- **WHEN** 群聊 Stream 消息触发的 Job 成功提交一个新 TXT
- **THEN** 文件 Delivery 使用冻结的 `openConversationId`、`robotCode` 和来源 Stream 应用调用群机器人文件消息接口
- **AND** 不把文件发送到默认群或其它 Connector

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
系统 MUST 用 `file-worker` 替换 `attachment-worker` 服务名，同时继续消费现有附件队列和兼容在途消息。File Worker SHALL 使用短期来源凭证下载附件并通过 File Service 内部流式接口导入，MUST NOT 获得 MinIO 凭据或直接写对象存储；附件下载终态仍须清除来源凭证。尚未被文字认领的纯附件只进入 `staged` 终态而不释放或创建 Job；已经绑定唯一 `WAITING_INPUT` Job 的附件集合全部进入安全终态后，File Worker才释放该 Job一次。

#### Scenario: 切换时存在旧附件消息
- **WHEN** 部署切换到 `file-worker` 时原附件队列仍有合法消息
- **THEN** File Worker 使用原幂等 attachment ID继续处理
- **AND** 不产生重复消息、附件、对象或 Job

## MODIFIED Requirements

### Requirement: MVP只接受现代白名单格式
系统 SHALL 为现有消息附件兼容链路继续支持JPEG、PNG、WebP、DOCX、XLSX、PPTX和Markdown，并为新的任务工作区链路支持 UTF-8 `.txt`；系统 MUST 根据真实内容探测MIME、校验扩展名、数量、文件大小、解压后大小及结构上限。任务工作区 `.txt` 单文件 MUST 不超过15 MiB，允许输入UTF-8 BOM但不得猜测GBK或UTF-16。系统 MUST 拒绝DOC、XLS、PPT及其他未支持格式。

#### Scenario: 现代Office附件通过现有兼容校验
- **WHEN** DOCX、XLSX或PPTX的扩展名、MIME、大小和结构符合现有附件策略
- **THEN** 系统保存对象并进入现有受限文本提取
- **AND** 本变更不把该文件加入第一阶段任务工作区编辑能力

#### Scenario: UTF-8 TXT进入任务工作区
- **WHEN** `.txt` 内容为有效UTF-8且大小不超过15 MiB
- **THEN** 系统允许 File Worker通过File Service导入并进入任务工作区链路

#### Scenario: TXT编码或大小不合法
- **WHEN** `.txt` 是GBK、UTF-16、无效UTF-8或超过15 MiB
- **THEN** 系统将attachment标记为REJECTED并保存安全错误码

#### Scenario: 类型伪装或超限
- **WHEN** 扩展名与真实MIME冲突，或附件数量、大小、解压后大小、行列或幻灯片超过对应策略
- **THEN** 系统将attachment标记为REJECTED并保存安全错误码

#### Scenario: 旧版Office或其他格式到达
- **WHEN** 消息包含DOC、XLS、PPT、PDF、压缩包、音视频、SVG、脚本、可执行文件或未知格式
- **THEN** 系统不解析内容并返回不泄漏内部信息的格式说明

### Requirement: 文档在受限worker中提取
系统 SHALL 由非root、无外网、受CPU、内存和时间限制的 File Worker 处理消息附件。现有兼容链路继续提取DOCX段落/表格、XLSX工作表有界单元格、PPTX幻灯片文本和Markdown纯文本；任务工作区 `.txt` 只执行有界UTF-8校验和内容导入。Worker MUST NOT执行公式、宏、嵌入对象、HTML或远程资源，第一阶段 MUST NOT 调用 `docling-serve`。

#### Scenario: 现有文档提取成功
- **WHEN** 受支持Office或Markdown文档在资源上限内完成现有解析
- **THEN** 系统保存有界纯文本、分段信息、解析器版本和截断状态并标记READY

#### Scenario: TXT校验成功
- **WHEN** 任务工作区 `.txt` 通过大小和UTF-8校验
- **THEN** File Worker通过File Service保存原始内容并标记可用于精确版本物化
- **AND** 不声称调用了Docling或其它文档解析器

#### Scenario: 加密、宏格式或损坏文档
- **WHEN** 文档加密、属于宏格式、包含禁止结构、损坏或触发资源限制
- **THEN** 系统停止处理并标记REJECTED或FAILED，不向Agent暴露内容

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
