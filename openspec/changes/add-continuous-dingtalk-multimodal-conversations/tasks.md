## 1. 钉钉契约与配置基线

- [ ] 1.1 收集并脱敏保存钉钉群聊、私聊、文本、图片和文件Stream payload夹具，确认conversation type、机器人身份、媒体引用和下载凭证字段
- [ ] 1.2 扩展配置模型和示例环境变量，加入连续会话开关、对象存储、附件类型/数量/大小、处理超时、上下文预算和保留期设置
- [ ] 1.3 为群聊、私聊和各媒体payload编写adapter契约测试，先覆盖未知事件、空内容和凭证脱敏失败路径

## 2. 会话与多模态持久化模型

- [ ] 2.1 创建加法数据库迁移，为agent_session增加稳定session key、conversation type、滚动摘要游标/版本和最后消息时间
- [ ] 2.2 扩展agent_message字段并新增message_attachment、attachment_content表、外键、唯一约束、状态约束和查询索引
- [ ] 2.3 为历史session回填唯一legacy key并验证迁移不会自动合并或破坏现有会话、job和message
- [ ] 2.4 扩展领域对象和仓储，实现按群聊/私聊规则原子get-or-create session、session内sequence分配和外部消息幂等
- [ ] 2.5 实现消息、附件、提取内容、处理状态和待删除状态的仓储读写接口，并确保数据库事务失败时不发布队列消息
- [ ] 2.6 增加数据库迁移、并发session解析、消息顺序、重复事件和跨project/connector隔离测试

## 3. 对象存储与本地运行环境

- [ ] 3.1 定义ObjectStorage应用端口及私有bucket对象模型，实现按attachment ID和内容散列幂等put/head/get/delete
- [ ] 3.2 实现可配置S3兼容adapter，确保日志、异常和健康输出不包含access key、secret、预签名URL或对象正文
- [ ] 3.3 在Docker Compose增加本地MinIO、持久卷、健康检查和幂等bucket初始化，并通过profile避免影响不需要附件能力的基础运行
- [ ] 3.4 增加对象完整性、重复写、瞬时失败、删除重试和孤儿对象识别测试

## 4. Channel与钉钉多模态入口

- [ ] 4.1 将Channel event从单文本扩展为可选文本加附件描述，并保持现有文本调用方的向后兼容
- [ ] 4.2 扩展钉钉Stream解析器，归一化群聊/私聊身份、发送人、机器人身份、外部消息ID及图片/文件媒体描述
- [ ] 4.3 实现钉钉MediaDownloader授权客户端和短期凭证作用域，确保download code、临时URL、token和session webhook不落库、不进队列、不进日志
- [ ] 4.4 修改Channel ingress和job创建流程，原子解析session并持久化message/attachment；纯文本job直接PENDING，附件job进入WAITING_INPUT
- [ ] 4.5 保持Stream快速ACK、事件幂等和原reply route，补齐群聊、私聊、附件重投和下载凭证过期测试

## 5. 附件安全处理流水线

- [ ] 5.1 定义MediaDownloader、MalwareScanner和AttachmentExtractor端口以及PENDING到READY/REJECTED/FAILED状态机
- [ ] 5.2 实现流式下载、数量/大小限制、SHA-256、libmagic真实MIME探测和扩展名一致性校验，避免完整大文件驻留内存
- [ ] 5.3 集成恶意内容扫描，并对超限、类型伪装、加密文档、宏、嵌入对象、压缩炸弹和扫描失败产生稳定安全错误码
- [ ] 5.4 构建无外部网络且受CPU、内存、文件和时间限制的Office/Markdown提取运行时，支持DOC/DOCX、XLS/XLSX、PPT/PPTX和纯文本Markdown
- [ ] 5.5 实现图片真实格式/像素校验、元数据移除和受控OCR或视觉文本提取；未配置提取器时保存对象并明确标记内容不可读
- [ ] 5.6 将提取结果按页、工作表或幻灯片分段保存，实施行列/字符上限并记录解析器版本和截断状态
- [ ] 5.7 实现附件任务幂等重试、对象/数据库状态补偿和终态审计，确保不产生重复对象或重复提取内容
- [ ] 5.8 使用安全、恶意、超限、损坏、加密和提示注入夹具覆盖所有支持格式及失败状态测试

## 6. 附件队列与Agent输入闸门

- [ ] 6.1 定义只包含attachment ID和追踪标识的附件任务publisher/consumer，并配置独立正常、重试和死信路径
- [ ] 6.2 实现附件协调服务：全部附件终态且存在可用输入时原子将WAITING_INPUT转为PENDING并只发布一次Agent job
- [ ] 6.3 实现没有可用文本或附件内容时的安全失败与结果投递，不调用Claude运行时
- [ ] 6.4 增加并发附件完成、重复队列投递、部分成功、全部失败、超时和worker重启恢复测试

## 7. 连续会话上下文与滚动摘要

- [ ] 7.1 实现按session、权限和sequence读取最近用户/助手消息、发送人归属及READY附件提取片段的查询服务
- [ ] 7.2 定义ConversationSummarizer端口并实现摘要版本、summary-through-sequence和乐观并发更新，失败时退化为最近消息窗口
- [ ] 7.3 修改AgentContextBuilder，将滚动摘要、最近消息和有界附件片段注入conversation context，同时保留现有ER、业务流和schema上下文
- [ ] 7.4 对消息数、单附件字符数和总上下文预算实施确定性裁剪，优先保留当前问题与最近消息并暴露截断标记
- [ ] 7.5 在系统提示中将聊天和附件内容标记为不可信数据，验证其中的提示注入不能改变只读工具、权限和安全规则
- [ ] 7.6 增加连续追问、群内多发送人、私聊隔离、跨群/项目泄漏、摘要并发和超预算上下文测试

## 8. 生命周期、安全与可观测性

- [ ] 8.1 实现原对象、提取文本、消息和会话的可配置保留状态机及清理任务，支持对象删除失败后的幂等重试
- [ ] 8.2 实现数据库/对象存储一致性核对和孤儿数据报告，默认只报告而不自动删除未知对象
- [ ] 8.3 增加session命中/创建、下载、校验、扫描、提取、拒绝、上下文读取、过期和删除审计事件，并验证不记录正文、二进制和凭证
- [ ] 8.4 扩展ready/health状态，报告对象存储、扫描器和提取器是否配置/可用但不执行真实附件处理或泄漏密钥
- [ ] 8.5 完成权限、保留、删除、凭证屏蔽、审计摘要和对象bucket私有性测试

## 9. 文档与端到端验证

- [ ] 9.1 更新README和运维文档，说明群聊/私聊会话边界、支持格式、存储分层、限制、保留、失败恢复和本地启动命令
- [ ] 9.2 运行数据库迁移、单元/集成测试、ruff、mypy、compose config和OpenSpec严格校验
- [ ] 9.3 使用本地MinIO和附件处理服务完成文本、图片、DOC/DOCX、XLS/XLSX、PPT/PPTX、Markdown的对象写入与提取烟测
- [ ] 9.4 使用真实脱敏钉钉群聊连续追问验证session复用、发送人顺序、附件ACK、WAITING_INPUT到SUCCEEDED及原群投递
- [ ] 9.5 使用真实脱敏钉钉私聊连续追问验证按用户隔离、附件上下文、重复事件幂等和原私聊投递
- [ ] 9.6 验证跨群、跨私聊、跨project和跨connector无法读取聊天或附件，并记录最终运行证据与未完成限制
