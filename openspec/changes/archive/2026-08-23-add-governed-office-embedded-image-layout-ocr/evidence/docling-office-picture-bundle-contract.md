# Docling Office picture bundle contract probe

验证日期：2026-08-21（Asia/Shanghai）

## 固定输入与运行边界

- 镜像：`quay.io/docling-project/docling-serve:v1.30.0@sha256:0244089785d5ccb7570dfaa593cdc81ec64a1aadc63ffa9dce065064b0a6a807`。
- 输入：仓库脚本生成的合成DOCX与合成PPTX，不含业务数据。
- 探针：`scripts/probe_docling_office_picture_bundle.py`；只输出结构计数、schema keys、media type与字节数，不输出凭据、task ID、文件名、提取文字或图片字节。
- 请求固定为异步file conversion、`target_type=zip`、`image_export_mode=referenced`、`include_images=true`、Markdown+JSON；关闭图片描述、图片分类、图表提取、代码/公式增强。
- 下载以128 MiB硬上限流式读取，并在解压前检查响应media type与Content-Length；ZIP继续限制entry数量、压缩/解压总量、路径穿越、绝对路径、反斜线、重复名、symlink和白名单后缀。

## 结构结果

### DOCX

- 响应为`application/zip`，压缩7470字节、解压计费20312字节，共4个entry：1 Markdown、1 Docling JSON、1 PNG及目录结构。
- Docling JSON有1个picture；`self_ref`、parent ref和image ref均存在，parent可解析且parent children反向包含picture ref，referenced image URI精确命中ZIP图片entry。
- 图片media type为`image/png`。该合成DOCX没有page provenance、page number或page bbox；最近父容器label为`section_header`。

### PPTX

- 响应为`application/zip`，压缩18872字节、解压计费43136字节，共6个entry：1 Markdown、1 Docling JSON、3 PNG及目录结构。
- Docling JSON有3个picture；3个`self_ref`、parent ref和image ref全部存在并可解析，3个parent children全部反向包含picture ref，3个referenced image URI全部命中ZIP图片entry。
- 3个picture均有`page_no`与bbox provenance，图片media type均为`image/png`；父容器label为`chapter`。

## 结论与设计收紧

- 固定镜像满足异步referenced artifact ZIP、picture ref、父容器ref、媒体类型、PPTX slide/page+bbox及有界单次结果下载合同，任务1.3通过。
- 上游没有为DOCX提供稳定页坐标，也不保证最近父容器一定是段落或表格单元；canonical delta改为接受Docling返回的可解析最近父容器ref及同父顺序，禁止伪造更细锚点。
- 上游没有独立原生PPTX shape ID；Profile将稳定Docling picture `self_ref`作为shape/ref，并与`page_no+bbox`组合。
- 当前正式Compose只允许`inbody`target；后续部署任务必须显式允许受控`zip`，但只有新Profile的固定Provider可以请求它，旧Profile合同不变。
- 固定镜像默认INFO日志会输出上传名与外部task ID。验证确认提高Docling应用/访问日志级别后不再输出这些字段；实现仍须发送与用户display name无关的固定安全上传名，并增加日志边界测试。

## Transform fidelity follow-up 与已确认像素基准

2026-08-21 使用额外合成PPTX复核了Office可见变换：源PNG为`1200×800`，在slide中设置上/下各25%裁剪并旋转90度。固定镜像的`referenced` artifact仍为原始`1200×800` PNG；裁剪和旋转没有烘焙到导出像素。把`include_page_images`改为`true`后，DOCX/PPTX bundle的entry、图片数和图片尺寸均未增加，不能取得可绑定的渲染页像素。

因此固定上游合同只证明图片身份、父锚点和原始artifact导出，不证明Office可见裁剪/旋转。已确认采用该原始artifact作为OCR像素事实源：平台仅应用图片文件自身EXIF方向，不解析DrawingML，也不应用Office显示层裁剪、旋转或翻转，不增加OOXML变换检查器。Profile canonical payload记录`RAW_EMBEDDED_MEDIA_AFTER_EXIF`与`office_display_transform_applied=false`，布局Markdown、管理端与Runtime明确提示结果可能包含页面上已裁掉区域。

该选择把上述探针从阻塞项转换为固定回归合同：合成PPTX必须继续证明导出图片为原始`1200×800`像素，且所有Agent可见结果不得声称等同Office可见渲染。此决定不自动授权创建或激活目标Publication；仍须完成任务9.7的新鲜全链E2E。探针只使用合成色块和固定测试文字，输出结构与尺寸聚合，不输出图片、OCR正文、Secret或业务标识。
