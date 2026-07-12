## Why

当前钉钉 Stream 入口只接受文本，并且每条消息都会创建新的 Agent session，导致群聊和私聊无法延续上下文，图片及 Office、Markdown 文档也无法成为可审计的诊断输入。长期记忆建设前必须先建立稳定会话身份、多模态消息存储和受控附件解析，使 Agent 能在权限边界内读取真实连续对话。

## What Changes

- 为钉钉群聊和私聊定义稳定、隔离的会话身份：群聊按 connector、群 conversation、project 复用会话；私聊按 connector、稳定参与方身份、project 复用会话，禁止群与私聊串线。
- 扩展 Channel event 和钉钉 Stream 解析，接收文本、图片、DOC/DOCX、XLS/XLSX、PPT/PPTX、Markdown 附件，并保留外部消息、发送人、会话类型和附件引用。
- 将消息正文、会话身份、附件元数据、处理状态、提取文本和安全摘要存入 PostgreSQL；将图片和文档原始二进制存入可配置的 S3 兼容对象存储，数据库不保存大对象。
- 增加附件下载、类型探测、大小限制、校验和、恶意内容防护、文本提取、失败隔离、保留期和删除语义；短期下载凭证、session webhook 和外部临时 URL 不得持久化。
- 构建有界会话上下文：读取最近消息与已成功提取的附件内容，按字符/token预算生成滚动摘要并注入 Agent；附件未就绪或处理失败时明确向用户说明，不伪造内容。
- 为会话复用、消息幂等、附件对象、解析过程、上下文读取和删除记录安全审计事件，并保持 RabbitMQ job payload 只携带内部标识。

## Capabilities

### New Capabilities

- `continuous-agent-conversation`: 定义钉钉群聊和私聊的稳定会话身份、消息顺序、会话复用、滚动摘要、上下文预算和隔离规则。
- `multimodal-message-storage`: 定义文本、图片及 Office/Markdown 附件的元数据与对象存储分层、下载校验、解析状态、访问控制、保留和删除语义。

### Modified Capabilities

- `channel-ingress-contract`: 将归一化 Channel event 从单一文本扩展为消息正文加附件描述，并约束附件入站幂等与安全字段。
- `dingtalk-agent-ingress`: 增加钉钉群聊/私聊类型识别、支持的图片和文件消息解析、媒体下载及安全确认语义。
- `agent-job-lifecycle`: 从每次请求新建会话改为解析或复用稳定会话，并在发布 job 前持久化多模态用户消息与附件记录。

## Impact

- 影响钉钉 Stream adapter、通用 Channel event、Agent job 创建服务、会话/消息仓储、上下文构建器、Worker和审计服务。
- 需要新增数据库迁移、对象存储端口与 S3 兼容实现、附件提取 worker/队列、内容类型探测与 Office/Markdown/图片处理依赖。
- Docker Compose 和环境配置需要提供本地对象存储、bucket初始化、附件大小/类型/保留期和上下文预算配置；生产环境可替换为企业现有 S3 兼容服务。
- 调试 API 和测试夹具需要支持构造群聊、私聊、重复事件、附件处理成功/失败以及会话上下文读取场景。
