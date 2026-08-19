## MODIFIED Requirements

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
系统 SHALL 为启用`docling-text-v1`的任务工作区链路支持PDF、DOCX、XLSX、PPTX、JPEG、PNG和WebP原件，并继续按已冻结文本格式策略支持UTF-8 TXT、LOG和Markdown；系统 MUST 根据真实内容探测MIME、校验扩展名、数量、文件大小、解压后大小及结构上限。源文档单文件 MUST 不超过25MiB；Agent可读文本仍 MUST 不超过15MiB。系统 MUST 拒绝DOC、XLS、PPT、宏文件及其他未支持格式。

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

#### Scenario: 类型伪装或超限
- **WHEN** 扩展名与真实MIME冲突，或附件数量、大小、页数、解压后大小、行列、像素或幻灯片超过对应固定策略
- **THEN** 系统将attachment或processing run标记为确定拒绝
- **AND** 不调用模型、不静默截断或降级到宽松解析器

#### Scenario: 旧版Office或其他格式到达
- **WHEN** 消息包含DOC、XLS、PPT、宏文件、压缩包、音视频、SVG、脚本、可执行文件或未知格式
- **THEN** 系统不解析内容并返回不泄漏内部信息的格式说明

#### Scenario: PDF进入未启用Profile的应用
- **WHEN** 应用Publication未选择文档处理Profile而消息包含PDF
- **THEN** 系统不创建processing run并返回当前应用未启用文档读取能力的安全状态

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

### Requirement: 图片只安全存储而不宣称可理解
系统 SHALL 对JPEG、PNG和WebP执行真实格式、文件大小和像素限制校验，去除不需要的元数据后通过File Service保存原件；仅当应用Publication冻结`docling-text-v1`时，系统 SHALL 允许Docling对图片执行OCR文字提取。系统 MUST NOT把OCR结果等同于架构图、流程图、仪表盘、照片或其它视觉语义理解，也不得调用VLM或生成虚构描述。

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
