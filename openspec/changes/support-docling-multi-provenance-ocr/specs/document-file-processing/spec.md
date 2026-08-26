## MODIFIED Requirements

### Requirement: OCR布局使用版本化不可变Schema
系统 MUST 为`docling-layout-ocr-v2`发布符合`enterprise-agent.office-image-ocr-layout/v2`的不可变`OCR_LAYOUT_JSON` Representation。v2 Schema MUST 绑定精确source File/Version、processing run、Profile hash、layout/Assembler version，并为所有图片occurrence保存图片摘要、父锚点、状态以及有界OCR block；每个block MUST 保存稳定局部ID、Unicode文字、`confidence_bp`、`reading_order`、规范化bbox和可选polygon。`confidence_bp` MUST 为上游明确提供并规范化后的`0..10000`整数，或在上游未提供逐block置信度时为JSON `null`；系统不得复制聚合置信度或生成默认值。若固定Docling的一个非空text item包含多个provenance，系统 MUST 只在每个provenance均提供合法且无重叠的`charspan`和bbox、全部非空白文字恰好被覆盖时，按text item顺序及`charspan`顺序确定性展开为多个block；字符上限 MUST 按原text item完整文字累计一次，block上限 MUST 应用于展开后的最终block集合。若Profile包含word级结果，word MUST 受独立数量/字符上限约束并保持block归属。完整OCR文字和坐标 MUST 保存在File Service管理的私有对象中，PostgreSQL不得逐block/word保存正文。

#### Scenario: 上游未提供逐block置信度
- **WHEN** 固定Docling成功返回合规文字、provenance和bbox但没有逐block`confidence`
- **THEN** v2布局结果保留文字与坐标并把`confidence_bp`保存为`null`
- **AND** Markdown明确“置信度=上游未提供”，不把图片标记为`FAILED`且不发明数值

#### Scenario: 单个文本项包含多个合法provenance
- **WHEN** 固定Docling的一个非空text item返回两个或更多provenance，且每个条目具有合法bbox与界内、非重叠`charspan`，所有未覆盖字符均为空白
- **THEN** 系统按text item顺序及`charspan`升序为每个条目生成一个文字和bbox绑定的block
- **AND** block ID、`reading_order`、置信度、关系与结果hash必须由该展开后序列确定性产生

#### Scenario: 多段provenance无法安全映射
- **WHEN** provenance缺失、为空、类型错误，或多段`charspan`缺失、越界、重叠、产生空文字或遗漏任意非空白文字
- **THEN** Provider以安全错误码失败关闭对应item
- **AND** 不合并bbox、不采用第一个坐标、不猜测文字归属且不发布截断结果

#### Scenario: 多段展开超过block上限
- **WHEN** 合法多段provenance展开后的最终block数量超过Profile固定的单图block上限
- **THEN** Provider以`docling_picture_block_limit_exceeded`失败关闭对应item
- **AND** 不按上游text item数量放行且不截断超限block

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
