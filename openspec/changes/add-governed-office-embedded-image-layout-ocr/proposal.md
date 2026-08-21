## Why

当前 `docling-text-v1` 能提取 Office 原生正文和表格，却把 DOCX、PPTX 内嵌栅格图片输出为占位符；图片中的文字、位置和版面关系不会进入 Agent 可读表示。需要在不启用 VLM、不把原图或 Base64 交给 Agent、也不扩大 Runtime 协议的前提下，引入可审计的布局感知 OCR，让 Agent 能依据文字及其空间关系更可靠地分析截图、表单、仪表盘和简单结构图。

## What Changes

- 新增代码发布 Profile `docling-layout-ocr-v1`。它是 `docling-text-v1` 的完整超集，继续支持既有源格式、正文、表格和独立图片 OCR，并为 DOCX、PPTX 内嵌栅格图片提取 OCR 文字、置信度、规范化坐标、阅读顺序和有界空间关系；既有 `docling-text-v1` 的 code、version、hash 和历史行为保持不变。
- 为每个精确源 File Version 生成不可变 `OCR_LAYOUT_JSON` 派生表示，使用版本化 Schema 保存图片父文档锚点、图片尺寸/摘要、OCR block/word、坐标与空间关系；完整 OCR 内容继续由 File Service 写入私有对象存储，PostgreSQL 只保存身份、状态、大小、哈希、Profile/处理器 provenance 和生命周期事实。
- 由确定性 Assembler 把有界布局结果合并进同一份 Agent 可读 Markdown，明确坐标系、图片位置、OCR 置信度、阅读顺序和部分失败；Agent 仍只物化 Markdown，`OCR_LAYOUT_JSON`、Docling JSON、Office 原件和图片字节均不得进入 Job Sandbox、MCP JSON 或初始 conversation context。
- 为 PPTX 保存 slide/shape 与幻灯片内图片位置；为 DOCX 保存稳定文档节点/段落锚点，不伪造会随字体和渲染环境变化的页码坐标。图片内部坐标统一规范化为左上角原点的 `0..10000` 整数空间，同时保留原始像素尺寸、旋转和裁剪变换。
- 对内嵌图片实施真实格式、压缩大小、解码像素、累计像素、图片数量、OCR block/字符数、派生字节、处理时间和并发上限；重复图片可按内容哈希复用 OCR 计算，但每个父文档出现位置保留独立锚点。
- 将图片提取、OCR布局结果和 Markdown 组装纳入现有 processing run、Outbox、RabbitMQ、File Processing Worker、staging/finalize、重试与清理边界；部分图片失败或超限必须形成明确 `PARTIAL` notice，不得静默省略或声称已完整理解。
- 保持图片内容为不可信用户数据。图片中的文字和空间关系不得改变系统提示、Tool可见性、授权、网络或沙盒边界；日志、审计、队列和错误事实不得记录OCR正文、文件名、原图、对象键或原始异常。
- 明确第一阶段只提供布局感知 OCR，不识别栅格箭头、颜色、图标、照片语义或精确图表因果，不启用 VLM、远程图片描述、自定义模型、运行时模型下载或外部插件。
- 本 change 的实施前置条件是 `add-governed-docling-file-representations` 完成并同步到 canonical specs；在该前置条件满足前只能评审本提案，不得 apply 或让 delta 覆盖仍在进行的 Docling change。

## Capabilities

### New Capabilities

- `office-embedded-image-layout-ocr`: 定义 Office 内嵌图片提取、双坐标空间、版本化 OCR Layout Schema、确定性空间关系、布局增强 Markdown、部分成功语义和非 VLM 能力边界。

### Modified Capabilities

- `business-application`: 增加代码发布的 `docling-layout-ocr-v1` 选择与 Publication code/version/hash 冻结，保持旧 Publication 和 `docling-text-v1` 行为不变。
- `task-file-workspace`: 增加 `OCR_LAYOUT_JSON` 派生表示的身份、配额、生命周期和非物化规则，并保持 Agent 只读取冻结的布局增强 Markdown。
- `platform-operations`: 增加 Office 图片提取/OCR所需固定模型 artifacts、资源上限、队列/就绪/积压观测和布局 OCR 端到端验收。

## Impact

- 受影响代码包括文档处理 Profile 注册、Docling Provider/适配层、File Processing Worker、processing run 与 representation staging/finalize、File Service 流式接口、Manifest/Markdown组装、派生内容配额与生命周期、管理端 Profile 展示及运行中心观测。
- 需要前向 migration 扩展 Profile 约束、Representation kind、OCR Layout provenance/Schema元数据、Profile驱动的必需输出集合及必要索引；2026-08-21 apply preflight确认磁盘与本地Compose ledger的当前head均为`115_expand_file_turn_admission.sql`，因此候选版本为`116`，创建migration前仍须再次确认head未变化。
- `docling-layout-ocr-v1` 仍通过 Business Application Publication 显式启用，不因部署模型或容器而自动赋予既有应用新能力；Publication一次只选择一个文档处理 Profile，新 Profile 必须包含旧文字 Profile 的全部能力而不是与其叠加选择。
- Agent Runtime 协议保持现状：Manifest冻结原件和最终 Markdown Representation，Runtime只物化 Markdown。任何未来向多模态模型发送原图或识别视觉语义的能力必须另行提出 change。
