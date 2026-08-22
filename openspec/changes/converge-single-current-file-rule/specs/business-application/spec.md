## MODIFIED Requirements

### Requirement: Business Application发布冻结文档处理Profile
Business Application Revision SHALL 只允许选择`NONE`或代码发布的`docling-layout-ocr-v2`，默认值 MUST 为`NONE`；Publication MUST 冻结解析后的Profile code与hash。`docling-layout-ocr-v2` MUST 以独立完整定义注册，不得从已删除Profile继承options或hash。运行时只能使用Job固定Publication中的Profile，不得重新读取Draft、当前最新Profile或环境变量来扩大可处理格式和处理选项。

#### Scenario: Publication关闭文档处理
- **WHEN** 发布者选择`NONE`并完成发布
- **THEN** Publication冻结文档处理关闭状态
- **AND** 不调用Docling或创建文档representation

#### Scenario: 新Publication选择当前DoclingProfile
- **WHEN** 发布者选择当前唯一已安装的`docling-layout-ocr-v2`并完成发布
- **THEN** Publication冻结该Profile的code与独立完整hash
- **AND** 后续代码发布不改变既有Publication或已创建Job

#### Scenario: 管理端提交任意处理器配置
- **WHEN** Revision payload包含任意Docling URL、HTTP source、Callback、模型、VLM、插件、原始options、`docling-text-v1`、`docling-layout-ocr-v1`或未知Profile code
- **THEN** 系统拒绝保存或发布
- **AND** 不把该配置转发到Worker或Docling

#### Scenario: 当前数据库仍引用旧Profile
- **WHEN** 单一合同migration发现任何Revision、Publication、Deployment或非终态Job仍引用已删除Profile
- **THEN** migration失败关闭并报告安全引用计数
- **AND** 不把旧code在线解释或回退成当前Profile

### Requirement: 文档处理能力保持显式运行接线状态
业务应用管理与运行状态 SHALL 区分`DISABLED`、`CONFIGURED_UNAVAILABLE`和`READY`：`NONE`为`DISABLED`；选择`docling-layout-ocr-v2`但processing worker、Docling readiness、队列或File Service依赖不可用时为`CONFIGURED_UNAVAILABLE`；只有固定Profile、依赖和安全闸门均可用时才能报告`READY`。该状态不得因容器进程running或管理后台开启而误报。

#### Scenario: Publication启用当前Profile但Docling未就绪
- **WHEN** 应用Publication选择`docling-layout-ocr-v2`且Docling模型仍在加载或readiness失败
- **THEN** 文档处理状态为`CONFIGURED_UNAVAILABLE`
- **AND** 新文档Job保持安全等待或按固定超时失败，不回退任何旧提取器

#### Scenario: 未选择Profile的应用正常运行
- **WHEN** 应用Publication的Profile为`NONE`
- **THEN** 其它已发布Channel、Agent和直接文本能力继续按固定`text-v2`运行
- **AND** 系统不为该应用创建Docling processing run

#### Scenario: 配置选择与实时运行状态分区展示
- **WHEN** 管理员查看Business Application的组成配置
- **THEN** 管理端展示固定直接文本规则和`NONE`/`docling-layout-ocr-v2`文档处理选择，并明确TXT、LOG、Markdown不进入Docling
- **AND** 不展示文件格式策略选择或任何旧Profile
- **WHEN** 管理员查看已激活Publication的发布与运行信息
- **THEN** 文档解析/OCR运行状态来自File Processing Worker、Docling、processing队列和File Service的实时安全探针
- **AND** Publication未激活、探针失败或状态无法取得时不得报告`READY`

## ADDED Requirements

### Requirement: Business Application不得配置直接文本规则版本
Business Application Revision、Publication、canonical snapshot、管理API和管理端 MUST NOT 暴露或持久化可切换的直接文本规则版本。所有启用任务文件能力的应用 SHALL 使用平台代码固定的`text-v2`行为；调用方提交文件格式策略字段 MUST 被识别为不允许的未知字段，而不是被忽略或兼容解释。

#### Scenario: 创建应用草稿
- **WHEN** 管理员创建或编辑启用任务文件能力的应用草稿
- **THEN** 页面只读说明TXT/Markdown可读写且LOG只读
- **AND** 请求与持久化快照均不包含`file_format_policy_version`或等价切换字段

#### Scenario: 旧客户端提交文本策略
- **WHEN** 客户端提交`text-v1`、`text-v2`或任意文件格式策略选择字段
- **THEN** 管理API返回字段级合同错误
- **AND** 不静默丢弃、不保存兼容影子值且不创建Revision
