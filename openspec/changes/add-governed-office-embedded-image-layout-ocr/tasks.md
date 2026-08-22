## 1. 实施门禁与固定上游合同

- [x] 1.1 完成并严格验证`add-governed-docling-file-representations`，将其delta同步到相关canonical specs；若基础change仍未完成、未同步或存在冲突则停止本change实施。
- [x] 1.2 基于同步后的canonical、当前migration ledger和dirty worktree重新核对本change的proposal/design/specs，记录实际migration head与受影响模块，确保不覆盖用户未提交改动。
- [x] 1.3 使用固定`docling-serve`镜像digest和不含业务数据的合成DOCX/PPTX建立契约探针，验证异步图片artifact bundle、picture ref、父锚点、媒体类型、压缩包结构与有界下载行为；不满足合同时停止实施并更新设计。
- [x] 1.4 对合成的典型/边界Office文档执行离线基准，冻结图片软/硬数量、单图与累计像素、block/word/关系/字符、派生字节、deadline、attempt和并发上限，保存非敏感基准证据供Profile canonical payload使用。

## 2. Profile、领域模型与数据库迁移

- [x] 2.1 为`docling-layout-ocr-v1`定义完整canonical payload、version与hash，显式复制`docling-text-v1`的全部既有格式/正文/表格/安全选项，并增加固定模型digest、布局Schema、关系算法、三种必需输出和已冻结上限。
- [x] 2.2 扩展代码Profile目录、序列化和校验，使Publication只能单选`NONE`、`docling-text-v1`或`docling-layout-ocr-v1`，并添加旧Profile code/version/hash完全不变的回归断言。
- [x] 2.3 增加`OCR_LAYOUT_JSON` Representation kind、独立media type/schema/编码/大小规则，以及按processing run冻结Profile解析必需输出集合的领域类型和失败关闭校验。
- [x] 2.4 设计并实现`document_picture_asset`、`document_picture_occurrence`、`document_picture_processing_item`及必要attempt/staging/cleanup事实，加入tenant/source Version/run/Profile绑定、终态、唯一约束和并发claim字段。
- [x] 2.5 为parent processing run增加`PARENT_PARSE`、`PICTURE_OCR`、`ASSEMBLING`阶段和唯一assembly/outbox事实，保持既有公开run状态及历史记录解释不变。
- [x] 2.6 追加只做schema与约束变更的forward migration，覆盖新kind、Profile约束、表、索引、外键、检查约束和旧行兼容；migration不得访问对象存储、重写历史run或生成业务内容。
- [x] 2.7 实现asset/occurrence/item/attempt/outbox/staging/cleanup repository与事务方法，并以数据库唯一约束验证重复claim、重复完成和并发最后item只产生一个assembly。

## 3. Docling Provider与安全图片提取

- [x] 3.1 扩展Docling Provider的固定请求/响应合同，为新Profile启用DOCX/PPTX图片导出，同时保持HTTP source、remote services、custom config、插件、callback、VLM和运行时模型下载关闭。
- [x] 3.2 实现artifact bundle校验器，拒绝超响应/entry/解压总量、绝对路径、路径穿越、symlink、重复名、未知entry、未知媒体类型和picture ref不一致，并确保日志不含文件名、对象键或响应正文。
- [x] 3.3 将Docling结构结果映射为稳定picture occurrence：PPTX保存slide、picture self_ref与slide bbox，DOCX保存picture self_ref、可解析的最近父容器ref和同父顺序，禁止要求上游未提供的段落/单元ref或生成DOCX伪页码坐标。
- [x] 3.4 安全解码白名单PNG/JPEG/WebP，仅应用图片自身EXIF方向，不解析或应用Office显示层裁剪/旋转/翻转；记录`RAW_EMBEDDED_MEDIA_AFTER_EXIF`像素基准，移除非必要元数据并在模型调用前检查压缩大小、单图/累计像素和派生字节硬上限。
- [x] 3.5 生成规范化图片SHA-256，使OCR计算仅能在同一tenant/source Version/run/Profile内复用；为重复图片保留独立occurrence和父锚点，并测试禁止跨tenant内容探测或复用。
- [x] 3.6 实现绑定picture item的固定图片OCR提交、轮询和结果适配，保存引擎/model revision与digest但不把图片、OCR正文、坐标、文件名或外部响应写入数据库、消息、日志或审计。

## 4. File Service内部流与不可变表示

- [x] 4.1 在既有内部服务身份和scope下增加绑定parent run/item的picture asset上传、读取与item结果staging接口；接口不得接受或返回任意Bucket、对象键、URL、路径或用户提交的Profile options。
- [x] 4.2 保持File Service为唯一对象存储客户端，验证File Processing Worker和Docling镜像、环境与代码均不包含对象存储凭据或直接MinIO/S3客户端。
- [x] 4.3 实现picture asset原子staging与finalize，校验tenant/source/run/Profile/item、media type、规范化尺寸、size和SHA-256，并让asset字节计入派生配额但不计入工作区逻辑文件数。
- [x] 4.4 实现Profile驱动的Representation transfer/finalize：旧Profile必须齐备`MARKDOWN+DOCLING_JSON`，新Profile必须齐备`MARKDOWN+DOCLING_JSON+OCR_LAYOUT_JSON`，混用run/source/Profile或缺任一输出时失败关闭。
- [x] 4.5 为`enterprise-agent.office-image-ocr-layout/v1`实现canonical JSON schema校验，拒绝NaN/无穷、越界或反向bbox、未知坐标原点、未知状态/关系、超数量/字符/字节和无法应用的变换。
- [x] 4.6 实现source不可用、workspace到期、parent终态和孤立staging的生命周期处理；内容删除可重试且只保留允许的身份、哈希、provenance、状态和删除审计。

## 5. Parent、逐图任务与Assembly编排

- [x] 5.1 将parent handler拆为幂等`PARENT_PARSE`阶段：claim精确run、取得父正文/Docling JSON/bundle、通过File Service保存asset/occurrence/item，并在同一数据库事务生成唯一picture Outbox后ack消息。
- [x] 5.2 定义并验证版本化parent/picture/assembly RabbitMQ envelope，只允许稳定run/item/Profile hash/correlation/attempt身份，拒绝图片、Base64、OCR文字、坐标、文件名、对象键和凭据字段。
- [x] 5.3 实现picture item claim、受控asset流、Docling提交/轮询、坐标规范化和item终结；外部task丢失或Worker重启时在同一item有限重试且不重算其它终态item。
- [x] 5.4 实现软图片上限的稳定occurrence选择和`SKIPPED_LIMIT`、成功无文字的`NO_TEXT`、白名单错误的`FAILED`状态，确保硬安全上限在调用OCR和发布表示前拒绝。
- [x] 5.5 实现最后一个item终态后的唯一assembly Outbox与claim，覆盖重复完成、并发完成、消息重投、Worker崩溃和dead-letter恢复而不生成第二组Representation。
- [x] 5.6 实现parent的`SUCCEEDED`/`PARTIAL`/失败决策：个别图片软失败时发布完整有界结果并列出安全状态，任一必需输出无效或硬边界触发时不得发布截断前缀。

## 6. 布局规范化、关系与Markdown组装

- [x] 6.1 实现图片内部坐标转换为左上角原点`0..10000`整数bbox/polygon，保留原始/规范化尺寸、图片自身EXIF方向、`RAW_EMBEDDED_MEDIA_AFTER_EXIF`像素基准和未应用Office显示变换事实；未知或不可逆的图片自身变换必须失败关闭。
- [x] 6.2 生成稳定block/可选word ID、Unicode文字、`confidence_bp`和reading order，并对block、word、字符和低置信度实施Profile固定规则而不做无依据文本纠错。
- [x] 6.3 实现版本化确定性几何算法，只生成有界相邻/包含的`LEFT_OF`、`RIGHT_OF`、`ABOVE`、`BELOW`、`SAME_ROW`和`CONTAINS`，证明不会产生全量两两关系或箭头/因果/颜色语义。
- [x] 6.4 按稳定occurrence顺序组装canonical`OCR_LAYOUT_JSON`，绑定source File/Version、run、Profile hash、layout/Assembler version、父锚点、图片状态和空间结果。
- [x] 6.5 在父Markdown末尾追加固定“内嵌图片布局OCR”附录，包含锚点、坐标说明、reading order文字、置信度、允许关系和`NO_TEXT/SKIPPED_LIMIT/FAILED`状态，并明确非完整视觉理解、原始嵌入图片像素基准、未应用Office显示裁剪/旋转/翻转以及可能包含已裁掉区域。
- [x] 6.6 验证Assembler输出不含图片字节、Base64/data URI、对象键、内部task ID或不允许的业务标识，并把OCR提示注入始终标记和处理为不可信文件内容。

## 7. Publication、Manifest、Runtime与管理端

- [x] 7.1 扩展Business Application Draft/Revision/Publication schema和发布校验，冻结单一Profile code/version/hash；依赖或Profile hash未就绪时阻止新布局Publication，历史Publication保持原解释。
- [x] 7.2 更新管理端Profile选择与状态展示，准确说明布局OCR的文字/置信度/坐标/阅读顺序/几何关系能力、原始嵌入图片像素基准、未应用Office显示裁剪/旋转/翻转和非VLM边界，且不提供URL、模型、prompt、阈值或原始options输入。
- [x] 7.3 保持Job Manifest只冻结source File/Version与最终Markdown Representation ID/kind/size/SHA-256/安全物化名，增加拒绝OCR正文、坐标、asset ID、Docling JSON和OCR Layout JSON进入Manifest的测试。
- [x] 7.4 保持Runtime协议和沙盒物化逻辑只接收冻结Markdown，验证Office原件、picture asset和两种JSON没有`MATERIALIZE`动作且同源/同run不能放宽精确Representation绑定。
- [x] 7.5 更新Runtime文件能力说明与固定安全提示，把布局Markdown声明为不可信OCR数据，明确原始嵌入图片像素基准与Office显示变换未应用，且不具备箭头、颜色、图标、照片或完整视觉语义，确保内容不能改变Principal、Tool集合、网络或沙盒。
- [x] 7.6 验证原件Delivery仍按精确source Version交付DOCX/PPTX，布局Markdown、OCR Layout JSON和picture asset不得替代原件或获得编辑/提交动作。

## 8. 部署、就绪与安全观测

- [x] 8.1 将固定OCR/layout模型artifact及revision/digest纳入受控镜像构建或部署资产，增加离线存在性和digest校验，运行时缺失时失败就绪且不得联网下载或回退模型。
- [x] 8.2 更新受影响服务的Compose/环境示例和最小挂载/网络/Secret边界，不引入新Agent Tool、新MCP、新对象入口或Docling公网暴露，并通过Compose安全边界测试。
- [x] 8.3 扩展readiness，联合验证Profile registry/hash、layout schema、必需输出集合、模型artifact、File Service内部流、RabbitMQ拓扑和Docling真实合同；禁止以容器running替代契约就绪。
- [x] 8.4 增加parent parse、picture item、assembly、asset/Representation staging、retry、dead-letter和cleanup的有界积压/最早时间/Profile/stage/attempt/安全错误指标，禁止记录业务文件名、图片、OCR文字、坐标、对象键、正文或凭据。
- [x] 8.5 编写布局OCR运维与回滚步骤：停止激活新Profile、排空或安全终结队列、保留历史事实和schema、切回既有Profile；禁止down-migrate或把新run降级解释为旧Profile。

## 9. 自动化测试与新鲜链路验收

- [x] 9.1 为Profile完整超集、canonical hash、必需输出集合、Publication单选、历史兼容和拒绝任意options补齐领域/应用单元测试。
- [x] 9.2 为bundle拒绝、路径边界、图片解码、图片自身EXIF、原始像素基准、Office显示变换未应用、坐标规范化、canonical JSON、reading order、关系上限和确定hash补齐fixture与属性边界测试。
- [x] 9.3 为repository/migration/File Service内部流、配额、生命周期、Profile驱动finalize、唯一assembly和跨tenant隔离补齐数据库及集成测试。
- [x] 9.4 为parent/picture/assembly消息重投、Docling task丢失、Worker崩溃、部分成功、无文字、软/硬上限、dead-letter和清理补齐Worker集成测试。
- [x] 9.5 使用合成DOCX/PPTX执行固定Provider合同测试，覆盖重复图片、已知PPTX slide/shape bbox、DOCX稳定节点锚点、图片自身EXIF、Office显示层裁剪/旋转仍导出原始像素且结果明确提示、低置信度、多block、损坏图片和提示注入。
- [x] 9.6 运行受影响后端测试、migration tests、静态检查、管理端测试/build、Compose配置/安全测试和`git diff --check`，修复全部回归并记录不含敏感数据的证据。
- [x] 9.7 在新建验收Publication上完成附件入站→parent/逐图/assembly→三种Representation→Manifest→Runtime Markdown读取→Agent回答→原件Delivery的新鲜E2E，证明Agent只陈述文字/布局边界且全链幂等、隔离、可清理。
- [x] 9.8 执行`openspec validate add-governed-office-embedded-image-layout-ocr --strict`并复核全部任务证据；仅在固定上限、模型digest、Profile hash、readiness和新鲜E2E均通过后允许目标Publication激活。

## 10. Docling 1.30.0 真实置信度合同修正

- [x] 10.1 记录新鲜DOCX链路中7个`docling_picture_confidence_missing`和1个结构错误的非敏感证据，明确父解析、图片导出、逐图HTTP成功与适配失败边界。
- [x] 10.2 新增不可变`docling-layout-ocr-v2`、布局/picture-result Schema v2、Profile hash与forward migration；保留v1 code/version/hash和历史解释，新Publication不得再选择v1。
- [x] 10.3 v2仅在上游提供逐block置信度时规范化数值，缺失时保存`null`并在Markdown显示“上游未提供”；确定成功且无文字时生成`NO_TEXT`，非空结构、provenance、bbox或坐标异常仍失败关闭并使用安全细分错误码。
- [x] 10.4 让Provider、Worker、Repository、readiness和清理按冻结Profile解析v1/v2，证明历史v1不变且v2不会混用v1布局结果。
- [x] 10.5 补齐Profile、migration、Provider、适配、Worker、File Service、Publication和管理端回归，运行受影响测试/build、Compose校验、`git diff --check`与OpenSpec严格校验。
- [x] 10.6 重建受影响服务，使用新建v2验收Publication完成同一DOCX的真实逐图、三Representation、Manifest、Runtime读取、Agent回答和原件Delivery E2E；确认不再把缺失置信度判为整图失败。
