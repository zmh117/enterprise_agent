## ADDED Requirements

### Requirement: 布局OCR派生表示与原件保持不同身份
File Service MUST 把`docling-layout-ocr-v1`或`docling-layout-ocr-v2`产生的`MARKDOWN`、`DOCLING_JSON`和`OCR_LAYOUT_JSON`保存为绑定同一精确source Version与processing run的不同不可变Representation；各run必须严格使用其冻结Profile对应的Schema，不得混用v1/v2结果。只有最终Markdown SHALL 具有受控`MATERIALIZE`动作；Docling JSON、OCR Layout JSON、picture asset和Office原件不得进入Agent Sandbox、成为File Version、改变current version、获得编辑/提交动作或作为原件交付。

#### Scenario: Job使用布局增强Markdown
- **WHEN** Job Manifest冻结Office source Version及布局Profile的最终Markdown Representation
- **THEN** Runtime物化Markdown并保留原件File/Version身份用于授权、保留和Delivery
- **AND** 不物化另外两种JSON或图片asset

#### Scenario: 用户要求转发原始PPTX
- **WHEN** 用户要求交付具有DELIVER动作的精确PPTX source Version
- **THEN** Delivery通过File Service发送PPTX原件
- **AND** 不发送布局Markdown、OCR Layout JSON或内嵌图片asset

### Requirement: Job Manifest继续只冻结Agent可读Markdown
需布局OCR的Manifest条目 MUST 冻结原始File/Version ID及最终Markdown Representation ID、kind、size、SHA-256和安全物化名；MUST NOT包含OCR正文、坐标、picture asset ID、对象键、Base64、Docling JSON或OCR Layout JSON。Manifest冻结身份但不冻结授权，物化时 MUST 重新复核source与Representation访问权。布局Profile不得要求Runtime协议新增图片或JSON content类型。

#### Scenario: 本轮布局OCR已经可用
- **WHEN** 本轮Office附件的布局Profile run已`SUCCEEDED`或具有合规Markdown的`PARTIAL`
- **THEN** Manifest冻结精确最终Markdown并按既有规则自动或按需物化
- **AND** 同一run的其它Representation只保留为不可物化事实

#### Scenario: 模型替换Markdown表示
- **WHEN** 模型或Runtime尝试用同run的OCR Layout JSON、Docling JSON或另一run的Markdown替换Manifest冻结表示
- **THEN** File Service在返回内容前拒绝
- **AND** 不因Profile或source相同而放宽精确Representation绑定

### Requirement: 图片派生资产和布局输出受工作区配额与清理约束
picture asset、item staging、OCR Layout JSON、Docling JSON和布局增强Markdown的实际字节 MUST 计入相应布局OCR Profile固定的派生内容配额；picture occurrence和asset不得占任务工作区逻辑文件名额。新提取、OCR或终结会突破任一冻结上限时 MUST 在发布可见Representation前拒绝或按Profile定义的明确PARTIAL路径终结，不得留下错误可见性。工作区到期或source内容不可用后，图片asset和布局派生内容 MUST 按既有非终态依赖、保留与可重试清理规则处理。

#### Scenario: 一份PPTX包含多张内嵌图片
- **WHEN** File Service为同一PPTX创建多个picture occurrence与处理asset
- **THEN** 工作区逻辑文件计数仍只计算PPTX原件一次
- **AND** 所有asset、staging和最终表示字节计入派生内容配额

#### Scenario: 派生内容将超过配额
- **WHEN** 下一个picture asset或最终OCR Layout JSON会使run/workspace超过冻结字节上限
- **THEN** File Service不发布超限对象或错误Representation事实
- **AND** processing run记录稳定安全错误或Profile规定的明确PARTIAL状态

#### Scenario: 工作区到期但图片item未终态
- **WHEN** 工作区到期而关联layout OCR parent或picture item仍非终态
- **THEN** 清理暂缓到处理进入终态且不延长原工作区到期时间
- **AND** 终态后立即按source/representation生命周期执行清理
