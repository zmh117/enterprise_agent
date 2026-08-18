## ADDED Requirements

### Requirement: Business Application发布冻结文档处理Profile
Business Application Revision SHALL 选择一个代码发布的`document_processing_profile_code`，默认值 MUST 为`NONE`；Publication MUST 冻结解析后的Profile code与hash。运行时只能使用Job固定Publication中的Profile，不得重新读取Draft、当前最新Profile或环境变量来扩大可处理格式和处理选项。

#### Scenario: 旧Publication没有文档处理字段
- **WHEN** 系统读取本变更前创建且没有文档处理字段的Publication
- **THEN** 稳定解释为`NONE`
- **AND** 不调用Docling或创建文档representation

#### Scenario: 新Publication选择DoclingProfile
- **WHEN** 发布者选择当前已安装的`docling-text-v1`并完成发布
- **THEN** Publication冻结该Profile的code与hash
- **AND** 后续Profile发布不改变既有Publication或已创建Job

#### Scenario: 管理端提交任意处理器配置
- **WHEN** Revision payload包含任意Docling URL、HTTP source、Callback、模型、VLM、插件、原始options或未知Profile code
- **THEN** 系统拒绝保存或发布
- **AND** 不把该配置转发到Worker或Docling

### Requirement: 文档处理能力保持显式运行接线状态
业务应用管理与运行状态 SHALL 区分`DISABLED`、`CONFIGURED_UNAVAILABLE`和`READY`：`NONE`为`DISABLED`；选择已安装Profile但processing worker、Docling readiness、队列或File Service依赖不可用时为`CONFIGURED_UNAVAILABLE`；只有Profile、依赖和安全闸门均可用时才能报告`READY`。该状态不得因容器进程running或管理后台开启而误报。

#### Scenario: Publication启用Profile但Docling未就绪
- **WHEN** 应用Publication选择`docling-text-v1`且Docling模型仍在加载或readiness失败
- **THEN** 文档处理状态为`CONFIGURED_UNAVAILABLE`
- **AND** 新文档Job保持安全等待或按固定超时失败，不回退旧提取器

#### Scenario: 未选择Profile的应用正常运行
- **WHEN** 应用Publication的Profile为`NONE`
- **THEN** 其它已发布Channel、Agent和文本文件能力继续按原配置运行
- **AND** 系统不为该应用创建Docling processing run
