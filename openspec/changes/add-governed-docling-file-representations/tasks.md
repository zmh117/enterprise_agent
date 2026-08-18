## 1. 变更前置与依赖收敛

- [x] 1.1 重新核对当前分支、dirty worktree、migration head、active changes 和相关 canonical specs，记录与 `support-log-and-markdown-workspace-files`、平台拓扑变更的重叠点，确保不覆盖并行工作。
- [x] 1.2 明确本变更与 Markdown 工作区支持、File Service/File Worker 拓扑的依赖顺序；对复用字段、manifest 版本和 Compose 服务名形成唯一实现口径。
- [ ] 1.3 从官方 Docling/Docling Serve 发布物核验候选镜像的版本、digest、CPU 架构、许可证和 SBOM；在实现时固定 tag 与 digest，不使用 `latest`。
- [ ] 1.4 用脱敏样本完成 CPU 基准测试并记录峰值内存、单文件延迟和吞吐；据此把 phase 1 worker 并发固定为 1 或 2，并验证 25 MiB、300 页、600 秒边界可执行。

## 2. 数据模型与扩展迁移

- [x] 2.1 先补充数据库契约测试，覆盖处理配置、处理运行、派生表示、唯一性、状态枚举、索引和外键约束。
- [x] 2.2 新增 expand migration：创建 `file_processing_run` 与 `file_representation`，并为业务应用 revision/publication 增加文档处理 profile 快照字段。
- [x] 2.3 为 source version 与 representation 建立不可混淆的引用约束；保证同一 source version、profile hash、representation kind 的成功结果幂等唯一。
- [x] 2.4 为处理状态、可读性状态、重试调度、租户/应用/Job 查询和清理扫描增加必要索引及 schema 注释。
- [x] 2.5 在 SQLite 单测库和 PostgreSQL 迁移测试上验证 upgrade、旧数据兼容和当前 migration ledger；本变更不执行破坏性 down migration 或 contract/drop。

## 3. 受治理处理配置

- [x] 3.1 实现代码内置 `docling-text-v1` profile registry，固定输入格式、OCR/表格能力、资源上限、输出种类和规范化配置 hash。
- [x] 3.2 强制 `docling-text-v1` 禁用 VLM、远程 URL、回调、插件、自定义 pipeline、任意参数透传和运行时模型下载。
- [x] 3.3 为 Business Application revision 增加 `document_processing_profile_code`，默认 `NONE`；发布时校验 profile 并冻结 code、version 和 hash。
- [x] 3.4 保持旧 publication 的 `NONE` 兼容行为，禁止平台通过全局开关静默改变已发布应用语义。
- [x] 3.5 补充管理 API/UI 的 profile 展示、选择、发布校验和只读快照测试，不向普通用户暴露 Docling 原生任意配置。

## 4. File Service 处理领域

- [x] 4.1 实现处理运行与派生表示的领域模型、repository 和状态机，区分 source lifecycle、processing lifecycle 与 representation lifecycle。
- [x] 4.2 在 source import 时执行真实格式嗅探、扩展名/MIME 一致性检查、大小与页数边界检查，并仅授予 `READ_METADATA`、`RETAIN`、`DELIVER` 等源文件动作。
- [x] 4.3 通过 File Domain Outbox 幂等创建处理请求，消息只携带稳定 ID、profile hash、尝试号和追踪标识，不携带二进制或凭据。
- [ ] 4.4 提供仅供 processing worker 使用的短期授权 source stream 接口，校验 tenant、principal、source version、用途和审计上下文。
- [x] 4.5 提供 representation staging/upload/finalize 接口：分别校验 Markdown/JSON 大小、hash、媒体类型和 profile provenance，二者完成后原子暴露成功结果。
- [x] 4.6 实现 finalize、重复投递、worker 崩溃重试和并发完成的幂等保护，失败结果不得留下可见的半成品表示。
- [x] 4.7 实现 orphan staging reconciliation、失败重试扫描和 retention cleanup；派生表示不得比 source version 或其受治理 workspace 生命周期更长。
- [x] 4.8 为 File Service 的跨租户拒绝、越权读取、状态跃迁、幂等和清理行为补充聚焦测试。

## 5. 消息、Worker 与 Docling Provider

- [x] 5.1 增加 RabbitMQ processing queue、publisher/consumer、重试退避、最大尝试次数和 DLQ 配置，并与现有 outbox/inbox 事务模式保持一致。
- [x] 5.2 建立独立 `file-processing-worker` 运行身份、最小权限授权和启动 wiring；禁止复用管理员或用户 bearer token。
- [x] 5.3 在 `DocumentProcessor` seam 下实现 Docling Serve provider，仅使用内部 multipart 上传、异步 submit/poll/fetch 流程，并设置连接、轮询和总处理超时。
- [x] 5.4 对 Docling 响应做严格 schema/媒体类型/大小校验，将成功、部分成功、无文本、格式拒绝、超限、超时和服务故障映射为平台稳定错误码。
- [x] 5.5 实现 worker 状态机：领取、source stream、Docling submit/poll/fetch、representation staging/finalize、ack/retry/DLQ；每一步均保持可重放。
- [x] 5.6 确保日志、消息、异常和 audit 不记录原始文档、完整提取文本、Docling API key、内部签名 URL 或其他 credential。
- [x] 5.7 使用 fake Docling server 补充 provider 和 worker 契约测试，覆盖慢轮询、重复回调式结果、畸形输出、超限、进程重启和 broker redelivery。

## 6. 附件接入与 Job 就绪门禁

- [x] 6.1 在启用 profile 的 publication 上，将支持格式的附件导入为 source version 并触发异步 processing；停止为该路径生成新的 `attachment_content`，但保留旧 publication 兼容读取。
- [x] 6.2 分离 source ingestion 状态和 readability 状态，落实 `NOT_REQUIRED`、`PENDING`、`AVAILABLE`、`PARTIAL`、`NO_TEXT`、`UNAVAILABLE` 的确定性转换。
- [x] 6.3 Job 在必需表示 `PENDING` 时进入受限等待状态，仅由持久化处理事件释放；重启后不得依赖进程内等待或丢失唤醒。
- [x] 6.4 对非空 `PARTIAL` Markdown 允许带治理提示继续；对 `NO_TEXT`/`UNAVAILABLE` 禁止伪造文本或静默当成可读内容。
- [x] 6.5 当请求只有不可读附件且无有效文本指令时，不调用模型并返回结构化不可处理说明；混合输入则仅使用可用表示并附带缺失提示。
- [ ] 6.6 补充渠道附件 E2E 前置测试，覆盖 DOCX/PPTX/XLSX/PDF/PNG/JPEG/WebP、旧 publication、重复 ingress 和 Job 重放。

## 7. Manifest v4 与 Runtime 物化

- [x] 7.1 扩展 manifest schema v4 与 hash 规范，分别冻结 original source version 和 `markdown` representation version/profile provenance，并保留旧 manifest 读取兼容。
- [x] 7.2 File Service 生成 manifest 时只引用已原子完成的 representation；原始二进制不得获得 `READ_CONTENT`，JSON 表示不得被默认投影到 Runtime。
- [x] 7.3 File Service 物化接口按冻结的 representation version 校验 tenant、Job、manifest hash 和动作，拒绝 latest-following、跨 Job 访问及 source/representation 混用。
- [x] 7.4 更新 Runtime 文件协议与 bridge，把 Markdown 表示物化到每 Job sandbox 的确定性只读路径，并保留 source/display/provenance 元数据映射。
- [x] 7.5 Runtime 仅通过既有 `Read`/`Grep`/`Glob` 能力访问 Markdown 文件；不得将全文重新内联到 conversation context，也不得新增通用 HTTP/MCP/Shell executor。
- [ ] 7.6 增加 manifest v3/v4 compatibility、tamper rejection、过期表示、只读权限、同名冲突和 cleanup 的聚焦测试。

## 8. Delivery、审计与运维可见性

- [x] 8.1 保持渠道/文件交付引用 original source version；Markdown/JSON representation 不得替代用户原始附件或被意外交付。
- [ ] 8.2 增加处理请求、状态跃迁、拒绝原因、重试、耗时、页数、输出大小和 Job 关联的结构化 audit/metrics，并执行 payload redaction。
- [ ] 8.3 在管理面提供按 tenant/application/profile/status 的 backlog、失败和 DLQ 摘要，以及 source→run→representation→Job 的可追溯视图。
- [ ] 8.4 为审计保留期、访问控制、representation provenance 和原始业务内容不落日志增加契约测试。

## 9. Compose、网络与 Secret 边界

- [x] 9.1 增加 `docling-serve` 与 `file-processing-worker` 两个容器，固定镜像 digest、非 root 用户、只读根文件系统、临时卷、CPU/内存限制和健康/就绪检查。
- [x] 9.2 将 Docling 置于内部网络且不发布宿主端口；只允许 processing worker 调用，Docling 不持有 PostgreSQL、RabbitMQ、MinIO 或模型供应商凭据。
- [x] 9.3 通过现有 Secret bootstrap 为 processing worker 配置专用 File Service credential，并为 Docling API 配置独立 secret；示例环境文件只声明变量名和安全默认值。
- [x] 9.4 更新 Compose 拓扑、运维文档和服务清单，明确新增净拓扑为 `file-processing-worker + docling-serve`，phase 1 不引入 Redis、RQ、Ray 或 `file-mcp`。
- [x] 9.5 增加 Compose config 与安全契约测试，检查固定 digest、内部端口、网络隔离、依赖健康、资源限制、无明文 secret 和无运行时下载。

## 10. 验证、发布门禁与旧路径退役证据

- [x] 10.1 运行受影响模块的 schema、repository、File Service、worker、Runtime、Business Application、渠道和 delivery 聚焦测试，并记录失败与修复证据。
- [ ] 10.2 在 fresh PostgreSQL/RabbitMQ/MinIO/Docling Compose 环境执行脱敏 synthetic E2E，验证七类输入、拒绝边界、超时、重试、重启、幂等与 representation cleanup。
- [ ] 10.3 执行一条真实的 Runtime→Inbox→Outbox→RabbitMQ→Job→processing worker→Docling→representation→Runtime→Delivery 链路，证明成功与失败路径，而不以容器健康替代业务证据。
- [ ] 10.4 在默认 `NONE` 下验证零行为变化；再按单个测试 publication 启用 `docling-text-v1`，观察 backlog、资源和错误率后才允许扩大范围。
- [ ] 10.5 对新 profile 路径执行“无新增 `attachment_content`”对账并记录旧数据依赖；本变更不 drop 旧表/列，后续 contract migration 必须另行审批并满足备份、保留期和零引用门禁。
- [x] 10.6 运行完整相关测试、`openspec validate add-governed-docling-file-representations --strict`、migration/schema 检查和 `git diff --check`，将实现状态与剩余限制写入 evidence，不把设计意图表述为已上线能力。
