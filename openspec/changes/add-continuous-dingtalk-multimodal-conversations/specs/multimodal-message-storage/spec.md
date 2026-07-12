## ADDED Requirements

### Requirement: 系统分层保存MVP多模态消息
系统 SHALL 在PostgreSQL保存消息正文、附件元数据、状态和有界提取文本，并在私有S3兼容对象存储保存原始二进制。原始二进制 MUST NOT 写入PostgreSQL、RabbitMQ、日志或审计payload。

#### Scenario: 文本和文档一起到达
- **WHEN** 消息包含文本和一个受支持文档
- **THEN** 系统保存一条user message、一条attachment记录并把原文件写入私有bucket

#### Scenario: 仅图片到达
- **WHEN** 消息没有文本但包含受支持图片
- **THEN** 系统保存消息和图片对象，并明确标记MVP不提供图片内容理解

### Requirement: MVP只接受现代白名单格式
系统 SHALL 支持JPEG、PNG、WebP、DOCX、XLSX、PPTX和Markdown，并 MUST 根据真实内容探测MIME、校验扩展名、数量、文件大小、解压后大小及结构上限。系统 MUST 拒绝DOC、XLS、PPT及其他未支持格式。

#### Scenario: 现代Office附件通过校验
- **WHEN** DOCX、XLSX或PPTX的扩展名、MIME、大小和结构符合策略
- **THEN** 系统保存对象并进入受限文本提取

#### Scenario: 类型伪装或超限
- **WHEN** 扩展名与真实MIME冲突，或附件数量、大小、解压后大小、行列或幻灯片超过策略
- **THEN** 系统将attachment标记为REJECTED并保存安全错误码

#### Scenario: 旧版Office或其他格式到达
- **WHEN** 消息包含DOC、XLS、PPT、PDF、压缩包、音视频、SVG、脚本、可执行文件或未知格式
- **THEN** 系统不解析内容并返回不泄漏内部信息的格式说明

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
系统 SHALL 使用非root、无外网、受CPU/内存/时间限制的worker提取DOCX段落/表格、XLSX工作表有界单元格、PPTX幻灯片文本和Markdown纯文本，MUST NOT执行公式、宏、嵌入对象、HTML或远程资源。

#### Scenario: 文档提取成功
- **WHEN** 受支持文档在资源上限内完成解析
- **THEN** 系统保存有界纯文本、分段信息、解析器版本和截断状态并标记READY

#### Scenario: 加密、宏格式或损坏文档
- **WHEN** 文档加密、属于宏格式、包含禁止结构、损坏或触发资源限制
- **THEN** 系统停止处理并标记REJECTED或FAILED，不向Agent暴露内容

### Requirement: 图片只安全存储而不宣称可理解
系统 SHALL 对JPEG、PNG和WebP执行真实格式、文件大小和像素限制校验，去除不需要的元数据后保存对象；MVP MUST NOT生成虚构OCR、视觉描述或把图片内容注入Agent。

#### Scenario: 图片通过校验
- **WHEN** 图片真实格式、大小和像素符合策略
- **THEN** 系统保存规范化对象并将内容能力标记为stored_not_interpreted

#### Scenario: 文本加图片消息执行
- **WHEN** 消息包含可用文本和一张已存储但不可理解的图片
- **THEN** Agent使用文本执行并明确图片未作为诊断证据

#### Scenario: 仅图片消息完成处理
- **WHEN** 消息只有已存储图片且没有可用文本
- **THEN** 系统不调用模型并通过原reply route说明MVP暂不支持图片理解

### Requirement: Agent job等待附件达到终态
系统 SHALL 让包含附件的job等待所有attachment进入READY、REJECTED、FAILED或stored_not_interpreted终态，MUST NOT 在下载或提取中启动模型。

#### Scenario: 部分文档可用
- **WHEN** 部分附件READY且仍存在文本或可用提取内容
- **THEN** 系统发布job并在上下文列出不可用附件的安全状态

#### Scenario: 没有可用输入
- **WHEN** 没有文本且所有附件均不可理解、REJECTED或FAILED
- **THEN** 系统不调用模型并安全结束job

### Requirement: 附件内容作为不可信数据注入
系统 SHALL 将提取文本标识为不可信用户数据并限制长度，其中的指令 MUST NOT覆盖系统提示、安全规则、权限或工具策略。

#### Scenario: 文档包含提示注入
- **WHEN** 提取文本要求Agent忽略系统规则或调用未授权工具
- **THEN** Agent将其作为引用数据处理且只读工具和权限策略保持不变

### Requirement: 多模态数据支持可重试删除和孤儿核对
系统 SHALL 按配置保留期标记并删除原对象与提取内容，删除过程 MUST 可重试；一致性核对默认只报告未知孤儿对象而不自动删除。

#### Scenario: 对象删除暂时失败
- **WHEN** 对象存储删除发生瞬时失败
- **THEN** 数据库保持待删除状态并重试，不错误标记为已删除

#### Scenario: 发现未知孤儿对象
- **WHEN** 私有bucket中的对象没有对应数据库记录
- **THEN** 系统生成安全报告且不自动删除对象
