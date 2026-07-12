## Context

当前`DingTalkStreamMessageService`只产生字符串消息，`CreateAgentJobService`每次调用`create_session()`，`AgentContextBuilder`也明确只使用当前问题。项目已经使用PostgreSQL 18作为事务事实库、RabbitMQ 4作为异步通道并通过Loki查询日志；测试用Redis属于基地业务数据源，不能复用为Agent缓存。

原方案同时引入MinIO、Tika/LibreOffice、ClamAV、OCR/视觉服务、复杂保留治理和47项任务，超过连续对话MVP的必要范围。本设计保留真实群聊/私聊连续性与附件存储，但把外部组件控制在PostgreSQL、RabbitMQ和MinIO，并通过应用端口保留后续替换能力。

## Goals / Non-Goals

**Goals:**

- 同一钉钉群聊或私聊稳定复用session，消息有序、带发送人且不跨范围泄漏。
- PostgreSQL持久化文本、附件元数据、提取文本和滚动摘要，MinIO保存附件原文件。
- 支持JPEG/PNG/WebP安全存储以及DOCX/XLSX/PPTX/Markdown的有界文本提取。
- 附件异步处理不阻塞Stream ACK，Agent只在输入到达终态后执行。
- 使用端口隔离对象存储、附件提取、摘要和未来记忆检索实现。

**Non-Goals:**

- 不建设跨session长期记忆、Embedding或向量/全文检索索引。
- 不增加Agent专用Redis/Valkey、Qdrant、OpenSearch、Weaviate或Elasticsearch。
- 不支持DOC/XLS/PPT旧格式、PDF、压缩包、音视频、SVG、脚本或可执行文件。
- 不部署Tika、LibreOffice、ClamAV、OCR或视觉模型；图片首期可保存但不作为可理解文本注入Agent。
- 不自动合并历史已拆分session，也不实现附件回传、在线预览或编辑。

## Decisions

### 1. PostgreSQL是会话唯一事实源，MVP不使用Redis缓存

群聊session key由`source_channel + connector_id + project_code + group + external_conversation_id`生成；私聊key由`source_channel + connector_id + project_code + direct + requester_id + bot_identity`生成。数据库唯一约束与原子get-or-create处理并发，session内sequence保证消息顺序。

滚动摘要、摘要游标和最近消息均从PostgreSQL读取。应用层定义`ConversationRepository`和`ConversationCache`边界，但MVP使用`NoConversationCache`，避免缓存成为一致性前提。未来只有在测量到重复读取负载或需要分布式限流、流式状态时才接入独立Redis/Valkey。

### 2. 通用Channel信封支持可选文本和附件

规范化消息包含可选文本、发送人、会话类型和附件列表，文本与附件不能同时为空。为兼顾快速ACK与可恢复异步下载，download code或等价媒体来源凭证使用现有`APP_CONFIG_MASTER_KEY`短期加密后保存到attachment记录，附带凭证类型和过期时间；下载完成、拒绝、失败或过期后立即清除密文。明文凭证、临时URL、token和session webhook不进入数据库、RabbitMQ、日志、审计或调试接口。

同一外部事件只创建一条message、若干attachment和一个job。Agent队列继续只传`job_id/correlation_id`，附件队列只传`attachment_id/correlation_id`。

### 3. PostgreSQL保存元数据，MinIO保存原文件

加法迁移扩展：

- `agent_session`：`session_key`、`conversation_type`、`summary_text`、`summary_through_sequence`、`summary_version`、`last_message_at`。
- `agent_message`：外部消息ID、发送人、消息类型、sequence、内容状态和安全元数据。
- `message_attachment`：文件名、声明/探测MIME、大小、SHA-256、bucket/key、处理状态、失败码、短期加密来源凭证/类型/过期时间和处理时间戳；所有终态清除凭证密文。
- `attachment_content`：有界纯文本、分段信息、解析器版本、字符数和截断标记。

对象key使用内部attachment ID和散列，不使用用户文件名。bucket保持私有，Agent只读取数据库中的安全提取文本。定义`ObjectStorage`端口，MVP实现S3兼容adapter和本地MinIO；生产可以无业务改动地替换企业S3。

### 4. MVP只解析现代、安全边界较清楚的格式

使用受限Python worker：

- DOCX：提取段落和表格文本。
- XLSX：只读、`data_only`方式按工作表和行列上限提取，不计算公式。
- PPTX：按幻灯片提取文本形状内容。
- Markdown：按纯文本读取，不渲染HTML、不加载远程资源。
- JPEG/PNG/WebP：使用真实格式、大小和像素限制校验，重编码去除元数据后存储；首期不生成OCR/视觉描述。

所有格式执行扩展名/MIME一致性、数量、文件大小、解压后大小、页/行列/幻灯片和字符上限。宏格式、加密文档、嵌入对象、类型伪装和超限内容拒绝。worker使用非root、无外网、只读根文件系统、临时目录和CPU/内存/超时限制。

定义`AttachmentExtractor`和`MalwareScanner`端口，但MVP不以空扫描器伪装为“已扫描”；状态和审计只陈述已执行的格式校验/解析隔离。未来生产要求恶意软件扫描或旧Office支持时，再接入ClamAV和Tika/LibreOffice。

### 5. 附件使用WAITING_INPUT输入闸门

入口原子保存session、message、attachment和job后快速ACK。纯文本job直接PENDING；包含附件的job进入WAITING_INPUT。attachment状态为`PENDING -> DOWNLOADING -> STORED -> EXTRACTING -> READY`，失败终态为`REJECTED/FAILED`。

所有附件到达终态后：

- 有文本或至少一个可用附件文本：job原子转PENDING并只发布一次。
- 只有图片而没有文本：保留图片记录，但安全结束job并说明MVP暂不理解图片。
- 文本加图片：使用文本执行，并明确图片未作为理解证据。
- 全部附件失败且无文本：不调用模型，走现有安全失败投递。

下载、对象写入、提取和job释放均按内部ID幂等。

### 6. 连续上下文使用滚动摘要加最近消息

`AgentContextBuilder`读取当前session的摘要、摘要游标后的最近消息和READY文本附件片段。群消息带发送人标签；上下文先做session/project/connector/请求人权限过滤，再按最近消息数、单附件字符数和总字符/token预算裁剪。

定义`ConversationSummarizer`端口，以摘要版本和`summary_through_sequence`乐观更新。摘要失败时退化为最近消息窗口，不阻塞当前job。历史消息和附件都标记为不可信用户数据，不能改变系统安全规则或工具权限。

### 7. 为长期记忆与检索预留端口但不提前部署

未来长期记忆通过`MemoryRepository`保存PostgreSQL事实，通过`EmbeddingProvider`生成向量，通过`MemoryRetrievalIndex`检索。MVP不创建memory表、不安装pgvector，也不创建空Qdrant/OpenSearch集成。应用模块不得把MinIO、未来Redis或检索引擎SDK类型泄漏到领域/应用层。

升级顺序固定为：连续会话MVP → PostgreSQL长期记忆与pgvector → 有测量依据时增加Redis/Valkey、Qdrant或OpenSearch。

## Risks / Trade-offs

- [真实钉钉payload字段与夹具不同] → 实施第一步收集脱敏群聊、私聊和媒体payload，集中在adapter做兼容。
- [不使用Redis导致PostgreSQL读取增加] → 先测量上下文读取延迟；端口已经允许后续加入缓存，但PostgreSQL始终是事实源。
- [不部署ClamAV仍存在恶意文件风险] → 只允许严格白名单格式、隔离解析、资源限制且不提供用户下载；生产开放下载或扩展格式前必须另行接入扫描。
- [图片首期不能参与诊断] → 明确用户提示和状态，不让模型猜测；OCR/视觉理解作为独立后续能力。
- [大工作簿或演示文稿耗尽资源] → 流式/只读解析、解压大小和结构上限、worker隔离、超时和文本截断。
- [对象与数据库状态不一致] → 状态机、SHA-256、幂等补偿和只报告不自动删除的孤儿核对。

## Migration Plan

1. 执行加法数据库迁移并为旧session生成唯一legacy key，不自动合并历史。
2. 部署MinIO profile、私有bucket初始化和对象存储健康检查，连续会话/附件开关保持关闭。
3. 部署兼容旧文本路径的新API和worker，先启用session复用与文本连续上下文。
4. 启用现代文档和图片存储、异步提取及WAITING_INPUT闸门。
5. 用真实脱敏群聊、私聊和各MVP附件完成端到端验证后再默认启用。

回滚通过功能开关恢复每请求新session并停止新附件任务；保留加法列、表和对象，确认无在途任务后按文档清理，不执行破坏性降级迁移。

## Open Questions

- 生产环境最终使用企业S3兼容存储还是独立MinIO，以及对应备份、加密和保留策略。
- 聊天消息、附件原文件和提取文本的正式保留天数。
- 真实钉钉群聊、私聊、图片和文件Stream payload中的稳定会话类型及媒体下载字段，需要在apply的第一项任务中用脱敏样本确认。
