## MODIFIED Requirements

### Requirement: MVP只接受现代白名单格式
系统 SHALL为现有消息附件兼容链路继续支持JPEG、PNG、WebP、DOCX、XLSX、PPTX和Markdown，并为`text-v1`任务工作区支持UTF-8 `.txt`、为`text-v2`任务工作区支持UTF-8 `.txt/.log/.md`；`.markdown`只保留在旧兼容链路。系统 MUST根据冻结格式策略、真实内容探测、允许声明MIME、扩展名、数量、文件大小、解压后大小及结构上限进行校验。任务工作区文本单文件 MUST不超过15 MiB，允许输入UTF-8 BOM但不得猜测GBK或UTF-16。系统 MUST拒绝DOC、XLS、PPT、未注册扩展名及其它未支持格式。

#### Scenario: 现代Office附件通过现有兼容校验
- **WHEN** DOCX、XLSX或PPTX的扩展名、MIME、大小和结构符合现有附件策略
- **THEN** 系统保存对象并进入现有受限文本提取
- **AND** 该文件不进入`text-v1/text-v2`任务工作区编辑能力

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

#### Scenario: 类型伪装或超限
- **WHEN** 扩展名与允许MIME或真实内容冲突，或附件数量、大小、解压后大小、行列或幻灯片超过对应策略
- **THEN** 系统将attachment标记为REJECTED并保存安全错误码

#### Scenario: 旧版Office或其他格式到达
- **WHEN** 消息包含DOC、XLS、PPT、PDF、压缩包、音视频、SVG、脚本、可执行文件或未知格式
- **THEN** 系统不解析内容并返回不泄漏内部信息的格式说明

### Requirement: 文档在受限worker中提取
系统 SHALL由非root、无外网、受CPU、内存和时间限制的File Worker处理消息附件。现有兼容链路继续提取DOCX段落/表格、XLSX工作表有界单元格、PPTX幻灯片文本和Markdown纯文本；任务工作区`.txt/.log/.md`只执行有界格式、大小、UTF-8和二进制拒绝校验并导入原始文本。Worker MUST NOT执行公式、宏、嵌入对象、Markdown HTML、链接、远程资源或其它主动内容，本阶段 MUST NOT调用`docling-serve`。

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

### Requirement: Channel 文件输入绑定任务工作区
Channel ingress SHALL把没有非空文字且命中当前Business Application Publication冻结格式策略的`.txt/.log/.md`消息作为附件暂存事件：解析真实身份和Publication，创建或复用当前Channel Session与活动任务工作区，持久化并异步导入附件，但 MUST NOT创建Agent Job、Job Dispatch、Result Delivery、占位文字指令或用户回复。同一Session中连续到达的纯附件消息 SHALL进入同一未消费附件集。第一条后续非空文字消息 MUST在创建唯一Agent Job的事务中原子认领该集合；已经认领的附件 MUST NOT被后续无关Job再次自动认领，但其文件版本可以继续作为工作区候选。消息附件身份与任务工作区引用 MUST分离，工作区过期不得提前删除仍在独立保留期内的原始附件。

#### Scenario: 连续发送三种纯文本附件
- **WHEN** 已授权用户在同一钉钉会话依次发送合法`.txt`、`.log`和`.md`且都没有非空文字，并命中`text-v2`
- **THEN** 系统创建或复用当前任务工作区并异步导入三个附件
- **AND** 不创建Agent Job、Job Dispatch、Result Delivery或用户回复

#### Scenario: text-v1收到LOG或Markdown
- **WHEN** 当前Publication冻结`text-v1`且用户发送`.log`或`.md`
- **THEN** 系统不把附件导入任务工作区或为其启用文件Job
- **AND** 按既有兼容或不支持策略返回安全结果，不追溯升级Publication

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

### Requirement: Stream 入站冻结同会话文件交付事实
钉钉Stream入站在普通回复使用`sessionWebhook`时，MUST同时从受信回调冻结会话类型、来源Stream Connector、`robotCode`，并按私聊冻结实际`senderStaffId`、按群聊冻结`openConversationId`，供同一Job的精确文件版本交付使用。文件交付不得从模型参数获取这些事实，也不得因为复用来源应用凭据而把Stream Connector开放为通用Delivery Connector。新提交的`.txt/.md`与当前Manifest中获授权的既有`.txt/.log/.md`精确版本都必须使用相同冻结reply route；交付`.log`不得创建或修改文件版本。

#### Scenario: 私聊生成Markdown文件
- **WHEN** 私聊Stream消息触发的Job成功提交一个新Markdown版本
- **THEN** 文件Delivery使用冻结的实际发送人和来源Stream应用调用私聊机器人文件消息接口
- **AND** 普通文字最终回复仍使用原`sessionWebhook`

#### Scenario: 群聊原样交付LOG
- **WHEN** 群聊Job按用户请求交付Manifest中获授权的既有LOG精确版本
- **THEN** 文件Delivery使用冻结的`openConversationId`、`robotCode`和来源Stream应用调用群机器人文件消息接口
- **AND** 不修改LOG、创建新版本或把文件发送到其它Connector
