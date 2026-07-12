## 1. 契约、配置与数据模型

- [ ] 1.1 收集并脱敏固化钉钉群聊、私聊、文本、图片和文件Stream payload夹具，确认稳定会话类型、机器人身份和媒体下载字段
- [x] 1.2 扩展配置及示例环境变量，加入功能开关、S3兼容存储、附件白名单/大小/结构限制、处理超时、上下文预算和保留期
- [x] 1.3 创建加法迁移，扩展agent_session/agent_message并新增message_attachment、attachment_content及必要唯一约束、状态约束和索引
- [x] 1.4 为旧session回填唯一legacy key，并验证迁移不会自动合并或破坏已有session、job和message

## 2. 稳定连续会话

- [x] 2.1 扩展会话和消息领域对象及仓储，实现群聊/私聊稳定session key、数据库原子get-or-create和session内sequence
- [x] 2.2 修改Channel ingress与job创建流程，使文本消息复用session、保持外部事件幂等并在发布队列前完成事务持久化
- [x] 2.3 实现按session和权限读取最近消息、发送人归属与滚动摘要，并定义MVP不启用缓存的ConversationCache端口
- [x] 2.4 实现ConversationSummarizer的版本/游标乐观更新和失败降级，将有界摘要与最近消息注入AgentContextBuilder

## 3. MinIO对象存储

- [x] 3.1 定义ObjectStorage端口并实现S3兼容adapter，支持按attachment ID与SHA-256幂等put/head/get/delete且不泄漏凭证
- [x] 3.2 在Docker Compose增加可选MinIO profile、显式持久卷、健康检查和幂等私有bucket初始化
- [x] 3.3 实现对象删除重试和数据库/对象存储孤儿核对，默认只报告未知对象不自动删除

## 4. 钉钉附件入口与受限提取

- [x] 4.1 将Channel message扩展为可选文本加附件描述，并保持所有现有纯文本调用路径兼容
- [x] 4.2 扩展钉钉Stream adapter归一化群聊/私聊身份及JPEG/PNG/WebP、DOCX/XLSX/PPTX/Markdown媒体，安全拒绝其他格式
- [x] 4.3 实现钉钉MediaDownloader、来源凭证短期加密落库/终态清除、流式下载、数量/大小限制、SHA-256、真实MIME和扩展名一致性校验
- [x] 4.4 实现受限AttachmentExtractor：DOCX段落/表格、XLSX只读有界单元格、PPTX幻灯片文本和Markdown纯文本，并限制解压大小、结构、字符、CPU/内存和时间
- [x] 4.5 实现JPEG/PNG/WebP格式/像素校验、去元数据和对象存储，使用stored_not_interpreted明确表示MVP不提供图片理解

## 5. 附件队列与输入闸门

- [x] 5.1 定义只携带attachment ID的RabbitMQ附件任务publisher/consumer及幂等状态机、重试和死信路径
- [x] 5.2 修改job生命周期：纯文本直接PENDING，附件消息进入WAITING_INPUT，全部附件终态且有可用输入时原子发布一次Agent job
- [x] 5.3 实现文本加不可理解图片、仅图片、部分文档成功和全部附件失败的用户可见安全结果，禁止没有可用输入时调用模型
- [x] 5.4 将READY附件文本按单附件和总预算注入AgentContextBuilder，并标记为不能覆盖系统规则的非可信用户数据

## 6. 安全、文档与端到端验证

- [x] 6.1 补齐群聊/私聊隔离、并发session、消息顺序、事件重投、摘要并发、权限拒绝和上下文截断测试
- [x] 6.2 补齐对象幂等、下载凭证加密/过期/终态清除与输出屏蔽、格式伪装、超限、加密/宏/损坏文档、图片不可理解及提示注入测试
- [x] 6.3 更新README和运维文档，说明MVP组件、支持/拒绝格式、存储分层、限制、保留、失败恢复和未来Redis/pgvector/搜索升级边界
- [ ] 6.4 运行迁移、完整测试、ruff、mypy、Compose配置、OpenSpec严格校验及MinIO/附件worker运行时烟测
- [ ] 6.5 使用真实脱敏钉钉群聊和私聊验证连续追问、附件快速ACK、WAITING_INPUT转换、原会话投递及跨范围无泄漏
