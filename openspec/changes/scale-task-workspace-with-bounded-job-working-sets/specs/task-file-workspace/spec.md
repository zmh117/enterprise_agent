## MODIFIED Requirements

### Requirement: 第一阶段文件类型和配额有界
任务工作区 SHALL 根据Business Application Publication冻结的文本格式策略继续支持TXT及已发布的LOG/Markdown能力，并在Publication选择`docling-text-v1`时接受PDF、DOCX、XLSX、PPTX、PNG、JPEG和WebP原件。文本文件和Agent可读Markdown单文件最大15MiB，Docling源文件最大25MiB且PDF最多300页；每个工作区的 ACTIVE 逻辑文件数量 MUST 使用平台受治理的当前 tenant 有效配额，代码默认值为200且任何配置、Publication或请求均 MUST NOT 突破1000的代码硬上限。配额数值 MUST NOT 写入Business Application Publication；Job审计 MUST记录当时观察到的有效值、配置来源和revision。尚未成为保留文件的工作版本、冲突候选和工作区派生内容计费总量必须受代码发布Profile限制。新导入、处理或提交导致任一上限被突破时 MUST 在创建可见版本或表示前完整拒绝。系统 MUST 拒绝DOC、XLS、PPT、宏文件及其它未支持格式，且不得静默截断、猜测编码或降级到宽松解析器。

同一逻辑文件的新版本 MUST NOT重复占用 ACTIVE 文件数量。管理员降低有效配额后，已超过新上限的工作区 MAY继续读取文件并为既有逻辑文件提交满足容量规则的新版本，但 MUST拒绝新增逻辑文件，直至 ACTIVE 数量不超过有效配额。

#### Scenario: 非UTF-8文本进入工作区
- **WHEN** TXT、LOG或Markdown内容是GBK、UTF-16或无效UTF-8
- **THEN** File Service使用安全错误拒绝
- **AND** 不猜测或自动转换编码

#### Scenario: 提交超过工作区临时配额
- **WHEN** 新版本或派生表示会使工作区计费临时内容超过冻结上限
- **THEN** File Service不创建对象可见性、文件版本、representation或错误的当前指针

#### Scenario: 受支持PDF到达
- **WHEN** 新任务工作区收到不超过25MiB和300页、MIME与结构合法的PDF且Publication冻结`docling-text-v1`
- **THEN** File Service保存原件并异步生成Markdown和Docling JSON表示
- **AND** 原始PDF不直接进入Agent Sandbox

#### Scenario: 文档处理Profile未启用
- **WHEN** 工作区收到Office、PDF或图片但Publication没有冻结受支持文档处理Profile
- **THEN** 系统返回明确未启用结果
- **AND** 不调用Docling或声称已解析

#### Scenario: tenant没有配置覆盖
- **WHEN** tenant没有启用的工作区文件数量覆盖且兼容性预检已经通过
- **THEN** File Service使用默认200个 ACTIVE 逻辑文件的有效配额
- **AND** 不从Application Publication读取或推导另一个配额

#### Scenario: tenant尝试配置超过平台硬上限
- **WHEN** 管理员尝试把tenant工作区文件数量设置为1001或更大
- **THEN** 平台在保存配置前拒绝
- **AND** File Service的代码硬上限仍为1000

#### Scenario: 降低配额后工作区暂时超限
- **WHEN** 工作区已有240个 ACTIVE 逻辑文件且tenant有效配额从300降低为200
- **THEN** 既有文件仍可按当前授权读取，既有逻辑文件的新版本仍受容量规则允许
- **AND** 任何第241个新逻辑文件在创建对象可见性前被拒绝

### Requirement: Job 创建时冻结精确文件清单
File Service MUST 在非空文字触发Agent Job时，按当前用户、tenant、任务工作区、Business Application Publication和授权范围冻结有界Job File Manifest。直接可读文本条目 MUST 指向当时精确File Version；需文档处理的条目 MUST 同时冻结原始File/Version ID与精确Markdown Representation ID、kind、size、SHA-256和安全物化名。当前消息附件、引用消息、显式File/Version ID和完整文件名等本轮确定性内容依赖去重后最多20项，并按既有能力就绪规则决定自动物化；超过20项时系统 MUST保留已经导入的工作区文件、发出固定缩小范围说明且 MUST NOT创建Agent Job。时间、格式或名称条件形成的元数据候选最多50项，只能获得`READ_METADATA`且不得自动物化。系统 MUST NOT把工作区全部 ACTIVE 文件复制进Manifest，也 MUST NOT因候选截断而让模型猜测正文目标。清单冻结身份但不冻结授权，物化时 MUST 重新检查当前访问权。纯附件暂存事件 MUST NOT单独生成Manifest。

Job File Manifest、File MCP文件列表/元数据和Runtime自动物化元数据 MUST 明确区分：原始聊天附件进入平台的`source_received_at`、精确原始版本产生的`version_created_at`、representation产生时间以及Manifest冻结或查询发生的`observed_at`。`source_received_at` MUST 取平台创建原始`message_attachment`记录的时间并在后续版本/表示中保持不变；无聊天附件来源的Agent生成文件 MUST 返回`null`。持久化、Manifest hash、File MCP列表/元数据、Runtime Manifest和自动物化元数据中的非空机器时间 MUST 使用表示同一瞬时的UTC RFC 3339；面向用户陈述时才按用户显示时区转换，不得把`Z`或`+00:00`墙钟直接解释为本地时间。系统 MUST NOT使用File Worker导入完成时间、processing run时间、representation时间、工作区引用时间、Manifest条目时间或含义模糊的`created_at`回答“上传时间”。Manifest schema v4 MUST 把源身份、表示身份、来源接收时间和版本创建时间纳入不可变条目及其hash；旧schema可兼容读取但不得虚构缺失时间或表示。工作区有效配额、配置revision、目录revision、候选上限和内容工作集上限 MAY作为Job Snapshot审计字段保存，但 MUST NOT借此改写Manifest v4 hash或Runtime 1.2/1.3 schema。

#### Scenario: 暂存文本附件已经完成导入
- **WHEN** 后续非空文字创建Job前，暂存文本附件已经形成可用精确版本
- **THEN** 创建事务认领附件并立即把该版本冻结为自动物化项

#### Scenario: 暂存文档仍在处理
- **WHEN** 后续非空文字未绑定该文档
- **THEN** 系统立即创建可执行Job且不自动物化处理中文档
- **AND** 该文档只在满足有界候选选择时作为工作区元数据候选

#### Scenario: 其他Job在执行期间产生新表示
- **WHEN** 当前Job清单冻结source V3和representation R1后，同一source Version产生R2或文件产生V4
- **THEN** 当前Job继续物化R1并继续把V3用于原件身份
- **AND** R2或V4只进入后续新Job清单或当前Job后续显式追加选择事实

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

#### Scenario: 工作区包含200个ACTIVE文件
- **WHEN** 新Job只有2个确定性内容依赖和50个有界元数据候选
- **THEN** Manifest只冻结这52项而不是复制200个ACTIVE文件
- **AND** Runtime最多自动物化2个确定性内容依赖

#### Scenario: 本轮确定性内容依赖超过20项
- **WHEN** 同一文字请求确定性绑定21个已导入文件
- **THEN** 系统发出固定缩小范围说明且不创建Agent Job
- **AND** 不删除、隐藏或静默丢弃已经进入工作区的文件

## ADDED Requirements

### Requirement: 工作区文件目录支持有界一致分页发现
File Service SHALL 提供只读工作区目录发现能力，使用当前RUNNING Job的Principal、Publication和workspace解析授权范围，并以游标分页返回不超过50项安全元数据。查询 MUST只接受代码注册的名称、格式、来源接收时间和可读状态过滤，结果 MUST包含精确`file_id + version_id`、安全显示名、格式、大小、机器时间、可读状态、`observed_at`和目录revision；MUST NOT包含正文、对象位置、Bucket、凭据或跨工作区数据。

工作区目录 MUST具有单调`catalog_revision`。ACTIVE成员、逻辑名或选中版本发生变化时 MUST在同一事务递增；分页cursor MUST绑定workspace、过滤摘要、catalog revision和最后排序键。revision或过滤条件不一致时 MUST返回`workspace_catalog_changed`或等价失败并要求重新开始，不得继续返回可能漏项的页面。现有`task_workspace_list_files` MUST继续只列当前Job Snapshot，新目录发现 MUST使用独立Tool identifier和schema hash。

#### Scenario: 分页发现1000个ACTIVE文件
- **WHEN** 授权Job以limit 50遍历一个含1000个ACTIVE文件的工作区且目录revision保持不变
- **THEN** 每页最多返回50个不含正文的精确元数据项和不透明下一页cursor
- **AND** 各页按确定性顺序无重复无漏项

#### Scenario: 翻页期间目录发生变化
- **WHEN** Agent取得第一页后另一个事务修改选中版本并递增catalog revision
- **THEN** 旧cursor的下一页请求返回`workspace_catalog_changed`
- **AND** Agent必须从新观察时间和revision重新查询

#### Scenario: 查询尝试声明workspace或对象位置
- **WHEN** Tool参数包含workspace ID、tenant ID、Bucket、对象键或任意URL
- **THEN** 封闭Schema在数据库或对象存储访问前拒绝

### Requirement: 每个Job内容工作集最多20项且选择事实只追加
每个Job可读取内容的初始Manifest项与运行中追加选择去重后 MUST不超过20个精确File/Version。运行中追加选择 MUST保存不可变Job工作集事实，包含Job/Snapshot、workspace、精确File/Version、适用时的精确Representation身份与hash、选择来源、目录revision、序号和时间；重复选择 MUST幂等返回同一事实，不得改写初始Manifest、Manifest hash或Runtime request digest。

只有Job冻结兼容工作区发现Tool时，`file_prepare_materialization`才 MAY把Manifest外的当前ACTIVE工作区精确版本原子加入内容工作集。加入前 MUST实时复核Job状态、当前主体、tenant、Session、Publication、Tool schema hash、workspace归属、当前选中Version、Representation状态和20项上限；追加选择只授予本次受治理读取所需动作，不得自动授予EDIT、COMMIT或DELIVER。

#### Scenario: Agent选择目录搜索结果
- **WHEN** 兼容Job从目录结果取得当前精确File/Version并请求准备物化，当前工作集只有7项
- **THEN** File Service原子记录第8个追加工作集事实并准备受控物化
- **AND** 初始Manifest和Runtime request digest保持不变

#### Scenario: 第21个内容项被拒绝
- **WHEN** 初始项与追加项去重后已有20个内容项，Agent再选择一个不同版本
- **THEN** File Service返回`job_file_working_set_limit_exceeded`
- **AND** 不创建追加事实、transfer或Sandbox文件

#### Scenario: 旧Job尝试动态晋升
- **WHEN** 历史Job未冻结兼容工作区发现Tool却请求物化Manifest外File/Version
- **THEN** File Service沿用Manifest-only边界并在读取内容前拒绝

#### Scenario: 搜索后当前版本发生变化
- **WHEN** Agent使用搜索结果中的V3准备物化，但工作区当前选中版本已经变成V4
- **THEN** File Service返回目录已变化的安全错误并要求重新搜索
- **AND** 不自动把V3或V4加入内容工作集
