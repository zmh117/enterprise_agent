## MODIFIED Requirements

### Requirement: 第一阶段文件类型和配额有界
任务工作区 SHALL 固定使用代码发布的 `text-v2` 直接文本规则：TXT和Markdown可读写，LOG只读；该规则不得由Business Application、Publication、Job或Runtime切换。文档处理关闭时只接受这些直接文本；启用`docling-layout-ocr-v2`时还接受PDF、DOCX、XLSX、PPTX、PNG、JPEG和WebP原件。文本文件和Agent可读Markdown单文件最大15MiB，文档源文件最大25MiB且PDF最多300页；每个工作区默认最多200个ACTIVE逻辑文件，平台硬上限1000个，默认计费容量2GiB且平台硬上限10GiB。新导入、处理或提交导致任一上限被突破时 MUST 在创建可见版本或表示前完整拒绝。系统 MUST 拒绝DOC、XLS、PPT、宏文件及其它未支持格式，且不得静默截断、猜测编码或降级到宽松解析器。

#### Scenario: 非UTF-8文本进入工作区
- **WHEN** TXT、LOG或Markdown内容是GBK、UTF-16或无效UTF-8
- **THEN** File Service使用安全错误拒绝
- **AND** 不猜测或自动转换编码

#### Scenario: 提交超过工作区临时配额
- **WHEN** 新版本或派生表示会使工作区计费临时内容超过冻结上限
- **THEN** File Service不创建对象可见性、文件版本、representation或错误的当前指针

#### Scenario: 受支持PDF到达
- **WHEN** 新任务工作区收到不超过25MiB和300页、MIME与结构合法的PDF且Publication冻结`docling-layout-ocr-v2`
- **THEN** File Service保存原件并异步生成布局Markdown和Docling JSON表示
- **AND** 原始PDF不直接进入Agent Sandbox

#### Scenario: 文档处理Profile未启用
- **WHEN** 工作区收到Office、PDF或图片但Publication的文档处理Profile为`NONE`
- **THEN** 系统返回明确未启用结果
- **AND** 不调用Docling或声称已解析

#### Scenario: 调用方尝试切换直接文本规则
- **WHEN** Revision、Publication、Job或Runtime请求携带`text-v1`、未知文本策略或文件策略选择字段
- **THEN** 系统在副作用前拒绝该字段
- **AND** 不建立运行时兼容或回退分支

### Requirement: Job 创建时冻结精确文件清单
File Service MUST 在非空文字触发Agent Job时，按当前用户、tenant、任务工作区、Business Application Publication和授权范围冻结schema v5 Job File Manifest。Manifest MUST 冻结`workspace_catalog_revision_id`、当前消息附件、明确引用和已选Job Working Set，而不得复制工作区全部目录；直接可读文本条目 MUST 指向当时精确File Version，需文档处理的条目 MUST 同时冻结原始File/Version ID与精确Markdown Representation ID、kind、size、SHA-256和安全物化名。该文字Job本轮确定性绑定且能力已就绪的附件、同一消息新上传附件和明确引用文件 SHALL 进入Working Set并自动物化；其他文件只通过冻结Catalog Revision分页提供不含正文、凭据和对象位置的元数据，由Agent精确选择。自动物化与按需物化累计最多40个不同输入版本，超出时 MUST 完整拒绝新增选择。清单冻结身份但不冻结授权，物化时 MUST 重新检查当前访问权。纯附件暂存事件 MUST NOT单独生成Manifest。

Job File Manifest、File MCP文件列表/元数据和Runtime自动物化元数据 MUST 明确区分：原始聊天附件进入平台的`source_received_at`、精确原始版本产生的`version_created_at`、representation产生时间以及Manifest冻结或查询发生的`observed_at`。`source_received_at` MUST 取平台创建原始`message_attachment`记录的时间并在后续版本/表示中保持不变；无聊天附件来源的Agent生成文件 MUST 返回`null`。持久化、Manifest hash、File MCP列表/元数据、Runtime Manifest和自动物化元数据中的非空机器时间 MUST 使用表示同一瞬时的UTC RFC 3339；面向用户陈述时才按用户显示时区转换，不得把`Z`或`+00:00`墙钟直接解释为本地时间。系统 MUST NOT使用File Worker导入完成时间、processing run时间、representation时间、工作区引用时间、Manifest条目时间或含义模糊的`created_at`回答“上传时间”。Manifest schema v5 MUST 把Catalog Revision、Working Set、源身份、表示身份、来源接收时间和版本创建时间纳入不可变payload及其hash；系统不得生成、读取、投影或恢复schema v1-v4。

#### Scenario: 暂存文本附件已经完成导入
- **WHEN** 后续非空文字创建Job前，暂存文本附件已经形成可用精确版本
- **THEN** 创建事务认领附件并立即把该版本加入Working Set并冻结为自动物化项

#### Scenario: 暂存文档仍在处理
- **WHEN** 后续非空文字未绑定该文档
- **THEN** 系统立即创建可执行Job且不自动物化处理中文档
- **AND** 该文档继续作为冻结Catalog Revision中的元数据候选

#### Scenario: 其他Job在执行期间产生新表示
- **WHEN** 当前Job清单冻结source V3和representation R1后，同一source Version产生R2或文件产生V4
- **THEN** 当前Job继续物化R1并继续把V3用于原件身份
- **AND** R2或V4只进入后续Catalog Revision和Job清单

#### Scenario: 冻结后用户权限被撤销
- **WHEN** 文件和representation仍在Job File Manifest中但当前用户或应用访问已失效
- **THEN** File Service拒绝物化或交付
- **AND** 不把冻结清单解释为长期访问授权

#### Scenario: 查询最近一小时上传的文件
- **WHEN** 用户要求处理最近一小时上传的工作区文件
- **THEN** Agent使用File Service返回的`observed_at`作为边界，只选择`source_received_at`不早于该边界减一小时的文件
- **AND** 不把后续编辑版本或新representation误判为新上传文件

#### Scenario: Agent生成文件没有上传时间
- **WHEN** 工作区文件由Agent生成且没有聊天附件来源
- **THEN** File Service返回`source_received_at=null`和非空`version_created_at`
- **AND** Agent不把该文件归入“最近上传的附件”集合

#### Scenario: Manifest尝试替换Representation
- **WHEN** 模型或Runtime尝试以Manifest外的representation ID替换冻结表示
- **THEN** File Service在读取内容前拒绝

#### Scenario: 无附件文字Job
- **WHEN** 普通文字消息创建不包含文件的Agent Job
- **THEN** 系统仍创建合法schema v5空文件上下文且Working Set为空
- **AND** 不投影成旧Manifest或因文件上下文为空拒绝模型执行

#### Scenario: 旧Manifest进入当前服务
- **WHEN** 数据库或Runtime请求出现schema v1、v2、v3或v4 Manifest
- **THEN** 当前服务以稳定合同错误失败关闭
- **AND** 不读取旧payload、不计算旧hash且不执行模型

## ADDED Requirements

### Requirement: 入站附件只通过任务工作区形成Agent可读内容
所有消息附件 MUST 先由File Service形成受管原件和不可变版本。TXT、LOG和Markdown只按固定`text-v2`规则形成直接可读内容；Office、PDF和图片只在Publication启用`docling-layout-ocr-v2`时形成受治理Representation。Channel、API和Agent上下文构建器不得进程内提取DOCX、XLSX、PPTX或Markdown正文，也不得从独立附件正文缓存向模型注入内容。

#### Scenario: DOCX附件到达
- **WHEN** 用户发送合法DOCX且应用启用`docling-layout-ocr-v2`
- **THEN** 附件经File Service、processing队列和固定Docling Profile形成Markdown Representation
- **AND** Channel/API进程不使用Office库直接提取正文

#### Scenario: 旧附件正文缓存仍存在
- **WHEN** 部署前预检发现`attachment_content`或等价旧提取正文事实
- **THEN** 破坏性开放测试重置必须删除这些事实后才允许当前migration完成
- **AND** 当前运行代码不读取或回填该缓存
