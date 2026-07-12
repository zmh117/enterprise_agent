## ADDED Requirements

### Requirement: 系统分层保存多模态消息
系统 SHALL 在PostgreSQL保存消息正文、附件元数据、状态、安全提取文本和对象引用，并在私有S3兼容对象存储保存图片及文档原始二进制。系统 MUST NOT 将原始二进制写入PostgreSQL、RabbitMQ消息、日志或审计payload。

#### Scenario: 文本与文档一起到达
- **WHEN** 一条消息包含文本和一个受支持文档
- **THEN** 系统保存一条user message、一条关联attachment记录，并把文档对象写入私有bucket

#### Scenario: 仅图片消息到达
- **WHEN** 一条消息没有文本但包含受支持图片
- **THEN** 系统保存消息和图片attachment，并以图片处理结果作为可用输入或明确标记不可读

### Requirement: 系统只接受受支持且安全的附件类型
系统 SHALL 支持策略允许的JPEG、PNG、WebP、DOC、DOCX、XLS、XLSX、PPT、PPTX和Markdown附件，并 MUST 根据实际内容探测MIME、校验扩展名、数量、单文件大小、单消息总大小及解析资源上限。

#### Scenario: Office附件通过校验
- **WHEN** 文件扩展名、探测MIME、大小和数量均符合策略且恶意内容扫描通过
- **THEN** 系统保存对象并进入受控文本提取流程

#### Scenario: 类型伪装或超限附件
- **WHEN** 文件扩展名与探测MIME冲突，或附件数量、大小、页数、行列数、幻灯片数超过策略
- **THEN** 系统将attachment标记为REJECTED、保存安全错误码且不向Agent暴露内容

#### Scenario: 未支持附件类型到达
- **WHEN** 消息包含PDF、音视频、压缩包、可执行文件、脚本、SVG或未知类型
- **THEN** 系统安全拒绝该attachment并向用户提供不泄漏内部信息的格式说明

### Requirement: 附件下载和对象写入保持幂等且不持久化短期凭证
系统 SHALL 使用内部attachment ID驱动下载和存储，以SHA-256校验对象完整性，并 MUST NOT 持久化或记录钉钉download code、临时下载URL、session webhook、access token或对象存储凭证。

#### Scenario: 相同外部事件被重投
- **WHEN** 钉钉重复投递包含同一附件的外部事件
- **THEN** 系统复用已有message、attachment和对象，不重复下载、写对象或创建Agent job

#### Scenario: 下载任务重试
- **WHEN** attachment下载在对象已经完整写入后发生确认超时并被重试
- **THEN** 系统校验已有对象SHA-256并继续状态机，不创建第二份对象

#### Scenario: 下载凭证过期
- **WHEN** 系统无法在凭证有效期内下载附件
- **THEN** attachment进入安全失败终态，凭证不落盘，并提示用户重新上传

### Requirement: 附件在隔离环境中扫描和提取
系统 SHALL 在无外部网络、受CPU/内存/时间限制的隔离处理环境中扫描并提取附件，MUST 禁止Office宏、嵌入对象、外部链接和Markdown远程资源执行。

#### Scenario: 安全文档完成提取
- **WHEN** 文档扫描通过且解析器在资源上限内完成
- **THEN** 系统保存纯文本、结构化分段索引、解析器版本、字符数和截断状态，并将attachment标记为READY

#### Scenario: 恶意或加密文档到达
- **WHEN** 扫描发现恶意内容，或文档加密、包含禁止执行内容或触发解析器限制
- **THEN** 系统停止处理、隔离或删除不安全对象、标记REJECTED并记录安全审计事件

#### Scenario: 图片处理成功
- **WHEN** 图片通过真实格式校验、像素和大小限制以及恶意内容扫描
- **THEN** 系统移除不需要的元数据并保存受控OCR或视觉提取文本；若未配置图片内容提取器则明确标记内容不可读

### Requirement: Agent job等待附件达到终态
系统 SHALL 在消息包含附件时让关联job等待所有attachment进入READY、REJECTED或FAILED终态；系统 MUST NOT 在附件仍处于下载、扫描或提取状态时启动Agent模型执行。

#### Scenario: 部分附件可用
- **WHEN** 一条消息的部分附件READY而其他附件REJECTED或FAILED，并且仍存在文本或可用提取内容
- **THEN** 系统发布Agent job，并在上下文中列出不可用附件及安全原因

#### Scenario: 没有可用输入
- **WHEN** 消息没有文本且所有附件均REJECTED或FAILED
- **THEN** 系统不调用模型，将job置为安全失败状态并通过原reply route通知用户

### Requirement: 附件内容作为不可信数据注入
系统 SHALL 将附件提取文本标识为不可信用户数据并限制长度，附件中的指令 MUST NOT 覆盖系统提示、安全规则、权限或工具策略。

#### Scenario: 文档包含提示注入文本
- **WHEN** 提取文本要求Agent忽略系统规则或调用未授权工具
- **THEN** Agent上下文将其作为引用数据处理，现有只读工具和权限策略保持不变

### Requirement: 多模态数据支持保留、删除和核对
系统 SHALL 按配置保留期管理原对象、提取文本、消息和会话，并以可重试流程标记过期、删除对象、清理或匿名化数据库内容；系统 SHALL 能识别数据库记录与对象存储之间的孤儿数据。

#### Scenario: 附件到达保留期
- **WHEN** attachment已过期且不受法律保留或管理员保留约束
- **THEN** 清理任务删除原对象和提取内容，更新数据库状态并记录不含正文的审计事件

#### Scenario: 对象删除暂时失败
- **WHEN** 对象存储删除请求发生瞬时失败
- **THEN** 数据库保持待删除状态并重试，不把记录错误标记为已删除

