# 任务工作区文件格式使用说明

当前代码固定使用 `text-v2` 直接文本规则，不再由 Business Application、Publication、
Job 或 Runtime 选择 `text-v1/text-v2`。

| 格式 | 可进入工作区 | Agent 可创建/编辑 | 可交付 |
|---|---:|---:|---:|
| `.txt` | 是 | 是 | 是 |
| `.log` | 是 | 否 | 是，仅既有精确版本 |
| `.md` | 是 | 是 | 是 |
| `.markdown` | 否 | 否 | 否 |

三种文本格式都必须是 UTF-8 且不超过 15 MiB。输入可以包含 UTF-8 BOM；Agent 新建或
编辑的输出不能包含 BOM。平台拒绝 NUL、无效 UTF-8、UTF-16、GBK 和二进制伪装。
`.log` 即使声明 `application/octet-stream` 也必须通过完整文本验证。

Markdown 始终按不可信纯文本处理：管理端不渲染正文，平台不执行 HTML、不解析链接、
不抓取远程资源。需要 Agent 生成文件时，应明确要求“创建/编辑/保存 `.md` 文件”；仅让
聊天回复使用 Markdown 排版不会自动产生文件提交。

LOG 是只读诊断证据。Agent 可以读取、搜索并交付 Manifest 中已有的精确版本，但不能
写入、追加、改名后提交或创建新 LOG。需要整理日志时，应生成新的 `.txt` 或 `.md`。

## 文档与图片

PDF、DOCX、XLSX、PPTX、PNG、JPEG 和 WebP 不是直接文本。只有命中的 Application
Publication 冻结 `docling-layout-ocr-v2` 时，平台才会保存原件并异步生成 Agent 可读的
Markdown Representation；Profile 为 `NONE` 时明确拒绝且不调用 Docling。

原始二进制、Docling JSON、OCR Layout JSON 和图片 asset 不会进入 Agent Sandbox，也
不能被 Agent 编辑。源文件最大 25 MiB，PDF 最多 300 页。DOC、XLS、PPT、宏文件及其他
未注册格式不支持。

## 保存与交付

默认文件交付只发送 Agent 明确提交的 TXT/Markdown 精确版本；“只保存到工作区”不会
发送回会话。Delivery 重试同一版本，不重新运行 Agent。既有源文档的交付仍使用精确
原始 File Version，不把 Markdown Representation 冒充原件。
