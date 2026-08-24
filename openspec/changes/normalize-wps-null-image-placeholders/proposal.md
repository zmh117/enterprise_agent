## Why

部分由 WPS Office 生成的可正常打开和渲染的 DOCX 会保留指向不存在 `NULL` 包项的零尺寸图片占位关系。当前 Docling 的 DOCX 后端会在读取关系包时把这类文档判为无效，导致本可安全解析的正文和可见图片进入 `FAILED` 且无法形成 Markdown Representation。

## What Changes

- 在固定 `docling-layout-ocr-v2` Profile 中增加有界、确定性的 DOCX 兼容规范化。
- 仅当缺失目标是内部图片关系、目标规范化为 `NULL`，且全部引用均位于零宽或零高 DrawingML 图片占位时，删除相应占位节点和关系后继续处理。
- 保持上传原件及其 File Version、内容哈希和交付行为不变；规范化副本只存在于当前处理 attempt 的内存或临时目录中。
- 对非 `NULL` 缺失关系、可见图片引用、无法确定安全性的包结构继续非重试失败，不引入通用 Office 修复或 LibreOffice 回退。
- 将规范化算法版本纳入处理器 build 身份，并记录不含文件正文、文件名或关系值的安全处理事实；保持现有 Profile hash 不变，避免使已发布应用快照失效。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `document-file-processing`: 扩展固定文档处理 Profile 对 WPS 零尺寸 `NULL` 图片占位关系的安全兼容边界，同时保持其它损坏或不确定 DOCX 的拒绝语义。

## Impact

- 影响 `file-processing-worker` 的 DOCX 提交前处理、固定 Profile hash、文档处理错误分类和测试样本。
- 不修改 File Service 原件、File Version、对象存储格式、MCP、Agent Sandbox、权限或交付协议。
- 现有终态失败 run 不原地修改；相同 Source Version 需由新处理器 build 身份创建新 run 才能重处理。
