## Context

当前 checkout 已具备 File Service、私有 MinIO、不可变 `managed_file_version`、任务工作区、Job File Manifest、Runtime 单 Job Sandbox 与 File MCP bridge。只有 File Service 可以解析 MinIO 凭据和对象键；RabbitMQ、Agent、Runtime 与 Worker 只传递稳定身份或经授权的文件流。当前文本格式代码策略只把 TXT、LOG 和 Markdown 作为 Agent 可读文件，Office 兼容提取仍把正文保存到 `attachment_content` 后有界注入上下文，PDF 不受支持，图片以 `stored_not_interpreted` 结束。

Canonical spec 目前明确禁止 `docling-serve`，因此本设计描述的是 Documented-intent，不证明 Docling 已经部署或当前链路已实现。实施前还必须处理与其他 active change 在文件策略、Runtime protocol、Compose manifest 和 migration head 上的重叠，不得把 active delta 当成已接受基线。

Docling 官方 v1 API 可以接收 multipart 文件、异步返回 task ID、轮询状态并获取 Markdown/Docling JSON。Docling 自身的异步任务与结果暂存不是本平台的业务事实源：平台仍以 PostgreSQL processing run、File Domain Outbox、RabbitMQ 和私有 MinIO 为可恢复事实。

## Goals / Non-Goals

**Goals:**

- 把 PDF、DOCX、PPTX、XLSX、PNG、JPEG 和 WebP 原件纳入 File Service 的身份、版本、保留、授权和交付边界。
- 对精确原件版本异步生成不可变 Markdown 与 Docling JSON，并保存处理器版本、镜像 digest、profile hash、状态、错误和血缘。
- 让 Agent 只按需读取 Markdown 表示；原始二进制、Docling JSON、对象位置和凭据不进入模型上下文。
- 保持 Job、处理任务、文件提交和文件交付为相互独立且可恢复的状态机。
- 默认关闭文档处理，由 Business Application Publication 显式冻结代码发布 profile 后启用。
- 在 Compose 中以两个职责清楚的新增服务落地，并证明真实 DingTalk 到 Agent/Delivery 链路，而不是只证明容器健康。

**Non-Goals:**

- 不使用 VLM，不生成架构图、流程图、仪表盘或普通照片的视觉语义描述；图片只进行 OCR 文字提取。
- 不把 Docling 暴露为 MCP、Agent Tool、任意 HTTP capability 或管理端可配置的处理器。
- 不支持 DOC、XLS、PPT、宏文件、压缩包、SVG、音视频、任意 URL source、远程模型或第三方 Docling 插件。
- 不支持直接编辑或原样重建 PDF/Office 文件；Agent 可以读取派生 Markdown并生成新的受支持文本文件，但不得声称保留原件版式。
- 不在第一阶段加入 chunks、向量数据库、知识库索引、跨文件语义检索或 Docling 图片资产导出。
- 不在第一阶段引入 Docling RQ/Redis 或 Ray；扩容必须建立在负载和恢复证据上。

## Decisions

### 1. Docling 是内部 DocumentProcessor Provider，不是 Agent-facing Tool

平台定义窄接口 `DocumentProcessor`，输入是平台已验证的文件流与代码固定 profile，输出是受限的 Markdown、Docling JSON、状态、处理耗时和安全错误。`DoclingServeProcessor` 是首个 Provider，唯一 Consumer 是 `file-processing-worker`。

选择该方案是为了保持 Harness 的 Definition/Provider/Consumer seam：Agent、File MCP、消息入口和 Runtime 均不依赖 Docling HTTP 细节，未来替换实现只影响 Provider。没有选择 MCP 或任意 HTTP Handler，因为文档转换是平台数据面编排，不是模型自主决定的 Tool Call，也不能让模型提交 URL、Header、模型或解析参数。

### 2. 原件版本与派生表示分开建模

`managed_file_version` 继续只代表用户原件或 Agent 显式生成/编辑的文件版本。新增：

- `file_processing_run`：绑定 `tenant_id`、`source_file_id`、`source_version_id`、`processor_code`、`processor_version`、镜像 digest、`profile_code`、`profile_hash`、状态、attempt、外部 task ID、时间和安全错误。
- `file_representation`：绑定 processing run 和精确 source version，记录 `MARKDOWN` 或 `DOCLING_JSON`、media type、encoding、size、SHA-256、内部 object key、状态、创建与内容删除时间。

相同 `source_version_id + processor build digest + profile_hash` 只能有一个逻辑 processing run；每个 run 每种 representation 最多一个 AVAILABLE 结果。处理器升级或 profile 改变创建新 run，不覆盖旧表示。`file_representation` 不进入 `managed_file.current_version_id`，也不改变用户下载的原件。

未选择“把 Markdown 建成原文件新版本”，因为这会破坏文件身份、当前版本和交付语义；也未选择把完整正文放入 PostgreSQL，因为正文不是关系事实，且会重新引入直接上下文注入和大字段生命周期问题。

### 3. 源文件策略与 Agent 可读策略正交

新增代码注册的源格式定义：PDF、DOCX、PPTX、XLSX、PNG、JPEG、WebP。它们允许 `READ_METADATA`、`RETAIN`、`DELIVER`，但不得直接 `MATERIALIZE`、`EDIT` 或 `COMMIT` 到 Agent Sandbox。现有文本格式策略继续定义 TXT、LOG 和 Markdown 的读写动作。

渠道提供的图片文件名和媒体类型只作为来源元数据，不能作为真实格式事实。File Worker 必须先安全解码 JPEG、PNG 或 WebP、执行像素上限检查、去除不需要的元数据并重新编码；File Service 再按规范化字节的真实媒体类型与文件签名确定源格式。若图片原始扩展名与规范化格式不一致，File Service 使用相同 stem 和真实格式的 canonical extension 创建受治理 display name，并在同名时继续使用既有不透明 attachment 后缀消歧；原始名称仍只保留在 `message_attachment` 来源事实中。该兼容规则仅适用于成功解码并重新编码的图片，不适用于 PDF、Office 或其他文件，后者的扩展名、媒体类型和结构仍必须严格一致。

File Service 的拒绝响应只向 File Worker 返回有界安全消息和稳定机器 `error_code`。File Worker 必须保存白名单机器码到 `message_attachment.failure_code`，不得把本地化提示文字当作错误码，也不得记录原始响应正文。这样运维可以区分格式、签名、配额和身份拒绝，而不泄漏文件内容或内部异常。

文档的 Markdown 表示是只读 `agent-readable` 内容，不是可交付原件。Job Manifest schema v4 中一个文档条目同时包含：

- 原件 `file_id`、`source_version_id`、display name、source media type、来源/版本时间和原件动作；
- 精确 `content_representation`：representation ID、kind、SHA-256、size、只读 format code 与安全 materialized name。

`file_prepare_materialization` 继续让模型以 Manifest 中的 File/Version 身份选择候选；File Service 必须从同一冻结条目解析精确 representation，不接受模型自行替换 representation、URL 或对象键。Runtime bridge 的隐藏传输控制信息绑定 representation ID、Job、一次性 transfer 与安全沙盒路径。

### 4. Business Application Publication 冻结处理 profile

Business Application Revision 增加 `document_processing_profile_code`，默认 `NONE`。发布时必须解析代码注册 profile并冻结 code/hash；运行不得重新读取 Draft 或用环境变量扩大能力。

第一阶段唯一 profile `docling-text-v1` 固定：

- 输入格式：PDF、DOCX、PPTX、XLSX、PNG、JPEG、WebP；
- 输出格式：Markdown、Docling JSON；
- OCR 和表格结构开启，图片导出使用 placeholder；
- VLM、图片语义描述、远程 services、自定义 VLM/picture config、外部 plugins、HTTP source 和 callback 全部关闭；
- 单原件最大 25 MiB、PDF 最大 300 页、单文档处理超时 600 秒、Markdown 最大 15 MiB、Docling JSON 最大 64 MiB；
- 上述值只能通过新的代码发布 profile改变，管理端不能提交原始 Docling options。

选择 Publication 冻结而不是全局自动启用，可避免部署新容器后所有既有应用静默获得新内容能力，并让 Job 可重放其创建时的处理契约。

### 5. 平台 RabbitMQ 提供外层持久编排，Docling 使用单实例 local engine

原件导入与 processing run 创建在 File Service 事务中写 `file.processing.requested` Outbox。Dispatcher 只向 RabbitMQ 发布 run ID、source version ID、profile hash 和 correlation ID，不发布文件字节、正文、对象键、文件名或凭据。

独立 `file-processing-worker`：

1. claim processing run；
2. 用自身短时 Service Principal JWT 向 File Service 请求绑定 run/source version 的只读传输；
3. 流式转发到 `POST /v1/convert/file/async`，只提交固定 profile 参数；
4. 保存 Docling task ID，有限轮询 `/v1/status/poll/{task_id}`；
5. 成功后只取一次 `/v1/result/{task_id}`；
6. 校验状态、格式、大小与 UTF-8，分别流式上传两个 staging representation；
7. 由 File Service 在数据库事务中原子发布表示并把 run 置为终态；
8. 本地终态提交成功后才 ack RabbitMQ。

默认 Compose 只新增一个 `docling-serve` local-engine 容器和一个 `file-processing-worker`。没有第一阶段引入 Docling RQ/Redis，因为平台外层已经有持久 RabbitMQ/DB 状态；Docling local task 在重启后丢失时，Worker把 task 标记为不可恢复并在同一 run 的下一 attempt 重新提交。重复计算允许发生，但唯一约束、SHA-256 与发布事务禁止产生重复表示。

### 6. 表示发布采用 staging 与幂等终结

File Service 为每个 run/kind 创建不透明 staging transfer。Worker 按流上传，File Service 计算 SHA-256、执行大小/UTF-8/JSON结构边界校验并把 staging 对象保持不可见。只有要求的 Markdown 与 Docling JSON 均完整时，单个数据库事务才创建/发布 representation facts、更新 processing run并写完成 Outbox。

相同 run/kind、相同哈希的重试返回同一 representation ID；相同 transfer 或 run 被用于不同内容时失败关闭。孤立 staging 由现有文件生命周期维护边界扩展后可重试清理。MinIO 不是跨对象事务系统，因此数据库可见性而不是对象存在本身决定内容是否可用。

### 7. Job 等待可读性事实而不是只等待附件下载

保留 `message_attachment` 的来源下载/导入状态，并增加与 processing run 关联的可读性事实，避免继续让 `READY` 同时表示“原件已保存”和“Agent 已能阅读”。可读性状态至少区分 `NOT_REQUIRED`、`PENDING`、`AVAILABLE`、`PARTIAL`、`NO_TEXT` 和 `UNAVAILABLE`。

当本轮文字绑定了需处理的附件时：

- 来源下载/导入未终态时，Job 可以保持 `WAITING_INPUT`；
- 来源已保存但必需 Markdown 表示仍为 PENDING 时，不得继续用 `WAITING_INPUT` 等待 Docling，也不得把无关文字 Job 绑进该处理中文档；准入改由 `decouple-document-readiness-from-agent-turns` 的能力门禁处理；
- AVAILABLE 后，Manifest v4冻结精确 Markdown representation；
- PARTIAL 且存在非空、未超限 Markdown时允许执行，并加入固定安全 notice；
- NO_TEXT/UNAVAILABLE 只加入固定安全 notice，不注入伪造正文；
- 存在用户文字或其他可读文件时可以继续执行；只有文件且全部不可读时不调用模型并安全终结。

Docling Markdown 不再写入 `attachment_content`，也不经 conversation attachment text 注入。Runtime 在第一次模型请求前只把 `auto_materialize=true` 的精确 Markdown表示放入 `inputs/<安全原名>.md`；正文仅在 Agent 使用 Read/Grep/Glob 时进入上下文。

### 8. 原件交付、表示阅读和文本输出保持三条路径

- 理解内容：物化冻结的 Markdown representation。
- 下载/转发：Delivery按冻结或授权的原始 File Version读取原件。
- 生成结果：Agent按现有文本格式策略生成新的 TXT/Markdown 文件并显式提交；不得把派生 Markdown 当成原件的新版本，也不得直接编辑 Office/PDF。

因此新增文档处理不会改变 Delivery Outbox 的精确版本语义，也不会因解析部分成功而新增 `PARTIAL` Agent Job终态。

管理端也按这三条路径区分配置语义：“直接文本文件策略”只描述TXT、LOG和Markdown如何由Agent经任务工作区直接读取，“文档解析/OCR Profile”只描述PDF、Office和图片如何生成只读文字表示。组成配置只显示选择结果；processing worker、Docling、processing队列和File Service的实时状态只在已激活Publication的“发布与运行”及运行中心展示。实时探针不可达、Publication未激活或状态未知时均不得从静态Profile注册信息推断`READY`。

### 9. 安全与网络边界

`docling-serve` 不映射宿主端口，不启用 UI，只连接专用内部网络；镜像必须固定 tag 和 digest，模型 artifacts 在镜像构建/受控部署阶段准备，运行时不从互联网下载。服务开启独立 API Key并关闭 remote services、custom configs、callbacks 和 external plugins。

`file-processing-worker` 只持有自己的 bootstrap credential、RabbitMQ 连接和 Docling API Key；没有 MinIO Secret、对象键、Principal签名私钥或其他 Worker credential。`docling-serve` 只有自身 API Key配置，不获得 PostgreSQL、RabbitMQ、MinIO或平台 Principal材料。File Service 仍是唯一对象事实入口。

日志和审计只允许 run ID、source version ID、profile hash、processor version/digest、页数/大小、状态、耗时、attempt和白名单错误码。文件名、正文、Docling JSON、原始异常、对象键、Token 和 Secret不得记录。Docling 输出始终是不可信用户数据，不能覆盖系统指令、权限或 Tool策略。

### 10. 生命周期与删除

representation 不得比 source version 活得更久，并沿用任务工作区派生内容的清理边界：工作区到期时，若没有非终态 Job/processing run使用，派生对象可以进入清理；原始消息附件仍按其独立保留事实保存。删除先把 representation 标为 `CONTENT_UNAVAILABLE` 并提交 cleanup fact，再由 File Worker经 File Service重试删除对象；processing run、哈希、provenance和删除审计可保留，但内容不得恢复或继续物化。

没有选择默认让派生表示跟随原件保留 360 天，因为当前 canonical 将派生内容视为工作区生命周期内容；未来如需跨工作区复用或长期知识库，应通过独立 change 定义新的 retention/indexing合同。

## Risks / Trade-offs

- [CPU Docling 对扫描 PDF 延迟较高] → 第一阶段以 25 MiB、300页、600秒、受控并发限制范围，并用独立 processing worker 避免挡住 Agent 问答；上线前用合成 born-digital/扫描件基准验证，未达SLO时再提出 GPU/RQ 扩容 change。
- [Docling local task 在容器重启后丢失] → PostgreSQL processing run与RabbitMQ是事实源；丢失 task ID只导致同一 run 新 attempt 重算，表示发布保持幂等。
- [异步结果默认单次读取，响应取得后持久化失败] → Worker先写受治理 staging，再终结；失败时重新提交转换，不把 Docling scratch 当持久事实。
- [Markdown 或 JSON 膨胀] → File Service在写入和终结前执行独立上限；Markdown超15 MiB不静默截断、不进入 Runtime，JSON超限使 run 安全失败。
- [OCR 结果不等于视觉理解] → profile和用户提示明确为文字提取；无文字图片返回 NO_TEXT，不调用 VLM也不声称理解图形含义。
- [恶意或损坏文档消耗资源] → MIME/扩展/结构前置校验、非root容器、只读根文件系统、tmpfs/临时空间、CPU/内存/PID/超时限制、禁外网和固定格式 allowlist。
- [新增 schema 与现有 active changes 冲突] → apply 前重新读取 canonical、active status和 migration head；只追加前向 migration，不改 ledger、不复用版本号、不在 migration 中访问或删除 MinIO对象。
- [旧 inline attachment_content 与新表示双写造成两套事实] → 启用 profile 后单一走 representation；先保留旧表兼容历史读取，完成对账和生产门禁后再通过显式 contract migration停止/删除旧写入与影子结构。

## Migration Plan

1. 在 apply 开始前检查 dirty worktree、相关 active change、canonical spec、Runtime protocol和 migration head；对重叠内容先同步、归档或重排，不能覆盖用户改动。
2. 追加 expand migration：Business Application profile字段、processing run、representation、可读性事实、Manifest v4、staging/cleanup/outbox约束与索引；migration只改数据库，不读写 MinIO。
3. 先部署兼容新 schema 的 File Service/API/Worker代码，profile保持 `NONE`；旧 Manifest和历史 `attachment_content`继续可读。
4. 部署固定 digest的 `docling-serve` 与 `file-processing-worker`，创建独立 bootstrap credential/API Key、队列、health/readiness和积压观测；不对外暴露端口。
5. 使用合成应用发布 `docling-text-v1`，完成 API、组件、重启恢复、拒绝路径和无 Secret泄漏验证后，再显式为目标业务应用创建并激活新 Publication。
6. 运行新鲜 DingTalk E2E，关联原附件、source version、processing run、两个 representations、Manifest v4、Runtime沙盒读取、Agent结果和原件Delivery。
7. 在对账证明新 Publication不再产生 Docling范围内的 `attachment_content` 后，提出/执行显式 contract gate；历史数据与审计继续只读保留到既有保留期。

回滚时停止发布或激活 `docling-text-v1`，让新任务回到默认关闭行为，排空或安全终结 processing queue，并保留新增表、对象和审计。不得 down-migrate、删除新对象或改写既有 Job/Publication；修复后可按原 run幂等恢复。

## Open Questions

- 非阻塞：CPU基准测试将决定默认 Docling worker并发是否为1或2；在获得真实负载证据前不得扩大并发或启用GPU。
- 非阻塞：apply 时重新核对上游稳定镜像版本和 digest，并将实际 Docling/Docling Core版本写入 processing provenance；proposal阶段不把 `latest` 视为可部署版本。
