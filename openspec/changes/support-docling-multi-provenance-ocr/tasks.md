## 1. 先建立失败与兼容回归

- [x] 1.1 在 `backend/tests/test_document_layout_ocr.py` 增加合成双 provenance 用例，使用合法 `charspan`、bbox、空白间隙和不同置信度，并确认旧实现以 `docling_picture_provenance_invalid` 失败。
- [x] 1.2 增加确定性期望：双 provenance 展开为两个顺序稳定的 block，文字切片、bbox、block ID、`reading_order`、置信度、关系和重复运行字节完全一致。
- [x] 1.3 增加失败关闭参数化用例，覆盖缺失/空/非对象 provenance、缺失或非整数 charspan、空区间、越界、重叠、非空白缺口和非法 bbox，且 fixture 不包含现场 OCR 正文。
- [x] 1.4 增加展开后 block 数超过 `max_blocks_per_picture` 的回归，确认返回 `docling_picture_block_limit_exceeded` 且不产生截断结果。

## 2. 实现确定性多 provenance 展开

- [x] 2.1 在 `layout_ocr.py` 增加有界的 provenance 解析/排序/覆盖校验逻辑；单 provenance 保持完整 text 路径，多 provenance 仅按合法 charspan 产生文字片段。
- [x] 2.2 将 block ID、`reading_order`、bbox 和置信度改为基于最终展开序列生成，并保持既有单 provenance canonical JSON 字节不变。
- [x] 2.3 将单图 block 上限应用到最终展开后的 block 集合，字符上限继续按每个上游完整 text 只累计一次，并保留现有关系数量上限。
- [x] 2.4 确认 Worker、数据库、日志与审计不新增 OCR 正文、charspan/bbox 明细或原始 Docling 失败响应，且不改变 API、消息、Schema 或 Profile 配置。

## 3. 代码与规格验证

- [x] 3.1 运行 `backend/tests/test_document_layout_ocr.py` 及相关 document processing/Worker 回归，确认新增用例和既有单 provenance、NO_TEXT、坐标、置信度、Assembler 用例通过。
- [x] 3.2 运行受影响 Python 静态检查、`docker compose config --quiet`、`git diff --check`，确认没有无关文件或配置漂移。
- [x] 3.3 运行 `openspec validate support-docling-multi-provenance-ocr --strict`，确认 delta spec 与全部工件严格有效。

## 4. 现场部署与完整链路验收

- [ ] 4.1 重建并滚动更新两个 `file-processing-worker`，确认两个 processing consumer、两个全局槽位与 Docling readiness 正常，且不修改 Docling 模型 digest/Profile 环境参数。
- [ ] 4.2 对现场 DOCX 的精确 File Version 使用新 Worker build 创建新 processing run，确认旧 `PARTIAL` run 及其错误事实保持不变。
- [ ] 4.3 验证新 run 的 7 个 picture item 全部为 `AVAILABLE`、父 run 为 `SUCCEEDED`、assembly 为 `COMPLETED`，且 Markdown、Docling JSON、OCR Layout JSON 三种 Representation 均完成发布。
- [ ] 4.4 通过受控物化读取新 Markdown，确认图片 5、7 不再显示 OCR 失败占位且其 block 已进入布局附录；证据只记录状态、数量、版本/哈希与安全错误码，不复制业务正文。
- [ ] 4.5 核对 processing 队列、stage outbox、槽位释放与重复 Representation，确认无遗留消息、无占用槽位、无重复发布后再完成交付。
