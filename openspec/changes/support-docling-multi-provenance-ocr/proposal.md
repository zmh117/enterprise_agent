## Why

当前 `docling-layout-ocr-v2` 适配器把每个非空 OCR 文本项限制为恰好一个 provenance；当固定 Docling 对复杂界面截图返回多个合法文字位置片段时，平台会以 `docling_picture_provenance_invalid` 关闭整张图片，导致可读 DOCX 只能以 `PARTIAL` 交付。现场文件已确认 7 张图片中第 5、7 张因此失败，且图片可正常解码、Docling 任务成功返回结果，因此需要补齐多段 provenance 的受控兼容边界。

## What Changes

- 对具有多个合法 provenance 的 Docling 文本项，按明确字符区间和坐标确定性地产生有界 OCR block，而不是把整张图片直接标记为失败。
- 对缺失、空、类型错误、字符区间无效、重叠/越界或无法与文字唯一对应的 provenance 继续失败关闭，不猜测文字与坐标关系。
- 保持现有 OCR Layout v2 坐标、置信度、reading order、数量/字符/关系上限以及 `PARTIAL` 降级语义不变。
- 增加覆盖单 provenance、多 provenance 和非法 provenance 的适配回归，并以现场 DOCX 的第 5、7 张图片进行真实处理验收。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `document-file-processing`：明确固定 Docling 返回多个合法 provenance 时的确定性 block 映射规则，以及无法安全映射时继续失败关闭的边界。

## Impact

- 影响 Docling 图片结果适配与布局 OCR block 生成逻辑，主要位于 `backend/app/modules/document_processing/layout_ocr.py`。
- 增加 document processing 单元/集成回归；不改变外部 API、数据库 Schema、RabbitMQ 消息、Profile 环境配置或容器拓扑。
- 部署后需要重建 `file-processing-worker` 镜像；既有终态 processing run 保持不可变，现场文件需创建新的 run 才能验证修复结果。
