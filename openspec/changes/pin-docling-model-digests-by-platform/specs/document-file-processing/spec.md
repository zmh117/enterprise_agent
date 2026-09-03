## MODIFIED Requirements

### Requirement: 布局OCR只通过代码发布Profile启用
系统 MUST 只允许代码发布且可审计的`docling-layout-ocr-v2`启用布局OCR。该Profile MUST 完整固定PDF、DOCX、PPTX、XLSX、PNG、JPEG和WebP的正文、表格、图片OCR、布局输出、处理器/模型revision、模型摘要算法、固定OCI index以及每个受支持平台的子manifest与模型artifact digest、坐标Schema、关系算法、资源上限和安全关闭项；完整平台映射 MUST 进入canonical payload，使同一发布在所有受支持平台生成相同Profile hash。运行时 MUST 只按规范化后的本机平台选择映射中的精确条目并校验实际artifact；用户消息、Agent、管理端和环境变量不得提交或覆盖原始Docling、OCR、模型、摘要或运行时options。

#### Scenario: 新Publication选择当前布局OCR
- **WHEN** Business Application Publication冻结`docling-layout-ocr-v2`
- **THEN** 平台按照该Profile固定的父文档解析、图片提取、图片OCR和三种必需输出创建processing run
- **AND** 不动态组合、继承或回退到已删除Profile

#### Scenario: 同一Profile运行于两个受支持平台
- **WHEN** 同一代码发布分别运行于`linux/amd64`与`linux/arm64`
- **THEN** 两端使用包含完整平台映射的相同canonical payload与Profile hash
- **AND** 每端只选择并校验自身平台对应的子manifest和模型artifact digest

#### Scenario: 当前平台没有受信条目
- **WHEN** 运行时OS/架构无法规范化为受支持平台或Profile映射缺少当前平台
- **THEN** Docling与Worker readiness失败且不得创建或执行布局OCR processing run
- **AND** 不回退到其它平台、环境变量、现场实算值或运行时下载

#### Scenario: 请求视觉语义或任意模型
- **WHEN** 用户、Agent或管理端要求识别栅格箭头、颜色、图标、照片语义、精确图表因果，或提交远程/自定义模型配置
- **THEN** 系统保持布局OCR能力边界并拒绝扩大Profile
- **AND** 不调用VLM、远程图片描述、外部插件或运行时模型下载
