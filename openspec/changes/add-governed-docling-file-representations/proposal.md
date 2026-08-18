## Why

当前消息附件中的 Office 文档仍由旧提取器把有界正文写入 PostgreSQL 并直接注入模型，PDF 不受支持，图片只能安全存储而不能提取文字；这与已经落地的 File Service、MinIO、不可变文件版本和 Job Sandbox 治理边界不一致。系统需要把 PDF、DOCX、PPTX、XLSX 和受支持图片统一转换为可审计、可重放的 Markdown 与 Docling JSON 表示，让 Agent 按需读取文字，同时继续用原始文件版本完成下载、保留和交付。

## What Changes

- 引入受治理文档处理能力，以部署固定的 `docling-text-v1` profile 调用自托管 `docling-serve`；第一阶段仅做文字、OCR 和表格结构提取，明确关闭 VLM、图片语义描述、远程服务、自定义模型配置和外部插件。
- 将 PDF、DOCX、PPTX、XLSX、PNG、JPEG 和 WebP 作为受治理源文件导入 File Service；TXT、LOG 和 Markdown 继续沿用现有文本链路，不经过 Docling。
- 新增不可变 `file_processing_run` 与 `file_representation` 事实，分别记录精确源版本的处理状态/处理器 provenance，以及 Markdown、Docling JSON 派生内容的对象位置、哈希、大小、状态和血缘；派生表示不得冒充或替换原始 File Version。
- 通过 File Domain Outbox、RabbitMQ 和独立 `file-processing-worker` 编排异步转换；消息只携带稳定 ID，Worker 通过受控 File Service 流式接口读取原件和回传派生内容，不获得 MinIO 凭据或对象键。
- 扩展 Job File Manifest，使 Job 同时冻结原始 File Version ID 和用于阅读的精确 Markdown Representation ID；Runtime 只把 Markdown 表示物化到单 Job 沙盒，原始二进制不进入 Agent 文件工具或模型上下文。
- 让包含文档的 Job 在所需表示完成前保持 `WAITING_INPUT`；部分成功、完全失败、超限、加密、损坏和处理器重启均产生确定、可审计且不虚构文件理解的结果。
- 由 Business Application Revision 选择代码发布的文档处理 profile，并由 Publication 不可变冻结；未选择 profile 的发布不获得 Docling 能力，也不能提交任意 Docling 参数、模型、URL 或插件配置。
- 默认 Compose 新增内部 `docling-serve` 和 `file-processing-worker`，固定镜像版本与 digest、资源上限、健康/就绪探针、Secret 隔离和安全积压观测；不新增独立 File MCP，不把 Docling 暴露为 Agent Tool/MCP。
- 以扩展迁移和兼容读取方式引入新 schema/Manifest；既有 Job、旧 Manifest 和未启用文档处理的 Publication 保持可恢复，旧 `attachment_content` 写入路径只在新链路稳定并经过显式 contract gate 后退役。

## Capabilities

### New Capabilities

- `document-file-processing`: 定义受治理文档处理 profile、异步处理运行、不可变派生表示、Docling Provider 边界、重试恢复、限制与安全 provenance。

### Modified Capabilities

- `business-application`: 增加由 Revision 选择并由 Publication 冻结的代码发布文档处理 profile，保持默认关闭和禁止任意处理器配置。
- `channel-conversation`: 扩展消息附件支持范围和状态机，用 Docling 文字/OCR结果替代受支持文档的旧正文注入，并定义失败或无可用文字时的安全行为。
- `task-file-workspace`: 区分原始文件版本与派生表示，扩展文件类型、保留/清理、Job Manifest 和 Runtime物化规则。
- `execution-delivery`: 让 Job 等待精确表示、冻结并传递新 Manifest，同时保持原件交付与 Agent执行终态相互独立。
- `platform-operations`: 增加 Docling 与文件处理 Worker 的 Compose 拓扑、迁移、Principal/Secret隔离、资源门禁、观测和完整端到端验收。

## Impact

- 受影响模块包括附件下载与状态机、File Service 内部流式 API、文件域 Repository/Outbox、RabbitMQ 拓扑、Job 创建与 Manifest、Agent Context、Python Runtime File Bridge、文件保留清理、管理运维状态和 Delivery 原件选择。
- 新增数据库表、约束、索引和前向 migration；实施时必须基于当时 migration head 分配版本，不预先占用可能与其他 active change 冲突的编号。
- 新增固定版本的 `docling-serve` 运行依赖及一个平台 `file-processing-worker`；后者复用统一 Principal JWT 体系，Docling 只使用独立内部 API Key，二者均不获得 MinIO Secret。
- 新的 Markdown 和 Docling JSON 保存在私有 MinIO 中，PostgreSQL 只保存身份、状态、大小、哈希、对象位置和血缘；完整正文、文件字节、对象键和凭据不进入 RabbitMQ、MCP JSON、日志或审计。
- 实施依赖当前文本文件策略与 Runtime 沙盒边界保持稳定；不得把未完成的 active change 当作 canonical Requirement，开始 apply 前须重新核对 checkout、相关 change 状态和 schema head。
