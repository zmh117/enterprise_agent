# document-file-processing Specification

## Purpose
定义受治理文档处理 Profile、不可变处理运行与派生表示的身份、异步编排、隔离、恢复和生命周期边界。

## Requirements

### Requirement: 文档处理只使用代码发布的固定Profile
系统 MUST 只允许代码发布且可审计的文档处理Profile；当前唯一启用Profile SHALL 为`docling-layout-ocr-v2`，其输入白名单为PDF、DOCX、PPTX、XLSX、PNG、JPEG和WebP，输出固定为Markdown、Docling JSON与OCR Layout JSON。该Profile MUST 开启有界OCR和表格结构提取，MUST 关闭VLM、图片语义描述、远程服务、HTTP URL Source、Callback、自定义模型配置和外部插件。
#### Scenario: 已发布应用选择Docling文字Profile
- **WHEN** Job固定的Business Application Publication选择`docling-layout-ocr-v2`
- **THEN** 平台按照该Profile冻结的输入、输出、资源上限和安全选项创建处理任务
- **AND** 用户消息、Agent或管理端不能覆盖这些选项
#### Scenario: 请求图片语义理解
- **WHEN** 用户要求理解无文字架构图、仪表盘或普通照片的视觉含义
- **THEN** 第一阶段只返回OCR文字能力边界或无可用文字状态
- **AND** 系统不调用VLM、不生成虚构视觉描述
#### Scenario: Docling请求携带远程来源
- **WHEN** 任一调用尝试提交HTTP URL、Callback、远程模型或外部插件配置
- **THEN** Provider在调用Docling前拒绝请求并记录安全错误码

### Requirement: 精确源版本产生不可变处理运行
系统 SHALL 为一个精确File Version和一个精确处理器build/Profile组合创建`file_processing_run`。运行 MUST 冻结tenant、source File/Version、processor code/version、镜像digest、Profile code/hash和创建来源；状态 SHALL 受控为`QUEUED`、`SUBMITTED`、`RUNNING`、`RETRY_WAIT`、`SUCCEEDED`、`PARTIAL`、`NO_TEXT`或`FAILED`，终态运行不得原地重置或改绑到其它源版本。
#### Scenario: 同一源版本重复收到处理事件
- **WHEN** 相同source Version、processor build digest和Profile hash被重复请求
- **THEN** 系统复用同一逻辑processing run或其确定终态
- **AND** 不创建重复的可用表示
#### Scenario: Docling版本升级
- **WHEN** 相同source Version改用新的processor version或镜像digest处理
- **THEN** 系统创建新的processing run并保留旧run及其provenance
- **AND** 旧Job继续使用已经冻结的旧表示
#### Scenario: 终态运行被改绑
- **WHEN** 调用方尝试把已终态run改绑到另一source Version或Profile hash
- **THEN** 系统在产生对象或状态副作用前拒绝

### Requirement: 派生表示独立于原始文件版本
系统 MUST 用`file_representation`保存processing run产生的`MARKDOWN`和`DOCLING_JSON`事实，并记录精确source Version、kind、media type、encoding、size、SHA-256、内部对象位置、状态和内容生命周期。Representation MUST NOT成为原文件的新File Version、当前版本或可交付原件，也 MUST NOT改变原文件的display name、media type或current version pointer。
#### Scenario: PDF转换成功
- **WHEN** 一个PDF source Version成功生成Markdown与Docling JSON
- **THEN** File Service为同一run创建两个不可变representation并保持PDF current Version不变
- **AND** 原件交付仍返回PDF而不是Markdown
#### Scenario: 新处理运行产生不同结果
- **WHEN** 新processor build为同一source Version产生新的Markdown
- **THEN** 系统创建新的representation身份且不覆盖旧对象或旧hash
#### Scenario: Agent请求交付Representation
- **WHEN** Agent尝试把只读Markdown representation作为原始Office/PDF文件交付
- **THEN** File Service拒绝混淆身份并要求选择受授权原始File Version或显式生成的新文本文件

### Requirement: 文档处理通过持久Outbox和RabbitMQ编排
File Service SHALL 在原件版本和processing run事务提交时写入唯一`file.processing.requested` Outbox；Dispatcher MUST 使用RabbitMQ发布只含稳定ID、Profile hash和correlation ID的消息。独立`file-processing-worker` MUST claim run、通过File Service流式读取精确原件、调用固定Docling Provider并在本地终态提交后才确认消息。
#### Scenario: RabbitMQ发布暂时失败
- **WHEN** source Version与processing run已提交但RabbitMQ不可用
- **THEN** Outbox保持可恢复状态并有限退避
- **AND** 不丢失run、不在消息中复制文件字节或对象位置
#### Scenario: Worker在Docling完成后崩溃
- **WHEN** Docling已经完成但Worker尚未发布representations即退出
- **THEN** 未确认消息被重新消费且同一run继续恢复或重算
- **AND** 幂等约束阻止重复可用表示
#### Scenario: 消息尝试携带文件内容
- **WHEN** processing queue payload包含正文、Base64、对象键、文件名、凭据或可访问URL
- **THEN** 发布器拒绝该payload并记录不含敏感值的契约错误

### Requirement: Docling异步任务丢失时按同一运行恢复
`file-processing-worker` SHALL 使用Docling v1 multipart异步接口提交、持久化外部task ID、有限轮询状态并在成功后获取一次结果。Docling重启、task不存在、结果已清理或连接中断时，系统 MUST 根据错误分类在同一processing run创建下一attempt或进入确定失败；不得把Docling task registry当成平台事实源。
#### Scenario: Docling重启后task不存在
- **WHEN** run保存的外部task ID在Docling返回不存在且run仍可重试
- **THEN** Worker清除该attempt的外部task绑定、有限退避并重新提交同一source Version和Profile
- **AND** run身份与Job引用保持不变
#### Scenario: 结果只允许读取一次
- **WHEN** Worker成功取得Docling结果
- **THEN** Worker立即把结果写入File Service受控staging并继续终结
- **AND** 不依赖稍后再次读取Docling临时结果完成恢复
#### Scenario: 重试耗尽
- **WHEN** 瞬时错误达到Profile固定的最大attempt或处理deadline
- **THEN** run进入`FAILED`并保存白名单错误码
- **AND** 不保存原始异常、响应正文或凭据

### Requirement: Representation使用两阶段流式发布
File Service MUST 为每个run和representation kind创建绑定身份的不透明staging transfer，在流式接收时计算SHA-256并校验Markdown UTF-8、JSON结构、media type和独立大小上限。只有`docling-layout-ocr-v2`要求的Markdown、Docling JSON与OCR Layout JSON均完整时，系统才能在数据库事务中发布可见representation、更新run终态并写完成Outbox；对象存在本身不得表示内容可用。
#### Scenario: Markdown上传完成但JSON失败
- **WHEN** Markdown staging完整而Docling JSON上传或校验失败
- **THEN** 系统不发布任一AVAILABLE representation
- **AND** 已写staging进入可重试清理或同run恢复
#### Scenario: 相同内容重试终结
- **WHEN** 相同run、kind、transfer元数据和SHA-256被重试
- **THEN** File Service返回同一representation ID或相同终结结果
- **AND** 不创建第二个对象事实
#### Scenario: Markdown超过15MiB
- **WHEN** Docling Markdown超过Profile固定的15MiB Agent可读上限
- **THEN** 系统完整拒绝该结果并使run安全失败
- **AND** 不静默截断、不把前缀物化给Agent

### Requirement: 部分成功与无文字具有确定语义
系统 SHALL 把Docling单文档结果映射为平台稳定状态：存在通过校验的非空Markdown但处理器报告不完整时为`PARTIAL`，成功但没有可用OCR/文本内容时为`NO_TEXT`，没有可发布Markdown时为`FAILED`。`PARTIAL` MAY 发布带完整性notice的表示；`NO_TEXT`和`FAILED` MUST NOT创建可供Agent假装阅读的Markdown表示。
#### Scenario: 扫描PDF部分页面失败
- **WHEN** Docling返回partial success且存在通过校验的非空Markdown
- **THEN** run进入`PARTIAL`并发布冻结表示
- **AND** Job上下文包含固定的内容可能不完整notice
#### Scenario: 图片没有任何文字
- **WHEN** OCR成功执行但没有产生可用文字
- **THEN** run进入`NO_TEXT`且不生成虚构Markdown正文
#### Scenario: 加密或损坏文档
- **WHEN** Docling确认文档加密、损坏或不符合固定格式
- **THEN** run进入非重试`FAILED`并返回安全错误分类

### Requirement: 文档处理组件遵守文件与凭据隔离
只有File Service基础设施层可以解析MinIO凭据和对象键。`file-processing-worker` MUST 只通过绑定run/source Version的内部流式接口收发内容；`docling-serve` MUST 不获得PostgreSQL、RabbitMQ、MinIO、平台Principal或业务应用凭据。完整原件和表示不得进入MCP JSON、Agent消息、日志、审计或RabbitMQ。
#### Scenario: Processing Worker环境被检查
- **WHEN** 运维检查`file-processing-worker`容器环境、Secret和挂载
- **THEN** 仅存在其角色bootstrap credential、RabbitMQ配置和Docling API Key
- **AND** 不存在MinIO Secret、对象键、签名私钥或其它Worker凭据
#### Scenario: Docling容器环境被检查
- **WHEN** 运维检查`docling-serve`容器
- **THEN** 它只有自身固定配置与API Key校验材料
- **AND** 不具有平台数据库、消息总线、对象存储或Principal访问能力
#### Scenario: 处理日志记录业务内容
- **WHEN** 文件名、Markdown、JSON、原始错误或文件字节准备写入日志或审计
- **THEN** 系统阻止该字段并只保留run ID、版本、Profile、大小、耗时、状态和白名单错误码
#### Scenario: 内部原件导入返回安全拒绝
- **WHEN** File Service拒绝File Worker提交的原件流
- **THEN** 响应只包含有界安全消息和稳定白名单`error_code`，File Worker只持久化机器码
- **AND** File Worker不复制原始响应正文、内部异常、文件名或文件内容到失败事实和审计

### Requirement: Representation生命周期不得扩大原件访问
Representation MUST 继承source Version的tenant、owner和访问边界，不得比source内容更晚可用。任务工作区到期且不存在非终态Job或processing run依赖时，派生内容 SHALL 进入可重试清理；清理后 MAY 保留run、hash、processor provenance和删除审计，但 MUST NOT恢复、物化或返回已删除内容。
#### Scenario: 工作区到期但Job仍在等待处理
- **WHEN** representation所属工作区到期但关联Job或processing run仍非终态
- **THEN** 清理暂缓到依赖进入终态
- **AND** 不修改原工作区到期时间
#### Scenario: 原件内容先被清理
- **WHEN** source Version已经`CONTENT_UNAVAILABLE`或`DELETED`
- **THEN** 所有对应representation不再可物化并进入清理
#### Scenario: Representation对象删除暂时失败
- **WHEN** MinIO删除发生瞬时错误
- **THEN** 数据库保持`CONTENT_UNAVAILABLE`及待清理事实并有限重试
- **AND** API和Runtime不得因对象暂时仍存在而返回内容

<!-- Integrated from archived change: `2026-08-23-add-governed-office-embedded-image-layout-ocr/specs/office-embedded-image-layout-ocr` -->

### Requirement: 布局OCR只通过代码发布Profile启用
系统 MUST 只允许代码发布且可审计的`docling-layout-ocr-v2`启用布局OCR。该Profile MUST 完整固定PDF、DOCX、PPTX、XLSX、PNG、JPEG和WebP的正文、表格、图片OCR、布局输出、处理器/模型revision与digest、坐标Schema、关系算法、资源上限和安全关闭项；用户消息、Agent、管理端和环境变量不得提交原始Docling、OCR、模型或运行时options。

#### Scenario: 新Publication选择当前布局OCR
- **WHEN** Business Application Publication冻结`docling-layout-ocr-v2`
- **THEN** 平台按照该Profile固定的父文档解析、图片提取、图片OCR和三种必需输出创建processing run
- **AND** 不动态组合、继承或回退到已删除Profile

#### Scenario: 请求视觉语义或任意模型
- **WHEN** 用户、Agent或管理端要求识别栅格箭头、颜色、图标、照片语义、精确图表因果，或提交远程/自定义模型配置
- **THEN** 系统保持布局OCR能力边界并拒绝扩大Profile
- **AND** 不调用VLM、远程图片描述、外部插件或运行时模型下载

### Requirement: Office内嵌图片使用稳定派生身份和双坐标空间
系统 SHALL 从精确DOCX/PPTX source Version的Docling结构结果中为每个内嵌栅格图片创建稳定picture occurrence，并 MUST 把可复用的规范化图片asset与其一个或多个父文档出现位置分开建模。PPTX父锚点 MUST 包含slide、Docling picture `self_ref`形成的稳定shape/ref及图片在slide中的规范化bbox；DOCX父锚点 MUST 包含稳定picture `self_ref`、Docling返回且可解析的最近父容器ref（段落、表格单元、section或body）及同父节点顺序，且 MUST NOT 要求上游未提供的段落/单元ref或声称存在跨渲染环境稳定的页码坐标。图片内部OCR坐标 MUST 使用左上角原点、`0..10000`整数空间，并保留原始/规范化尺寸、图片自身EXIF方向及`RAW_EMBEDDED_MEDIA_AFTER_EXIF`像素基准。系统 MUST 使用Office包内原始嵌入图片，不应用或声称应用Office显示层裁剪、旋转或翻转。

#### Scenario: PPTX图片包含文字
- **WHEN** PPTX第4张slide中的一个picture shape被安全提取并完成OCR
- **THEN** 系统保存slide/shape父锚点、图片在slide中的bbox以及OCR block在图片内部的规范化坐标
- **AND** 两种坐标必须具有不同字段和明确坐标系

#### Scenario: DOCX图片没有稳定页坐标
- **WHEN** DOCX内联图片只有稳定picture ref、可解析的section/body等父容器和顺序关系
- **THEN** 系统保存该文档节点/父容器/顺序锚点及图片内部OCR坐标
- **AND** 不通过字体依赖渲染伪造页码或页面bbox

#### Scenario: 相同图片重复出现
- **WHEN** 相同规范化图片内容在同一source Version中出现多次
- **THEN** 系统可以在同一tenant/source/run/Profile边界内按SHA-256复用一次OCR计算
- **AND** 每个出现位置仍保存独立occurrence、顺序和父锚点

#### Scenario: Office显示层裁剪或旋转图片
- **WHEN** PPTX或DOCX只在DrawingML显示层裁剪、旋转或翻转一张内嵌图片
- **THEN** OCR仍使用Office包内原始嵌入图片并仅规范化图片自身EXIF方向
- **AND** 布局JSON、Markdown、管理端与Runtime能力说明必须明确未应用Office显示变换且结果可能包含页面上已裁掉区域

<!-- Integrated from archived change: `2026-08-23-add-governed-office-embedded-image-layout-ocr/specs/office-embedded-image-layout-ocr` -->

### Requirement: OCR布局使用版本化不可变Schema
系统 MUST 为`docling-layout-ocr-v2`发布符合`enterprise-agent.office-image-ocr-layout/v2`的不可变`OCR_LAYOUT_JSON` Representation。v2 Schema MUST 绑定精确source File/Version、processing run、Profile hash、layout/Assembler version，并为所有图片occurrence保存图片摘要、父锚点、状态以及有界OCR block；每个block MUST 保存稳定局部ID、Unicode文字、`confidence_bp`、`reading_order`、规范化bbox和可选polygon。`confidence_bp` MUST 为上游明确提供并规范化后的`0..10000`整数，或在上游未提供逐block置信度时为JSON `null`；系统不得复制聚合置信度或生成默认值。若Profile包含word级结果，word MUST 受独立数量/字符上限约束并保持block归属。完整OCR文字和坐标 MUST 保存在File Service管理的私有对象中，PostgreSQL不得逐block/word保存正文。

#### Scenario: 上游未提供逐block置信度
- **WHEN** 固定Docling成功返回合规文字、provenance和bbox但没有逐block`confidence`
- **THEN** v2布局结果保留文字与坐标并把`confidence_bp`保存为`null`
- **AND** Markdown明确“置信度=上游未提供”，不把图片标记为`FAILED`且不发明数值

#### Scenario: OCR布局终结成功
- **WHEN** 同一run的全部有界图片item已经进入确定终态且Assembler生成合规布局JSON
- **THEN** File Service校验schema、身份、UTF-8、大小和SHA-256后发布一个`OCR_LAYOUT_JSON` Representation
- **AND** 该对象不得成为File Version、可交付原件或Agent可物化内容

#### Scenario: 坐标不符合规范
- **WHEN** OCR结果包含NaN、无穷值、越界值、反向bbox、未知原点或无法应用的图片自身EXIF方向变换
- **THEN** Provider在发布布局表示前失败关闭对应item
- **AND** 不猜测、夹断或静默改用引擎原始坐标

#### Scenario: OCR正文准备写入关系数据库
- **WHEN** 持久化流程尝试把block/word文字或完整布局JSON写入PostgreSQL、RabbitMQ、日志或审计
- **THEN** 系统拒绝该字段并只保存稳定身份、状态、大小、哈希、版本和安全错误码

<!-- Integrated from archived change: `2026-08-23-add-governed-office-embedded-image-layout-ocr/specs/office-embedded-image-layout-ocr` -->

### Requirement: 空间关系由确定性有界算法产生
系统 SHALL 以Profile固定版本的确定性算法，根据OCR bbox/polygon、文字方向、行高、重叠比例和reading order生成`LEFT_OF`、`RIGHT_OF`、`ABOVE`、`BELOW`、`SAME_ROW`和`CONTAINS`关系。系统 MUST 只生成Profile允许的相邻/包含关系并实施每block和每图片关系上限，不得把几何关系命名为流程边、箭头、因果、颜色或图形语义。

#### Scenario: 两个文字块同处一行
- **WHEN** 两个合规block满足Profile固定的同基线与间距规则
- **THEN** 系统以稳定顺序生成`SAME_ROW`及相应左右关系
- **AND** 相同输入、Profile和算法version必须产生相同canonical结果和hash

#### Scenario: 关系数量可能平方增长
- **WHEN** 一张图片包含大量OCR block
- **THEN** 系统只保留有界相邻/包含关系并在达到Profile上限前停止新增关系
- **AND** 不执行或持久化全量两两关系

#### Scenario: 文字位置类似流程图
- **WHEN** OCR block在空间上呈现左右或上下排列但没有受治理的连接器事实
- **THEN** 系统只输出几何关系
- **AND** 不声称识别到流程方向或节点因果

<!-- Integrated from archived change: `2026-08-23-add-governed-office-embedded-image-layout-ocr/specs/office-embedded-image-layout-ocr` -->

### Requirement: 父处理运行和逐图OCR保持持久幂等
系统 SHALL 在父`file_processing_run`下持久化图片asset、occurrence和picture processing item，并通过File Domain Outbox与版本化RabbitMQ消息分别编排父解析、逐图OCR和最终assembly。消息 MUST 只携带run/item/Profile hash/correlation/attempt等稳定身份；图片字节、Base64、OCR文字、坐标、文件名、对象键和凭据不得进入消息。Docling外部task丢失或Worker重启时，系统 MUST 在同一parent/item身份下有限重试，且不得发布重复asset、item或Representation。

#### Scenario: 父解析后Worker退出
- **WHEN** parent已经保存picture item与唯一子任务Outbox但Worker在ack前退出
- **THEN** 重试复用相同run/item并幂等发布缺失消息
- **AND** 不重复导入source Version或创建第二套occurrence

#### Scenario: 单张图片OCR任务丢失
- **WHEN** Docling重启后某picture item保存的外部task ID不存在
- **THEN** Worker按该item固定attempt策略重新提交同一asset与Profile
- **AND** 其它已终态图片item不重算、不回滚

#### Scenario: 最后一个图片完成
- **WHEN** parent下所有picture item进入`AVAILABLE`、`NO_TEXT`、`SKIPPED_LIMIT`或`FAILED`
- **THEN** 系统只写一个assembly Outbox并按稳定occurrence顺序生成最终输出
- **AND** 重复完成事件不得创建第二个assembly或重复Representation

<!-- Integrated from archived change: `2026-08-23-add-governed-office-embedded-image-layout-ocr/specs/office-embedded-image-layout-ocr` -->

### Requirement: Agent只读取布局增强Markdown
系统 MUST 由版本化确定性Assembler把父文档Markdown与布局OCR附录合并为同一份最终Markdown。附录 SHALL 为每张图片列出父锚点、坐标系、按reading order排序的有界block、上游提供时的置信度等级或明确的置信度不可用标记、允许的空间关系和确定状态，并 MUST 明确结果为布局OCR而非完整视觉理解。附录 MUST 同时声明像素基准为应用图片自身EXIF后的原始嵌入图片、未应用Office显示裁剪/旋转/翻转且可能包含页面上已裁掉区域。Manifest与Runtime只能冻结和物化该Markdown Representation；Office原件、图片asset、Docling JSON和`OCR_LAYOUT_JSON`不得进入Job Sandbox、MCP JSON或初始conversation context。

#### Scenario: Agent分析带截图的PPTX
- **WHEN** Job Manifest冻结PPTX source Version及`docling-layout-ocr-v2`生成的最终Markdown
- **THEN** Runtime只物化Markdown且Agent可以通过Read、Grep或Glob读取图片文字和空间关系
- **AND** Runtime协议不新增图片content block或原图传输

#### Scenario: 低置信度OCR文字
- **WHEN** block的`confidence_bp`低于Profile固定阈值
- **THEN** Markdown必须标记低置信度并保留机器提取字面值
- **AND** Assembler不得自动改写成看似确定的内容

#### Scenario: 成功图片没有可提取文字
- **WHEN** Docling返回`success`、没有errors且该图片Markdown为空
- **THEN** v2 item进入`NO_TEXT`并生成没有block的合规结果
- **AND** 不因缺少可消费的文字结构把图片记为`FAILED`，也不声称图片没有视觉含义

#### Scenario: 尝试物化布局JSON或图片
- **WHEN** Agent或Runtime请求物化`OCR_LAYOUT_JSON`、Docling JSON、Office原件或picture asset
- **THEN** File Service在返回字节前拒绝
- **AND** 同源或同run关系不得扩大MATERIALIZE动作

<!-- Integrated from archived change: `2026-08-23-add-governed-office-embedded-image-layout-ocr/specs/office-embedded-image-layout-ocr` -->

### Requirement: 图片上限和部分成功不得静默
Profile MUST 分别限制Office结构与图片数量、单图压缩大小、单图/累计解码像素、word/block/关系/字符数量、picture asset与三种最终Representation字节、attempt、deadline和并发。图片OCR成功但没有文字时item SHALL 为`NO_TEXT`且不得生成虚构正文；个别图片失败或因软处理上限未处理、但父正文与必需表示仍然有效时，parent SHALL 发布完整有界结果并标记为`PARTIAL`，同时在布局JSON和Markdown明确图片序号与安全状态。触发格式、解压、像素或其它安全硬上限时 MUST 在模型调用和可见表示前确定拒绝。

#### Scenario: 部分图片OCR失败
- **WHEN** 父正文有效且十张内嵌图片中一张OCR确定失败
- **THEN** 系统发布其余完整结果并把parent标记为`PARTIAL`
- **AND** Markdown明确该图片未完成且不得声称完整理解文档图片

#### Scenario: 图片没有文字
- **WHEN** 一张图片成功完成OCR但没有产生合规block
- **THEN** item进入`NO_TEXT`且Markdown说明未提取到文字
- **AND** 不把无文字等同于无视觉含义或处理失败

#### Scenario: 图片数超过软处理上限
- **WHEN** 合规Office文档的图片数超过Profile固定软处理上限但未触发安全硬上限
- **THEN** 系统按稳定occurrence顺序处理有界集合并把其余item标记为`SKIPPED_LIMIT`
- **AND** parent进入`PARTIAL`且不得静默截断

<!-- Integrated from archived change: `2026-08-23-add-governed-office-embedded-image-layout-ocr/specs/office-embedded-image-layout-ocr` -->

### Requirement: 图片派生内容继承访问与生命周期
picture asset、item输出、`OCR_LAYOUT_JSON`和布局增强Markdown MUST 继承source Version的tenant、owner、workspace、授权与内容生命周期，不得比source内容更晚可用。只有File Service可以解析对象存储凭据并读写picture asset和Representation；picture asset只用于处理恢复，parent终态发布后 SHALL 进入可重试内容清理且不得向Agent或用户返回。清理后系统 SHALL 仅保留稳定身份、哈希、Profile/处理器provenance、状态和删除审计，不得保留OCR正文或恢复已清理图片。

#### Scenario: 原件内容不可用
- **WHEN** source Version变为`CONTENT_UNAVAILABLE`或`DELETED`
- **THEN** 对应picture asset和三种Representation必须停止物化并进入清理
- **AND** 既有Job冻结事实不得恢复内容访问

#### Scenario: Parent终态后清理图片asset
- **WHEN** parent三种Representation已经原子发布且不存在非终态picture item
- **THEN** File Service把处理用picture asset内容置为不可用并由生命周期Worker重试删除对象
- **AND** 保留occurrence、hash和provenance供审计而不保留图片字节

#### Scenario: OCR文字包含提示注入
- **WHEN** 图片文字要求Agent忽略系统规则、调用未授权Tool或访问网络
- **THEN** Runtime和Agent必须把布局Markdown视为不可信文件数据
- **AND** 内容不得改变Tool可见性、Principal、授权、网络或沙盒边界
