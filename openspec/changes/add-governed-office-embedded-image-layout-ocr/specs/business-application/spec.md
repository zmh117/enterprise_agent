## ADDED Requirements

### Requirement: Publication单选并冻结布局OCR Profile
Business Application Revision SHALL 允许从代码注册目录选择`NONE`、`docling-text-v1`或`docling-layout-ocr-v1`中的一个文档处理Profile，并 MUST 在Publication冻结精确code、version与hash。`docling-layout-ocr-v1` MUST 是`docling-text-v1`能力的完整超集而不是可同时选择的addon；运行时不得重读Draft、环境变量或管理端原始options扩大能力。旧Revision/Publication缺失新值时 MUST 保持既有稳定解释，不得自动迁移到布局OCR。

#### Scenario: 应用发布布局OCR
- **WHEN** 管理员选择`docling-layout-ocr-v1`并创建新Publication
- **THEN** 发布校验代码目录、依赖就绪和Profile canonical hash后冻结code/version/hash
- **AND** Job只使用该不可变Profile创建处理运行

#### Scenario: 同时选择两个Profile
- **WHEN** Draft或API尝试同时组合`docling-text-v1`与`docling-layout-ocr-v1`
- **THEN** 后端在发布前拒绝矛盾配置
- **AND** 不生成动态合成Profile或hash

#### Scenario: 既有应用未启用布局OCR
- **WHEN** 已激活Publication仍冻结`docling-text-v1`或`NONE`
- **THEN** 该应用继续保持原文档处理能力和输出集合
- **AND** 新Profile部署不得追溯修改Publication或历史Job

### Requirement: 管理端准确展示布局OCR能力边界
管理端 SHALL 把`docling-layout-ocr-v1`展示为“Office内嵌图片布局OCR”，并 MUST 说明它提取文字、置信度、坐标、阅读顺序和几何关系，但不提供VLM、箭头、颜色、图标、照片语义或精确图表因果。管理端 MUST 同时说明OCR使用Office包内原始嵌入图片、仅应用图片自身EXIF方向、不应用Office显示裁剪/旋转/翻转且结果可能包含已裁掉区域。管理端只能选择代码Profile，不得输入Docling URL、OCR引擎、模型、prompt、坐标阈值或原始options；依赖未全部就绪时不得显示READY。

#### Scenario: 管理员查看Profile说明
- **WHEN** 管理员在Business Application组成配置中选择布局OCR Profile
- **THEN** 页面显示固定能力、原始图片像素基准、Office显示变换未应用、可能包含已裁掉区域的限制和非VLM边界
- **AND** 不把OCR坐标描述为完整图片语义理解

#### Scenario: OCR模型artifact缺失
- **WHEN** 新Profile已注册但固定OCR/layout artifacts或处理依赖未就绪
- **THEN** 管理端显示已配置但依赖未就绪并阻止激活或运行态READY
- **AND** 不从静态Profile注册推断真实可用
