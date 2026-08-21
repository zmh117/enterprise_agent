## Context

当前 checkout 中的 `docling-text-v1` 只要求 `MARKDOWN` 与 `DOCLING_JSON`，使用图片 placeholder，关闭图片导出和图片描述；Python Runtime 只接受冻结的 Markdown Representation。正在实施的 `add-governed-docling-file-representations` 已建立精确源版本、processing run、File Service staging/finalize、RabbitMQ、Docling Provider、Manifest 与 Runtime 沙盒边界，但其设计明确把 Office 图片资产导出和图片语义理解列为非目标。

本设计是后续能力，不能把该 active delta 当成 canonical Requirement。开始 apply 前，`add-governed-docling-file-representations` 必须完成、验证并同步到 canonical specs；届时还要重新核对 migration head、Profile/Manifest schema、Compose和dirty worktree。当前提案描述 Documented-intent，不证明目标环境已经具备 Office 内嵌图片 OCR。

DOCX 与 PPTX 的父文档定位语义不同。PPTX shape 在固定 slide 坐标系中有确定位置；DOCX 会受字体、分页器和渲染环境影响而重排，内嵌图片通常只有稳定文档节点/段落关系，没有可跨环境重放的页坐标。OCR引擎返回的图片内部坐标也可能使用像素、浮点、左下角原点或旋转后的空间，因此必须经过平台规范化后才能成为可审计事实。

完整OCR文字、坐标和图片仍是业务内容。File Service必须保持唯一对象存储事实入口；File Processing Worker与Docling只能通过绑定run/item的受控流取得或回传字节，不得获得MinIO凭据、Bucket或对象键。

## Goals / Non-Goals

**Goals:**

- 新增单选代码Profile `docling-layout-ocr-v1`，完整继承`docling-text-v1`的格式、正文、表格、独立图片OCR、安全和原件交付语义，并增加DOCX/PPTX内嵌栅格图片布局OCR。
- 为每个图片出现位置冻结父文档锚点，并为每个规范化图片冻结内部OCR文字、置信度、阅读顺序、规范化坐标和有界空间关系。
- 发布不可变`OCR_LAYOUT_JSON`和布局增强`MARKDOWN`；Agent只读取Markdown，不接收原图、Base64、Docling JSON或OCR Layout JSON。
- 让父文档解析、图片提取、子图片OCR、组装、失败恢复、配额、清理和审计具有持久且幂等的状态边界。
- 保持现有Runtime协议、File MCP工具集合、原件身份、Delivery和历史Publication行为不变。

**Non-Goals:**

- 不启用VLM、图片描述API、远程模型、自定义模型、外部插件或运行时模型下载。
- 不从栅格图中推断箭头方向、颜色语义、图标/照片含义、精确图表因果或未被OCR提取的内容。
- 不把内嵌图片提升为任务工作区逻辑File、不允许Agent物化图片，也不提供任意图片浏览/MCP读取工具。
- 不为DOCX渲染或伪造稳定页码坐标，不引入LibreOffice/PDF渲染作为布局事实源。
- 不修改`docling-text-v1`的code、version、hash、固定输出或历史processing run。
- 不在本change引入向量索引、chunks、跨文件语义检索或多模态Runtime协议。

## Decisions

### 1. 一个新Change引入一个完整Profile，而不是叠加两个Profile

Business Application Publication继续只冻结一个`document_processing_profile_code`。`docling-layout-ocr-v1`必须复制并冻结`docling-text-v1`的全部输入格式、正文/表格/OCR选项、资源边界和安全关闭项，再增加内嵌图片处理和第三种输出`OCR_LAYOUT_JSON`。旧Publication仍选择`NONE`或`docling-text-v1`，不得在运行时继承新能力。

未选择“`docling-text-v1 + layout-ocr-addon`”组合，因为这会引入Profile组合顺序、hash合成、管理端矛盾状态和历史重放复杂度；也不原地升级旧Profile，因为同一Profile hash必须保持相同处理契约。

### 2. Profile驱动必需输出集合

Representation终结规则从全局固定集合改为代码Profile固定集合：

- `docling-text-v1`：`MARKDOWN`、`DOCLING_JSON`；
- `docling-layout-ocr-v1`：`MARKDOWN`、`DOCLING_JSON`、`OCR_LAYOUT_JSON`。

File Service在创建transfer、校验media type/encoding/schema/大小和原子finalize时解析processing run已经冻结的Profile，不接受Worker、管理端或模型声明输出集合。新Profile只有三种必需输出全部STAGED且互相绑定同一run/source Version时才能发布；旧run继续按两个输出终结。

`OCR_LAYOUT_JSON`使用`application/json`，但与Docling JSON采用不同kind和独立schema/大小上限。它不得成为File Version、不得交付、不得进入Manifest可物化内容，也不得因同源而替换最终Markdown。

### 3. 使用文档级布局Schema保存双坐标空间

`OCR_LAYOUT_JSON`采用代码发布的`enterprise-agent.office-image-ocr-layout/v1` Schema，并至少包含：

- 精确source File/Version、processing run、Profile hash、layout schema version和Assembler version；
- `picture_occurrence_id`、稳定`picture_ref`、出现顺序和规范化图片SHA-256；
- 父锚点：PPTX使用`slide_no`、Docling picture `self_ref`作为稳定shape/ref和图片在slide中的规范化bbox；DOCX使用picture `self_ref`、Docling返回且可解析的最近稳定父容器ref（可能是段落、表格单元、section或body）和同父节点顺序，不要求上游未提供的段落/单元ref，也不包含伪造页码；
- 图片空间：规范化后宽高、原始宽高、图片自身EXIF方向、`RAW_EMBEDDED_MEDIA_AFTER_EXIF`像素基准及`office_display_transform_applied=false`事实；
- OCR block与可选word：稳定局部ID、Unicode文字、`confidence_bp`、`reading_order`、规范化bbox和可选polygon；
- 有界关系：`LEFT_OF`、`RIGHT_OF`、`ABOVE`、`BELOW`、`SAME_ROW`、`CONTAINS`，以及关系算法version；
- 每张图片的`AVAILABLE`、`NO_TEXT`、`SKIPPED_LIMIT`或`FAILED`状态和白名单错误码。

图片内部坐标统一为左上角原点、闭区间`0..10000`的整数空间；bbox固定为`[x0,y0,x1,y1]`且必须满足非负、有序和边界约束。浮点、像素、左下角原点和图片自身EXIF方向只在Provider内转换，不直接成为平台坐标契约。Office显示层裁剪、旋转和翻转不参与图片像素规范化；整数规范化减少引擎差异和canonical JSON/hash漂移。

完整OCR文字和坐标只保存在File Service管理的对象中。PostgreSQL保存run/item、schema、状态、大小、SHA-256、模型/引擎provenance、锚点摘要和生命周期，不逐word保存OCR正文。

### 4. 内嵌图片是派生处理资产，不是工作区File

父Docling任务使用代码固定的`target_type=zip`、`image_export_mode=referenced`和`include_images=true`取得有界、带picture ref的内部图片artifact bundle；既有`docling-text-v1`继续使用原`inbody + placeholder`合同。Docling部署可以为固定Provider允许`zip`target，但Worker、用户、管理端和环境变量不得选择target或导出模式。Provider必须对返回包实施总响应大小、entry数量、路径、媒体类型、单entry大小、解压后总量、重复名和symlink边界校验；图片、Base64、文件名和对象路径不得写日志或队列。固定镜像在默认INFO级别会记录上传名和外部task ID，因此生产部署必须把Docling应用/访问日志提升到不输出该字段的受控级别，Provider同时只发送与source display name无关的固定安全上传名。

File Processing Worker安全解码并规范化白名单PNG/JPEG/WebP，仅应用图片文件自身EXIF方向、去除非必要元数据，校验单图/累计像素和大小，再通过绑定parent run的File Service staging保存`document_picture_asset`。OCR像素事实源固定为Docling从Office包导出的原始嵌入媒体；Worker不解析DrawingML，也不应用Office显示层裁剪、旋转或翻转。数据库中的asset与occurrence分离：相同规范化SHA-256在同一tenant/source Version/run/Profile内可复用一次OCR计算，但每个DOCX/PPTX出现位置保留独立occurrence和父锚点。不得跨tenant用内容哈希探测或复用业务图片。

图片asset只服务处理恢复，Agent不可见，也不占任务工作区逻辑文件数；其字节计入Profile固定的派生内容配额。父run终态且三个最终representations发布后，asset内容进入可重试清理；保留asset/occurrence ID、哈希、状态和provenance，但不得继续返回图片字节。新Profile或处理器重算必须从仍可用的精确Office source Version重新提取，不恢复旧已清理asset。

未选择在File Processing Worker独立解析OOXML ZIP或增加DrawingML变换检查器，因为这会形成第二套Office结构/关系事实并显著增加裁剪、旋转、翻转、蒙版和特效兼容面。代价是OCR可能包含Office页面上已裁掉的区域，方向也只反映原始图片自身EXIF；Profile、布局JSON、Markdown、管理端和Runtime必须显式声明该限制。也未选择把图片作为`managed_file`，因为一份PPTX的图片数量不应消耗工作区逻辑文件名额或获得原件File动作。

### 5. 父解析和子图片OCR使用持久item编排

单个parent processing run保持既有公开状态集合，并增加仅供运维和恢复的固定`stage_code`：`PARENT_PARSE`、`PICTURE_OCR`、`ASSEMBLING`。新增持久`document_picture_processing_item`保存asset/occurrence集合、OCR引擎/模型digest、attempt、外部task ID、状态、时间和安全错误码，不保存OCR正文。

处理顺序为：

1. parent消息claim精确run并调用Docling取得正文、Docling JSON和图片bundle；
2. Worker通过File Service原子保存picture asset/item及唯一子任务Outbox，parent进入`PICTURE_OCR`并ack parent消息；
3. 每个唯一图片子任务通过绑定item的受控流调用固定Docling image OCR，规范化OCR结果并提交item staging；
4. 最后一个item进入终态后写唯一assembly Outbox；
5. Assembler按图片occurrence稳定顺序生成完整`OCR_LAYOUT_JSON`，并把有界布局附录追加到parent Markdown；
6. Worker上传三种representation，File Service按Profile原子finalize parent run后才ack assembly消息；
7. asset和孤立staging由生命周期任务清理。

RabbitMQ只携带run/item/Profile hash/correlation/attempt等稳定身份，不携带图片、OCR文字、坐标、文件名或对象键。parent、child和assembly消息均以数据库Outbox和唯一约束提供幂等边界；Docling临时task仍不是平台事实源。

未选择让单个Worker消息同步串行处理全部图片，因为大PPTX会长时间占用prefetch槽位且崩溃后只能整份重算；持久item允许逐图恢复、受控并发和明确部分结果，同时不新增服务或第二套消息总线。

### 6. 布局关系由版本化确定性算法生成

平台先按OCR polygon/bbox、行高、重叠比例和文字方向形成word、line、block与reading order，再只为相邻或包含关系生成有界关系，避免全量`O(n²)`关系。算法阈值、最大block/word/relationship数量和version属于Profile canonical payload并进入hash；模型、用户消息和管理端不能修改。

关系只是几何事实，不得命名为流程边、因果或语义连接。原生PPTX shape/connector或chart数据若后续需要使用，必须由独立change定义结构化合同；本change不从栅格像素或文字位置推断箭头。

### 7. Agent只读取布局增强Markdown

Assembler保留Docling正文和表格输出，在文末追加固定格式的“内嵌图片布局OCR”附录。每个图片section包含父锚点、坐标说明、按reading order排序的OCR block、置信度等级、关键几何关系和明确状态；不包含图片字节、data URI、对象键或内部task ID。低置信度文字必须标记，不得自动改写成看似确定的内容。

Manifest仍只冻结源File/Version与最终`MARKDOWN` Representation ID、size、SHA-256和安全物化名。Runtime继续只物化Markdown到Job Sandbox；`OCR_LAYOUT_JSON`和Docling JSON没有`MATERIALIZE`动作。这样布局能力不要求Runtime protocol版本升级，也不把大JSON直接塞入conversation context；Agent仅在Read/Grep/Glob读取本地Markdown时接触不可信内容。

### 8. 部分成功与上限必须显式

图片OCR成功但无文字时，item为`NO_TEXT`，布局JSON和Markdown明确“未提取到文字”；这不等于图片没有视觉含义，也不使parent自动PARTIAL。个别图片损坏、OCR失败或因资源边界未处理时，item为`FAILED`或`SKIPPED_LIMIT`，parent可发布正文与其余结果但必须为`PARTIAL`，列出不含文件名/正文的图片序号和安全原因。

图片数超过软处理上限时按稳定occurrence顺序处理有界集合，并为其余图片写`SKIPPED_LIMIT`；不得静默截断。图片数量、Office解压结构、单图或累计像素超过安全硬上限时在模型调用前确定拒绝。Markdown、Docling JSON或OCR Layout JSON任一超过Profile固定上限时不得只发布前缀；run按确定错误失败或根据已定义PARTIAL合同发布完整有界结果。

### 9. 安全、生命周期与运行边界不因OCR扩大

OCR文字、空间关系和Assembler输出始终是不可信用户数据；固定Runtime提示与文件能力说明必须禁止其覆盖系统指令、身份、授权、Tool策略、网络和沙盒。Docling继续禁外网、禁UI、禁remote services/custom configs/plugins/callbacks；所需OCR模型和layout artifacts在镜像构建或受控部署阶段固定revision与digest，readiness必须验证本地可用，运行时不得下载。

Representation和picture asset不得比source Version更晚可用，并继承tenant、owner、workspace与retention边界。只有File Service解析对象存储凭据；Worker与Docling环境、日志、审计、MQ、错误和健康结果不得泄漏OCR正文、图片、对象键、Secret或业务文件名。

### 10. 第一版Profile资源上限由固定CPU基准冻结

2026-08-21使用固定v1.30.0镜像、4 CPU、单Docling local worker和合成典型/边界DOCX/PPTX完成离线基准。32张不同的1280×720图片在串行picture OCR下耗时约128.4秒，单图最大4.319秒；因此第一版保持保守单转换并发，不用未测并发推断吞吐。

`docling-layout-ocr-v1`固定以下边界并全部进入canonical payload/hash：

- 图片occurrence软上限32，按稳定顺序处理；第33至128个写`SKIPPED_LIMIT`并让parent为`PARTIAL`。图片occurrence硬上限128，超过即在OCR前拒绝整次run；
- 单图压缩字节上限10 MiB、单图解码像素上限16,777,216、单run累计解码像素上限67,108,864；规范化asset与全部派生对象合计上限256 MiB；
- artifact ZIP压缩响应上限128 MiB、entry上限512、解压计费上限256 MiB；
- 每图OCR block上限2,048、word上限8,192、关系上限4,096、字符上限262,144；单run对应总上限为16,384 block、65,536 word、65,536关系和4,194,304字符；
- `MARKDOWN`保持15 MiB，`DOCLING_JSON`保持64 MiB，`OCR_LAYOUT_JSON`为64 MiB；任一必需输出超限不得发布截断前缀；
- parent parse deadline 600秒、单picture attempt deadline 120秒、assembly deadline 120秒、parent run总deadline 1,800秒；parent、picture和assembly各最多3次attempt；
- 默认CPU部署的Docling活动转换全局并发上限1、单parent在途picture item上限1。提高并发、图片数、像素或输出上限必须发布新Profile version/hash并重新基准，不得通过环境变量放宽。

软上限用于可解释的部分成功，硬上限用于防止解压、像素和任务放大。数量、像素、字符、关系和字节分别校验，不能用其中一个额度替代另一个。

## Risks / Trade-offs

- [坐标让Agent误以为获得完整视觉理解] → Profile、Markdown标题和固定notice统一称“布局OCR”，明确不识别箭头、颜色、图标、照片语义和未提取内容。
- [DOCX页坐标随渲染环境漂移] → 只保存稳定文档节点/段落/表格锚点和图片内部坐标，不渲染或伪造页码。
- [Docling导出图片bundle或picture ref在升级后漂移] → Provider使用固定镜像digest、严格结果schema和合成DOCX/PPTX契约测试；任何processor/digest/Profile变化创建新run，不覆盖旧表示。
- [Office显示层裁剪/旋转未体现在原始媒体] → 将原始嵌入图片明确冻结为OCR像素事实源，只应用图片自身EXIF；合成fixture证明未应用Office显示变换，所有Agent可见与管理端说明提示可能包含已裁掉区域。
- [大量图片导致CPU、队列和对象存储放大] → child item持久编排、去重、硬/软上限、独立积压观测和基准后固定并发；asset在parent终态后清理。
- [OCR block/关系数量导致JSON与Markdown膨胀] → block/word/relation/字符/字节独立上限、相邻关系算法和Profile驱动终结；不得无提示截断。
- [OCR错误或低置信度被Agent当成事实] → 保存置信度、标记低置信度、保留原文字面输出，不做无依据纠错；Agent面向用户应说明机器提取边界。
- [图片中包含提示注入] → 内容只作为沙盒不可信文件读取，Tool与权限在服务端固定，图片文字不得影响Manifest、授权或Provider选项。
- [新change与未同步Docling change冲突] → apply gate要求基础change先完成并同步canonical；之后重新生成差异、分配migration并运行严格验证，禁止覆盖当前active工作。

## Migration Plan

1. 完成、验收并同步`add-governed-docling-file-representations`，确认canonical已包含文档Profile、processing run、representation和Manifest规则；若未满足则停止apply。
2. 基于最新migration head追加expand migration：2026-08-21 preflight确认磁盘与本地Compose ledger head均为`115_expand_file_turn_admission.sql`，若创建时head仍未变化则使用`116`；该migration覆盖Profile约束、`OCR_LAYOUT_JSON` kind与校验、Profile驱动输出集合、picture asset/occurrence/item/attempt、stage/outbox/staging/cleanup事实和索引，不得读取、生成或删除对象。
3. 部署兼容新schema但默认不激活新Profile的File Service、Worker、API与管理端；历史Profile和run保持原终结集合。
4. 部署固定OCR/layout artifacts与Provider bundle契约，使用合成DOCX/PPTX验证双坐标转换、ZIP/图片拒绝、逐图恢复、去重、部分成功、清理和Secret不泄漏。
5. 创建仅用于验收的Business Application Publication选择`docling-layout-ocr-v1`，完成新鲜Channel到Markdown物化、Agent分析和原件Delivery链路；不得以容器healthy替代E2E。
6. 基准测试典型和边界DOCX/PPTX后冻结图片数、像素、block/字符、派生字节、超时和并发参数及Profile hash，再显式激活目标Publication。

回滚时停止创建或激活`docling-layout-ocr-v1` Publication，让新任务继续使用既有`docling-text-v1`或`NONE`；安全终结/排空parent与child队列，保留新增schema、历史run、representation和审计。不得down-migrate、改写旧Publication、删除已发布结果或把新run降级解释为旧Profile结果。

## Apply Gate Outcomes

- 固定镜像referenced ZIP合同已通过，精确结构与设计收紧记录在`evidence/docling-office-picture-bundle-contract.md`。
- 固定CPU典型/边界基准已通过，上限与原始聚合指标记录在`evidence/layout-ocr-limit-benchmark.md`；这些值必须进入Profile canonical payload与hash后才允许激活新Profile。
- Office transform fidelity探针证明固定镜像导出原始图片像素，不应用PPTX裁剪/旋转，`include_page_images=true`也不生成可绑定渲染像素。已明确选择原始嵌入图片作为OCR像素事实源，不增加OOXML变换检查器；Profile hash、布局输出、Markdown、管理端和Runtime均冻结并提示该边界。此项不再阻塞migration与兼容部署，但目标Publication仍须通过任务9.7新鲜E2E后才能激活；详见`evidence/docling-office-picture-bundle-contract.md`。
