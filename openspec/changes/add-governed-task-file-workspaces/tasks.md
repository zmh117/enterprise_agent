## 1. 兼容性切片与契约冻结

- [x] 1.1 为现有附件队列声明、消息字段、来源幂等键、重试和等待 Job 释放行为补充契约测试，记录 `attachment-worker` 的 Confirmed-current 基线
- [x] 1.2 在 TypeScript Runtime 中完成 File MCP 控制结果触发本地下载、提交意图触发流式上传的最小兼容性切片，证明完整文件不会进入模型或 MCP JSON
- [x] 1.3 在 Python Runtime 中完成与 TypeScript 等价的文件传输兼容性切片，固定跨 Runtime 的逻辑句柄和错误语义
- [x] 1.4 使用合成 15 MiB TXT、输入输出副本和 100 MiB 工作区配额做沙盒容量基准，确定可配置 tmpfs 默认值、安全余量和 readiness 下限
- [x] 1.5 冻结 File MCP Tool Manifest、内部流式 API、附件队列扩展字段和稳定错误码，并增加拒绝任意 URL、路径、对象键和动态 Tool 的 schema 测试

## 2. 数据库 Expand Migration 与领域模型

- [x] 2.1 创建下一条前向 migration，增加 `task_workspace` 及同一 Session 最多一个 ACTIVE 工作区的数据库约束和索引
- [x] 2.2 在 migration 中增加稳定文件、不可变文件版本、工作区文件引用和外部来源引用表，并建立租户、归属、当前版本和软删除约束
- [x] 2.3 在 migration 中增加 Job File Manifest 头与不可变清单项表，并建立 Job、Workspace、File、Version 和允许动作的外键与唯一约束
- [x] 2.4 在 migration 中增加 File Commit Intent、对象 staging、冲突候选、保留事实和待清理事实表，并建立严格幂等与状态约束
- [x] 2.5 扩展 Business Application revision/publication snapshot schema，加入 `task_workspace_retention_period`，并为旧 Publication 提供稳定 `WEEK` 兼容解析
- [x] 2.6 为现有聊天附件增加内部 File/Version 兼容关联和到期事实，按原始创建时间加默认 360 天回填但不在 migration 中访问或删除 MinIO 对象
- [x] 2.7 为全部新增表实现仓库、事务映射和领域状态枚举，增加 migration 前进、重复执行保护、约束和回滚边界测试

## 3. Business Application 配置与发布治理

- [x] 3.1 在 Business Application 草稿 API 中实现 `DAY`、`WEEK`、`MONTH` 严格校验、新草稿默认 `WEEK` 和未知字段拒绝
- [x] 3.2 在 Publication 构建、canonical snapshot、schema version、hash、Resolver 和审计中冻结工作区保留策略
- [x] 3.3 实现 Asia/Shanghai 自然日、自然周和自然月到期计算器，覆盖月末、年末和活动不滚动延期测试
- [x] 3.4 在管理前端的草稿表单、详情、列表和发布预览中展示并编辑工作区策略，同时显示字段来源和准确自然周期语义
- [x] 3.5 将 File Service/File Worker readiness 纳入发布预检和运行状态，依赖未接线时返回稳定非敏感 reason code
- [x] 3.6 修复管理前端附件与连续会话策略字段丢失，并强制任务工作区依赖消息附件策略

## 4. File Service 骨架、身份与唯一对象入口

- [x] 4.1 新建 `file-service` 应用和容器目标，使 Streamable HTTP File MCP 与内部流式 REST 共享领域服务、授权、事务、审计和健康检查
- [x] 4.2 实现平台 JWKS 缓存与 Principal JWT 验证，校验 issuer、audience、authorized party、时间、JTI、用户、租户、Job、Session、Publication、授权 hash 和精确 scope
- [x] 4.3 实现 File Authorization Service，对私聊用户归属、群会话双边界、实际 sender、业务应用访问、RUNNING Job 和 Manifest 动作默认拒绝式复核
- [x] 4.4 实现受限的 `file-worker` 服务 Principal 校验，将附件导入/清理 scope 与用户 Agent scope 分离并拒绝共享 Internal API Token
- [x] 4.5 实现 MinIO 基础设施适配器，只在 File Service 内解析 `secret://platform/`，使用服务端生成的不透明对象键并禁止凭据、Bucket、对象键和预签名 URL 越层
- [x] 4.6 增加配置、异常、日志、Tool 结果和审计脱敏测试，证明 JWT、MinIO Secret、钉钉凭据、对象键和文件正文不会被持久化或返回模型
- [x] 4.7 在平台 API 身份模块复用统一Principal Key Ring实现角色bootstrap认证、独立固定claim/scope和不超过300秒的Service Principal按需签发与安全审计，并验证共享JWKS不扩大Token可接受接口
- [x] 4.8 为 File Worker 与 Delivery Worker 实现短时 JWT 缓存/到期前刷新，并让 File Service 按完整固定角色 scope 集合验证当前接口所需 scope

## 5. 文件、版本、工作区与配额核心

- [x] 5.1 实现按 Session 创建、复用、结束和切换 Task Workspace 的应用服务，保证普通文字问答不创建工作区且同一 Session 最多一个 ACTIVE
- [x] 5.2 实现私聊用户所有权和群会话共享所有权模型，不保存钉钉群成员 ACL，并为跨用户、跨群、跨租户和失效应用访问补充拒绝测试
- [x] 5.3 实现 Managed File、不可变 File Version、当前版本乐观推进、来源血缘和外部引用服务
- [x] 5.4 实现第一阶段 TXT 验证：真实类型/扩展名、UTF-8、可选输入 BOM、无 BOM 输出和 15 MiB 流式上限
- [x] 5.5 实现每工作区最多 20 个逻辑文件和 100 MiB 未保留内容配额，在对象或正式版本可见前原子拒绝超限提交
- [x] 5.6 实现内容不可用终态，内部副本删除后拒绝通过旧钉盘引用恢复并返回要求重新上传的安全结果

## 6. 固定 File MCP 工具与统一审计

- [x] 6.1 以代码 Manifest 注册工作区查询、文件元数据查询、精确版本物化意图、提交意图、保留和交付所需的最小固定 File Tool 集合
- [x] 6.2 为 File Tool 输入启用 closed schema，只接受逻辑文件/版本/沙盒句柄和业务意图，拒绝主体、reply route、URL、路径、Bucket、对象键、凭据引用和 Server 地址
- [x] 6.3 让 `tools/list` 和 `tools/call` 同时按 Job 冻结 Tool identifier、schema hash、scope 和 Publication 过滤，并在漂移或非 RUNNING Job 时失败关闭
- [x] 6.4 将 File MCP operation、attempt 和 event 接入统一 MCP Operation Audit，记录有界身份、版本、提交、交付、状态和耗时摘要
- [x] 6.5 增加 MCP 协议测试，覆盖短时 JWT、Job/Publication/scope 不匹配、跨工作区 File ID、schema 漂移、Secret 注入和审计脱敏

## 7. Job File Manifest 与 Channel 接线

- [x] 7.1 在文件型 Agent Job 创建事务中解析或创建活动工作区，并冻结工作区 ID、Publication 保留策略和不可变 Job File Manifest
- [x] 7.2 将本次消息新上传和用户显式引用的合法 TXT 自动加入 Manifest，把其他工作区文件仅以无正文、无对象位置的有界元数据候选暴露
- [x] 7.3 在钉钉私聊入口绑定真实内部用户，在群聊入口用企业、Connector、conversation ID 和实际 `senderStaffId` 建立共享边界并逐消息复核访问
- [x] 7.4 为冻结后新版本产生、权限撤销、工作区到期、内容已删除和跨会话引用增加 Job/物化授权回归测试
- [x] 7.5 保持既有 JPEG、PNG、WebP、DOCX、XLSX、PPTX 和 Markdown 附件兼容链路，并确保它们不会被错误宣称进入第一阶段任务工作区编辑能力
- [x] 7.6 实现纯 TXT 附件消息静默暂存、同 Session 多文件累积、后续非空文字原子认领唯一 Job、导入竞态释放、一次性自动消费和跨 Session 隔离，并补齐 migration、Channel/File Worker/Manifest/管理端回归测试
- [x] 7.7 使用下一条前向 migration 保存并回填原始附件 `source_received_at`，升级 Job File Manifest schema，并在 File MCP、Python/TypeScript Runtime 自动物化元数据中统一投影 `source_received_at`、`version_created_at` 和服务端 `observed_at`，覆盖最近一小时筛选、Agent 生成文件空来源时间、旧 Manifest 兼容及模糊 `created_at` 不再作为上传时间的回归测试

## 8. Runtime Job Sandbox 与受限文件工具

- [x] 8.1 为 Python Runtime 实现 Job 专属沙盒映射、规范化安全文件名、文件/版本/相对路径句柄和成功/失败/取消/超时 finally 清理
- [x] 8.2 为 TypeScript Runtime 实现与 Python 等价的 Job 专属沙盒映射和全终态清理，保持 `settingSources: []` 与调用级配置隔离
- [x] 8.3 实现启动及周期残留扫描，只删除没有 RUNNING Job 归属的明确沙盒目录，并增加 Runtime 崩溃恢复测试
- [x] 8.4 仅对冻结文件能力的 Job 通过SDK `tools`开放沙盒内 `Read`、`Glob`、`Grep`、`Write`、`Edit`，保持自动批准集合为空并逐次执行路径守卫；继续拒绝 Bash、Shell、NotebookEdit、Web、任意 MCP 和其它开放执行能力
- [x] 8.5 为两个 Runtime 实现真实路径、`..`、绝对路径、符号链接、特殊设备、文件数量和容量守卫，并在副作用前拒绝逃逸
- [x] 8.6 将 Runtime file-transfer coordinator 接入 Python/TypeScript 真实 Claude SDK 工具循环，在 File MCP ToolResult 返回模型前拦截受控描述、流式物化 Manifest 精确版本，且不接受任意 URL 或直接访问 MinIO
- [x] 8.7 实现仅文件 Job 可见的代码自有 `select_sandbox_output`，把一个经过路径、类型、符号链接、大小和 UTF-8 校验的精确本地 TXT 注册为不透明 sandbox entry；提交意图必须触发该精确 entry 的流式上传，Job 结束不得扫描或自动提交全部沙盒文件
- [x] 8.8 增加 Python/TypeScript 等价性测试，覆盖按需下载、精确版本、Read/Glob/Grep/Write/Edit、路径逃逸、配额、取消清理和字节不进入模型事件
- [x] 8.9 在Business Application保存、发布和运行时就绪链路校验任务文件功能开关与Agent/Application File MCP Tool快照一致，拒绝“功能已开但工具未冻结”的假就绪配置
- [x] 8.10 将有界Job File Manifest投影交给两个Runtime，在首次模型请求前自动物化当前消息/显式引用项，并用SDK `default` permission mode保证空自动批准集合下所有内建与MCP调用仍进入`canUseTool`
- [x] 8.11 修复Claude Code CLI在`canUseTool`前将相对文件路径解析为绝对路径导致Python Runtime拒绝`Write/Edit`的问题，在Python与TypeScript沙盒守卫中只接受精确位于当前随机Job Sandbox内的SDK解析路径并还原为相对路径，增加真实Python CLI写入和跨Runtime路径逃逸回归

## 9. 两阶段提交、幂等与并发冲突

- [x] 9.1 实现 File Commit Intent 创建，绑定 Principal、Job、Workspace、目标 File 或新文件、base version、沙盒句柄和规范化元数据摘要
- [x] 9.2 实现绑定 Principal JWT 与 Commit ID 的内部流式上传，边接收边计算内容哈希、大小和 UTF-8 校验，并拒绝仅凭 Commit ID 上传
- [x] 9.3 实现 staging 不可见状态、不可变对象发布、数据库版本事务、当前指针推进、Outbox 和跨存储失败补偿事实
- [x] 9.4 实现严格 Commit ID 幂等：相同绑定和内容返回原 Version ID，任一元数据或哈希变化均拒绝
- [x] 9.5 实现 base version 乐观并发；失败内容形成受生命周期约束的 Conflict Candidate，且不得推进当前指针或成为 Retained File
- [x] 9.6 让后续 Job 可同时冻结最新版本与冲突候选，由 Agent 显式合并并以最新版本重新提交，File Service 不执行自动文本合并
- [x] 9.7 为提交响应丢失、重复上传、哈希变化、数据库回滚、对象写入失败、三个文件部分冲突和成功版本不回滚补充事务与集成测试
- [x] 9.8 在上传前拒绝活动逻辑名冲突并把发布竞态映射为稳定 `file_logical_name_conflict`，证明不产生 staging/版本或通用失败
- [x] 9.9 让成功与幂等恢复 Commit 回执返回精确 File、Version 及默认 Delivery 身份和当前状态，并由 Python/TypeScript Runtime 文件桥完整校验和投影

## 10. File Worker 替换、附件导入与生命周期清理

- [x] 10.1 将现有 `attachment-worker` 实现迁移为 `file-worker`，保留原队列名、声明、消息兼容、attachment ID 幂等、短期来源凭证清除和等待 Job 释放行为
- [x] 10.2 改造 File Worker 的附件流程，使外部字节经 File Service 导入并建立消息附件、File、Version、Workspace 和来源血缘关联，移除 Worker 直接 MinIO 写入
- [x] 10.3 保留现有受限 Office/Markdown 提取行为，并为任务工作区 TXT 仅执行有界 UTF-8 校验与导入，第一阶段不部署或调用 docling-server
- [x] 10.4 实现工作区到期扫描，暂缓有关联非终态 Job、Commit 或 Delivery 的清理，并在终态后按原固定到期时间继续处理
- [x] 10.5 实现 staging、无引用临时版本、Conflict Candidate、超期附件/Retained File 和数据库已标记对象的可重试清理状态机
- [x] 10.6 实现 MinIO 未知孤儿对象的只报告核对，以及数据库引用缺失对象的安全告警，默认不自动删除未知孤儿
- [x] 10.7 增加旧队列 ready/unacked 切换、重复消息、清理瞬时失败、历史已到期附件和内部内容删除后不可恢复测试

## 11. 精确版本交付与 Job 结果

- [x] 11.1 在钉钉修改/生成请求成功提交后，为每个精确 Version 创建回当前 reply route 的文件 Delivery 意图；“只保存到工作区”时跳过
- [x] 11.2 扩展现有 Delivery Outbox/Attempt，使其冻结 File、Version、内容摘要、会话、Job、Principal、Publication 和幂等键
- [x] 11.3 让 Delivery Worker 从 File Service 受控读取精确版本并创建新的钉盘文件，不覆盖输入原件、不发送冲突候选且不直接访问 MinIO
- [x] 11.4 实现交付失败独立重试同一版本、提交不回滚、Agent 不重跑和成功交付创建独立 360 天 Retained File 事实
- [x] 11.5 保持现有 Job 终态枚举；Runtime 正常回复时将多文件成功/冲突/拒绝逐项写入结果且 Job 为 `SUCCEEDED`，不新增 `PARTIAL`
- [x] 11.6 增加交付超时、响应丢失、重复投递、工作区到期暂缓、最终失败后清理和跨会话目标拒绝测试
- [x] 11.7 修复钉钉Stream会话已提交文件无法回发：冻结私聊发送人/群openConversationId/robotCode，令精确FILE_VERSION Delivery专用复用来源Stream Connector调用私聊或群机器人OpenAPI，并实现当前Job已提交版本的幂等`file_deliver_version`
- [x] 11.8 明确 `PENDING` 仅为排队状态，并为终态失败文件 Delivery 创建可崩溃恢复、最多一次且不递归的原路安全通知

## 12. Compose、凭据隔离与运行观测

- [x] 12.1 更新 Compose、镜像构建和环境示例：净新增 `file-service`，以 `file-worker` 替换 `attachment-worker`，不增加独立 `file-mcp`，并保留独立 Delivery 服务
- [x] 12.2 只向 File Service 注入 MinIO endpoint 和平台 Secret Reference 解析能力，从 Agent Worker、两个 Runtime、File Worker、Delivery 和前端移除 MinIO 凭据与直连配置
- [x] 12.3 将 Runtime tmpfs 改为受控配置并实现启动校验、单 Job 配额和仅显示非敏感上限的健康状态
- [x] 12.4 实现 File Service readiness，真实验证 migration head、私有 Bucket 权限、JWKS、Tool Manifest 和内部流式接口依赖
- [x] 12.5 实现 File Worker readiness 和运营指标，覆盖 RabbitMQ 契约、File Service 连接、附件/暂存/工作区/保留清理积压、最早到期时间和安全错误分类
- [x] 12.6 更新平台运维 API 与前端，展示 File Service/File Worker 接线、积压和最近结果，不显示文件名、正文、对象键或 Secret
- [x] 12.7 增加 Compose 配置和容器检查，证明默认服务清单、单附件消费者、MinIO Secret 唯一挂载和 docling-server 未部署
- [x] 12.8 更新密钥初始化、Compose和环境示例，只维护统一Principal私钥/JWKS与角色隔离bootstrap credential，删除独立Service Principal密钥配置和宿主机静态Service JWT文件要求并验证首次启动
- [x] 12.9 由 File Worker 维护链路发布并终结 File Domain Outbox，清理历史积压并在后端、管理 API 和前端展示安全积压与最近失败

## 13. 灰度迁移、验收与文档收口

- [x] 13.1 编写附件关联与到期事实回填命令，支持 dry-run、分批、断点续跑和对账，不下载重复内容也不删除对象
- [x] 13.2 编写单消费者切换运行手册：暂停 `attachment-worker`、核对 ready/unacked、启动 `file-worker`、验证幂等和必要时按顺序回滚
- [x] 13.3 通过 Publication Revision 功能开关灰度工作区、File MCP、Runtime Write/Edit 和默认文件交付，未命中 Job 保持原行为
- [ ] 13.4 使用合成 TXT 和假凭据完成私聊真实链路验收：Channel ingress、File Worker、File Service、PostgreSQL、MinIO、RabbitMQ、Job、真实 Claude SDK Runtime 工具循环、Sandbox、File MCP、Commit、Delivery 和最终回复；不得以手工直接调用 transfer coordinator 代替 Runtime 接线证据
- [x] 13.5 使用两个群成员完成群工作区连续编辑与并发冲突验收，证明实际 sender 审计、同群共享、跨群拒绝和只有一个当前版本
- [x] 13.6 完成负向验收：Principal 拒绝、权限撤销、非法编码、15 MiB/20 文件/100 MiB 拒绝、路径逃逸、幂等重试、沙盒残留、staging 清理、交付重试和 Secret/正文不泄漏
- [x] 13.7 更新 `CONTEXT.md`、相关 ADR、Compose/运维文档和管理员说明，明确自然周期、360 天独立保留、第一阶段 TXT、钉钉在线编辑不可感知和重新上传规则
- [x] 13.8 在代码、migration、测试、运行证据和回滚窗口全部满足后执行 contract：移除旧 `attachment-worker` 服务及其 MinIO 直连路径，不删除消息附件业务身份
- [x] 13.9 运行受影响的后端、前端、Runtime、MCP、Worker、migration、Compose 与端到端测试，并执行 `openspec validate add-governed-task-file-workspaces --strict`、未完成任务核对和 `git diff --check`
- [x] 13.10 使用新生成的统一假Principal材料和角色bootstrap credential完成本地Compose创建、按需签发、角色隔离、刷新窗口、跨Token类型拒绝和File Service验签验收，不记录或回显任何真实Secret/JWT
