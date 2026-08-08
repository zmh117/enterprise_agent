## Why

当前钉钉Stream入口只接受文本，并且每条消息都会创建新的Agent session，导致群聊和私聊无法延续上下文，附件也不能作为可审计消息保存。长期记忆建设前先交付一个组件少、边界清晰的连续对话MVP，并通过端口抽象保留缓存、向量检索、全文搜索和复杂文档处理的升级空间。

## What Changes

- 为钉钉群聊和私聊生成稳定、隔离的会话键：群聊按connector、project和群conversation复用session；私聊按connector、project、用户和机器人身份复用session。
- 扩展Channel event和钉钉Stream解析，接收文本、JPEG/PNG/WebP图片以及DOCX、XLSX、PPTX、Markdown附件；首期明确拒绝旧版DOC/XLS/PPT及其他未支持格式。
- 使用PostgreSQL保存session、消息、附件元数据、处理状态、提取文本和滚动摘要；使用私有S3兼容对象存储保存原始二进制，本地Compose提供MinIO。
- 使用RabbitMQ异步处理附件，job在 `WAITING_INPUT` 等待输入就绪；队列只传内部ID。下载凭证使用平台主密钥短期加密落库，下载完成或过期后清除，明文、二进制、临时URL和token不得进入队列、日志、审计或调试接口。
- 使用受限Python解析器提取DOCX、XLSX、PPTX和Markdown文本；图片首期只做安全校验、去除元数据和存储，不承诺OCR或视觉理解。
- Agent上下文由PostgreSQL中的滚动摘要、最近消息和有界附件文本组成；首期不引入Agent专用Redis、pgvector、Qdrant、OpenSearch、Weaviate、Tika、LibreOffice或ClamAV。
- 为会话隔离、消息/附件幂等、对象存储、附件状态、上下文读取和失败投递建立安全审计及端到端验证。

## Capabilities

### New Capabilities

- `continuous-agent-conversation`: 定义钉钉群聊和私聊的稳定会话身份、消息顺序、会话复用、滚动摘要、上下文预算和隔离规则。
- `multimodal-message-storage`: 定义MVP支持的图片、现代Office和Markdown附件的PostgreSQL元数据、MinIO对象存储、受限提取、状态和删除语义。

### Modified Capabilities

- `channel-ingress-contract`: 将归一化Channel event从单一文本扩展为可选文本加附件描述，并约束附件入站幂等与凭证安全。
- `dingtalk-agent-ingress`: 增加群聊/私聊识别、MVP媒体类型解析、异步下载和快速确认语义。
- `agent-job-lifecycle`: 从每次请求新建session改为解析或复用稳定session，并增加附件输入等待状态。

## Impact

- 影响钉钉Stream adapter、通用Channel event、Agent job创建服务、会话/消息仓储、上下文构建器、worker和审计服务。
- 新增加法数据库迁移、对象存储端口与S3兼容实现、受限附件提取模块和附件RabbitMQ任务。
- Docker Compose和环境配置增加可选MinIO profile、私有bucket初始化以及附件/上下文限制。
- 预留 `ConversationCache`、`AttachmentExtractor`、`MalwareScanner`、`EmbeddingProvider`、`MemoryRepository` 和 `MemoryRetrievalIndex` 边界，但本次仅实现MVP实际需要的端口。
