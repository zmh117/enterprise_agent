## Context

当前钉钉 Stream adapter 只从 payload 提取文本，`ChannelEvent.message` 也是单字符串；`CreateAgentJobService` 对每个外部事件调用 `create_session()`，所以相同群聊或私聊的后续问题落入不同 session。`agent_message` 只保存 role/content，`AgentContextBuilder` 将会话摘要固定为“仅使用当前问题”。现有 PostgreSQL 已保存 session、message、job、工具调用和审计，是会话控制面的事实来源，但没有附件对象存储、媒体处理队列或会话读取模型。

本变更涉及外部钉钉媒体下载、数据库模型、对象存储、异步处理、Agent上下文和数据安全。参与方包括钉钉用户、群成员、Agent API/worker、平台管理员及对象存储运维方。

## Goals / Non-Goals

**Goals:**

- 让同一钉钉群聊或私聊在明确隔离键下复用稳定 Agent session，并保留发送人和消息顺序。
- 支持文本、常见图片、DOC/DOCX、XLS/XLSX、PPT/PPTX和Markdown消息附件。
- 采用“PostgreSQL元数据与可检索文本 + S3兼容对象存储原文件”的分层存储。
- 在不阻塞钉钉快速ACK的前提下完成附件下载、扫描、解析和Agent job调度。
- 为Agent提供有界、可追溯、不会跨群或跨私聊泄漏的连续对话上下文。
- 支持幂等、保留期、删除、失败恢复、审计和本地Docker验证。

**Non-Goals:**

- 本变更不建设跨会话长期记忆、Embedding或向量检索。
- 不支持音频、视频、压缩包、PDF、可执行文件、脚本、SVG或任意未知格式。
- 不让Agent修改、覆盖或向钉钉回传用户附件。
- 不执行Office宏、公式、外部链接、嵌入对象或Markdown中的远程内容。
- 不自动合并历史上已经被拆分的旧session；旧记录保留可读，新消息使用新会话键。

## Decisions

### 1. 会话身份由服务端生成稳定键

新增归一化的 `conversation_type=group|direct` 和不可逆 `session_key`：

- 群聊键输入：`source_channel + source_connector_id + project_code + group + external_conversation_id`。
- 私聊键输入：`source_channel + source_connector_id + project_code + direct + requester_id + bot_identity`；外部conversation ID作为来源元数据保存，但不单独决定私聊归属。

数据库对 `session_key` 建唯一约束，并使用原子 get-or-create。群聊中不同发送人共享同一session，但每条消息保存独立sender；私聊始终按用户隔离。选择服务端键而不是直接复用钉钉ID，是为了防止不同connector、项目或会话类型出现相同外部ID时串线。

### 2. 扩展通用Channel消息信封

将单字符串消息扩展为规范化消息：文本正文可为空，附件列表可为空，但二者不能同时为空。附件描述只包含稳定媒体类型、显示文件名、声明大小/MIME和供adapter立即换取文件的短期来源句柄。短期下载URL、download code、session webhook和token只在内存中流转，不写数据库、队列或日志。

RabbitMQ Agent job消息仍只包含 `job_id` 和 `correlation_id`。附件处理使用独立的内部任务消息，只传 `attachment_id`，不传外部凭证或二进制。

### 3. PostgreSQL与对象存储分层

数据库采用加法迁移：

- `agent_session` 增加 `session_key`、`conversation_type`、`summary_text`、`summary_through_sequence`、`summary_version`、`last_message_at`。
- `agent_message` 增加 `external_message_id`、`sender_id`、`sender_display_name`、`message_type`、`sequence_no`、`content_status`、`safe_metadata_json`，并保留现有 `content` 兼容字段。
- 新增 `message_attachment`，保存message归属、文件名、声明/探测MIME、大小、SHA-256、对象bucket/key、扫描与提取状态、失败码、提取文本引用、创建/完成/过期时间。
- 大段提取文本保存到独立 `attachment_content`，包含纯文本、页/工作表/幻灯片等分段索引、解析器版本、字符数及截断标记。

原始二进制进入私有S3兼容bucket，不进入PostgreSQL、RabbitMQ或审计payload。对象key使用内部attachment ID和内容散列，不使用用户文件名。生产可以接入企业对象存储；本地Compose提供MinIO及幂等bucket初始化。

相较把二进制写入PostgreSQL，此方案避免数据库膨胀和备份阻塞；相较只保存钉钉临时URL，此方案不依赖会过期的外部下载凭证。

### 4. 附件异步处理并对Agent job设置输入闸门

入口先完成认证、幂等检查、session解析、message/attachment元数据持久化并返回ACK。包含附件的job进入 `WAITING_INPUT`，附件任务执行以下状态机：

`PENDING -> DOWNLOADING -> STORED -> SCANNING -> EXTRACTING -> READY`，失败终态为 `REJECTED` 或 `FAILED`。

所有附件到达终态后：

- 有文本或至少一个READY附件时，job转为 `PENDING` 并发布到现有Agent队列；上下文明确列出不可用附件。
- 没有任何可用输入时，job以安全原因失败并走现有结果投递，不调用模型。

下载和处理按attachment ID幂等；重试必须校验已有对象SHA-256，不能制造重复对象或重复Agent job。相比在Stream回调里同步下载和解析，该方案保留快速ACK并隔离大文件失败。

### 5. 内容安全与解析工具采用隔离端口

定义 `ObjectStorage`、`MediaDownloader`、`MalwareScanner`、`AttachmentExtractor` 应用端口。建议S3实现使用兼容客户端；Office解析通过无网络、只读根文件系统、受CPU/内存/超时限制的Apache Tika/LibreOffice提取容器；图片先用libmagic/Pillow验证并重编码去除元数据，再由受控OCR/视觉提取器生成文本；Markdown按受限字符集读取为纯文本，不渲染HTML或请求远程资源。

默认策略可配置，初始建议为单文件25 MiB、单消息100 MiB、最多10个附件，以及页数、工作表行列、幻灯片数和提取字符数上限。以探测MIME为准，扩展名与MIME不一致、加密文档、宏/嵌入对象、恶意软件、压缩炸弹或超限内容进入REJECTED。实现前应通过真实钉钉payload夹具确认各媒体类型的下载句柄字段。

### 6. 连续上下文由最近原文加滚动摘要组成

`AgentContextBuilder` 按当前job的session读取：滚动摘要、摘要游标之后的最近消息、每条消息可用的附件提取片段。群聊消息必须带发送人标签；私聊不暴露其他用户内容。上下文先按范围和权限过滤，再按配置的消息数、单附件字符数和总token/字符预算截断。

当未摘要消息超过阈值时，通过可替换的 `ConversationSummarizer` 生成新摘要，并以乐观版本和 `summary_through_sequence` 原子推进；摘要失败不阻塞当前job，退化为最近消息窗口。附件内容被明确标记为“不可信用户数据”，不能覆盖系统提示、安全规则或工具策略。

### 7. 生命周期、访问和审计

原文件、提取文本、消息和会话分别使用可配置保留期；默认不做硬编码业务承诺。清理任务先标记过期，再删除对象，最后清除/匿名化数据库内容，过程可重试。对象bucket保持私有；Agent只接收经过权限过滤的提取文本，不接收对象URL或存储凭证。

记录session命中/创建、附件下载、校验、扫描、提取、拒绝、上下文读取、过期和删除事件，但审计只保存ID、大小、类型、散列前缀和安全错误码，不保存正文、二进制、token或临时URL。

## Risks / Trade-offs

- [钉钉群聊/私聊payload字段因消息类型或SDK版本不同] → 收集真实脱敏payload夹具，adapter内集中做版本兼容和契约测试，未知类型安全忽略。
- [并发消息创建重复session或顺序错乱] → session_key唯一约束、数据库原子upsert、session内单调sequence及并发测试。
- [附件下载凭证在异步处理前过期] → 入口在凭证有效窗口内启动受控下载任务；只在内存/短寿命加密任务上下文使用凭证，超时向用户明确报告重新上传。
- [恶意Office或图片攻击解析器] → MIME探测、恶意软件扫描、隔离容器、无网络、资源上限、禁止宏和嵌入对象。
- [长聊天和大表格挤爆模型上下文] → 分段提取、行列/字符上限、滚动摘要、总预算和截断标志。
- [对象与数据库状态不一致] → 状态机、内容散列、幂等补偿和周期性孤儿对象核对。
- [群聊上下文包含其他成员敏感信息] → 会话级权限策略、发送人归属、项目/connector隔离、可配置保留和删除审计。
- [增加MinIO、扫描和提取服务提高运维成本] → 全部通过端口抽象；本地使用Compose，生产允许接企业S3和已有扫描/提取服务。

## Migration Plan

1. 先部署对象存储、私有bucket、扫描/提取服务及健康检查，功能开关保持关闭。
2. 执行加法数据库迁移；为旧session生成唯一legacy key，不尝试把历史会话自动合并。
3. 部署支持新字段但仍按旧文本路径运行的API和worker，验证向后兼容。
4. 启用附件下载/存储/提取，先观察模式记录状态但不注入Agent上下文。
5. 启用稳定session复用和连续上下文，按connector灰度群聊与私聊。
6. 运行真实钉钉文本、图片和各文档格式端到端测试，再扩大范围。

回滚时关闭多模态和连续会话开关，停止新附件任务并恢复每请求新session；保留加法表列和已存对象，待确认无在途任务后按保留策略清理，不执行破坏性降级迁移。

## Open Questions

- 生产环境使用现有企业S3兼容对象存储还是由本项目维护独立bucket，以及对应KMS/备份策略。
- 原文件、提取文本和聊天消息的正式保留天数、法律保留及用户删除SLA。
- 图片首期必须提供OCR/视觉描述，还是允许先完成安全存储并向Agent标记“图片内容尚不可读”。
- 钉钉实际群聊、私聊、图片和文件Stream payload中的稳定会话类型及媒体下载字段，需要在实现任务开始时用脱敏真实样本锁定。
