# Layout OCR limit benchmark

验证日期：2026-08-21（Asia/Shanghai）

## 运行边界

- 固定镜像：`docling-serve:v1.30.0@sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807`。
- 资源：CPU模式、4 CPU、8 GiB、单Docling local worker、离线模型artifact；Docling活动转换串行。
- 数据：`scripts/generate_docling_layout_ocr_samples.py`生成的合成DOCX/PPTX，每张图为1280×720且只含合成文字与几何框。
- 方法：`scripts/benchmark_docling_layout_ocr.py`先取得referenced ZIP，再对每个唯一图片执行固定RapidOCR；输出只包含聚合计数、字节与耗时，不包含task ID、文件名、OCR文字、坐标、图片或凭据。

## 观测结果

| Case | 图片 | Parent秒 | 图片OCR总秒 | 单图最大秒 | 像素总数 | Block | Tokenized word | 字符 | Bundle/解压字节 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| typical DOCX | 6 | 1.568 | 24.581 | 4.319 | 5,529,600 | 30 | 72 | 406 | 114,427 / 155,570 |
| typical PPTX | 8 | 0.766 | 32.421 | 4.056 | 7,372,800 | 40 | 96 | 542 | 154,044 / 210,889 |
| boundary DOCX | 32 | 3.804 | 128.206 | 4.080 | 29,491,200 | 160 | 385 | 2,181 | 611,419 / 829,218 |
| boundary PPTX | 32 | 2.794 | 128.412 | 4.061 | 29,491,200 | 160 | 385 | 2,181 | 611,589 / 840,983 |

四个case共耗时322.606秒。32图边界样本在当前串行CPU配置下稳定完成，单图耗时约4秒；没有用并发外推结果。

## 冻结边界

- occurrence：软上限32，硬上限128；软超限形成显式`SKIPPED_LIMIT/PARTIAL`，硬超限在模型调用前拒绝。
- 图像：单图10 MiB、单图16,777,216像素、单run累计67,108,864像素。
- 派生内容：全部asset与表示合计256 MiB；ZIP响应128 MiB、512 entries、解压256 MiB。
- OCR结构：每图2,048 block、8,192 word、4,096关系、262,144字符；单run总计16,384 block、65,536 word、65,536关系、4,194,304字符。
- 表示：Markdown 15 MiB、Docling JSON 64 MiB、OCR Layout JSON 64 MiB。
- 时间与恢复：parent 600秒、picture attempt 120秒、assembly 120秒、run总计1,800秒；各阶段最多3次attempt。
- 并发：默认CPU部署全局Docling活动转换1、单parent在途picture item 1。

边界相对本次32图样本保留了独立的数量、像素、结构、字符、字节和时间余量；任何放宽都要求新Profile version/hash、重新基准和显式Publication，而不是运行环境覆盖。
