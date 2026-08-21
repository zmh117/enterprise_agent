# document-file-processing Specification

## Purpose
定义受治理文档处理 Profile、不可变处理运行与派生表示的身份、异步编排、隔离、恢复和生命周期边界。

## Requirements

### Requirement: 文档处理只使用代码发布的固定Profile
系统 MUST 只允许代码发布且可审计的文档处理Profile；第一阶段唯一启用Profile SHALL 为`docling-text-v1`，其输入白名单为PDF、DOCX、PPTX、XLSX、PNG、JPEG和WebP，输出固定为Markdown与Docling JSON。该Profile MUST 开启有界OCR和表格结构提取，MUST 关闭VLM、图片语义描述、远程服务、HTTP URL Source、Callback、自定义模型配置和外部插件。

#### Scenario: 已发布应用选择Docling文字Profile
- **WHEN** Job固定的Business Application Publication选择`docling-text-v1`
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
File Service MUST 为每个run和representation kind创建绑定身份的不透明staging transfer，在流式接收时计算SHA-256并校验Markdown UTF-8、JSON结构、media type和独立大小上限。只有`docling-text-v1`要求的Markdown与Docling JSON均完整时，系统才能在数据库事务中发布可见representation、更新run终态并写完成Outbox；对象存在本身不得表示内容可用。

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
