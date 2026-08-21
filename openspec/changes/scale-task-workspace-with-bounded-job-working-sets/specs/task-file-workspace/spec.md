## MODIFIED Requirements

### Requirement: 第一阶段文件类型和配额有界
任务工作区 SHALL 根据Business Application Publication冻结的文本格式策略继续支持TXT及已发布的LOG/Markdown能力，并在Publication选择受支持文档处理Profile时接受PDF、DOCX、XLSX、PPTX、PNG、JPEG和WebP原件。文本文件和Agent可读Markdown单文件最大15MiB，Docling源文件最大25MiB且PDF最多300页。每个工作区的ACTIVE逻辑文件数量 MUST使用平台受治理的当前tenant有效配额，代码默认值为200且任何配置、Publication或请求均 MUST NOT突破1000的代码硬上限；工作区计费内容字节 MUST使用同一tenant有效配额快照中的独立限制，代码默认值为2GiB且任何配置、Publication或请求均 MUST NOT突破10GiB代码硬上限。

文件数和字节配额 MUST NOT写入Business Application Publication。Job审计 MUST记录当时观察到的两个有效值、配置来源和revision。字节计费 MUST覆盖尚未提升为独立Retained内容的工作版本、开放冲突候选、未终结staging和工作区派生表示/处理资产，并在同一工作区按稳定不可变对象身份去重。所有导入、处理和提交 MUST在外部对象或数据库可见性前事务预留预计新增文件数与字节；成功终结后转为实际用量，失败或过期后可重试释放。任一独立上限被突破时 MUST完整拒绝，不得以另一维度尚有余额、静默截断或最后写入者竞态来放宽。

同一逻辑文件的新版本 MUST NOT重复占用ACTIVE文件数量，但 MUST按实际新增计费内容占用字节配额。管理员降低有效配额后，已超过任一新上限的工作区 MAY继续读取已有内容，但 MUST拒绝继续增加超限维度的新逻辑文件、新版本、staging或派生内容，直至对应实际用量与有效预留不超过当前配额。

#### Scenario: 非UTF-8文本进入工作区
- **WHEN** TXT、LOG或Markdown内容是GBK、UTF-16或无效UTF-8
- **THEN** File Service使用安全错误拒绝
- **AND** 不猜测或自动转换编码

#### Scenario: 提交超过工作区字节配额
- **WHEN** 新版本、staging或派生表示会使工作区实际用量加有效预留超过当前tenant字节上限
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

#### Scenario: tenant没有字节配额覆盖
- **WHEN** tenant没有启用的工作区字节覆盖
- **THEN** File Service使用默认2GiB计费内容上限
- **AND** 不从Application Publication读取或推导另一个容量

#### Scenario: tenant尝试配置超过字节硬上限
- **WHEN** 管理员尝试把tenant工作区字节配额设置为大于10GiB
- **THEN** 平台在保存配置前拒绝
- **AND** File Service消费端仍以10GiB代码硬上限失败关闭

#### Scenario: 降低配额后工作区暂时超限
- **WHEN** 工作区已有240个 ACTIVE 逻辑文件且tenant有效配额从300降低为200
- **THEN** 既有文件仍可按当前授权读取，但任何新增逻辑文件在创建对象可见性前被拒绝
- **AND** 新版本仅在不会继续增加其它已超限维度时才可终结

### Requirement: Job 创建时冻结精确文件清单
File Service MUST在非空文字触发Agent Job时，按当前用户、tenant、任务工作区、Business Application Publication和授权范围冻结Manifest v5。Manifest头部 MUST包含不可变`workspace_catalog_revision_id`；条目 MUST只包含当前消息附件、明确引用、显式File/Version和创建前已选工作集，MUST NOT复制冻结目录中的其它200至1000个元数据成员。直接可读文本条目 MUST指向精确File Version；需文档处理的条目 MUST同时冻结原始File/Version ID与精确Markdown Representation ID、kind、size、SHA-256和安全物化名。

Job创建事务前 MUST对计划自动物化条目按`file_id + version_id`去重，并以实际文本File Version或Markdown Representation大小完整预检40项输入上限和224MiB Sandbox容量。超过任一上限时系统 MUST保留已经导入的工作区文件、发出固定缩小工作集说明且 MUST NOT创建Agent Job、dispatch outbox或任何Sandbox文件；不得只冻结或物化可容纳的前缀。PDF、Office和图片每个原始File/Version只算一个输入，且只计算实际进入Sandbox的Markdown，原始二进制和Docling/OCR JSON不得进入预检物化集合。清单冻结身份但不冻结授权，物化时 MUST重新检查当前访问权。纯附件暂存事件 MUST NOT单独生成Manifest。

Job File Manifest、File MCP目录元数据和Runtime自动物化元数据 MUST明确区分：原始聊天附件进入平台的`source_received_at`、精确原始版本产生的`version_created_at`、representation产生时间以及Manifest冻结或查询发生的`observed_at`。`source_received_at` MUST取平台创建原始`message_attachment`记录的时间并在后续版本/表示中保持不变；无聊天附件来源的Agent生成文件 MUST返回`null`。持久化、Manifest hash、File MCP列表/元数据、Runtime Manifest和自动物化元数据中的非空机器时间 MUST使用表示同一瞬时的UTC RFC 3339；面向用户陈述时才按用户显示时区转换，不得把`Z`或`+00:00`墙钟直接解释为本地时间。系统 MUST NOT使用File Worker导入完成时间、processing run时间、representation时间、工作区引用时间、Manifest条目时间或含义模糊的`created_at`回答“上传时间”。Manifest v5 MUST把目录revision、源身份、表示身份、来源接收时间和版本创建时间纳入不可变事实及其hash；旧schema可兼容读取但不得虚构缺失目录revision、时间或表示。两个工作区有效配额、配置revision/source和40/64/224MiB代码限制版本 SHALL作为Job Snapshot审计事实保存，但 MUST NOT要求Runtime 1.2/1.3新增tenant配置字段。

#### Scenario: 暂存文本附件已经完成导入
- **WHEN** 后续非空文字创建Job前，暂存文本附件已经形成可用精确版本
- **THEN** 创建事务认领附件并立即把该版本冻结为自动物化项

#### Scenario: 暂存文档仍在处理
- **WHEN** 后续非空文字未绑定该文档
- **THEN** 系统立即创建可执行Job且不自动物化处理中文档
- **AND** Agent只能通过该Job冻结目录revision的分页查询发现它

#### Scenario: 其他Job在执行期间产生新表示
- **WHEN** 当前Job清单冻结source V3和representation R1后，同一source Version产生R2或文件产生V4
- **THEN** 当前Job继续物化R1并继续把V3用于原件身份
- **AND** R2或V4只进入后续目录revision和后续Job，不替换当前Job冻结选择

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

#### Scenario: 工作区包含1000个ACTIVE文件
- **WHEN** 新Job只有2个当前附件且冻结一个包含1000个成员的目录revision
- **THEN** Manifest只冻结目录revision ID和这2个精确输入，不复制其它998个目录条目
- **AND** Runtime只预检并自动物化这2个输入

#### Scenario: 本轮计划输入超过40项
- **WHEN** 同一文字请求确定性绑定41个不同File/Version
- **THEN** 系统发出固定缩小范围说明且不创建Agent Job
- **AND** 不删除、隐藏或静默丢弃已经进入工作区的文件

#### Scenario: 计划Markdown超过Sandbox容量
- **WHEN** 计划自动物化的40个合规Markdown实际大小合计超过224MiB
- **THEN** Job创建前完整拒绝并要求缩小工作集
- **AND** 不创建只物化部分输入的Job或Sandbox

### Requirement: 每个 Agent Job 使用隔离临时沙盒
Runtime MUST为每个Agent Job创建独立Job Sandbox，并只把当前Job工作集已授权的精确文本File Version或精确Markdown Representation物化到该目录。Sandbox MUST固定总文件上限64和总容量224MiB，并分别限制`inputs`最多40个文件、`work/outputs`合计最多16个文件、`tmp`及内部安全余量最多8个文件；目录、marker和不可见控制元数据不得被模型用来规避普通文件计数。PDF、Office、图片原始二进制、Docling JSON和OCR Layout JSON MUST NOT进入Agent Sandbox。

自动物化、File MCP按需物化、Runtime Write/Edit和内部临时文件 MUST共享同一Sandbox预算与原子预留器。Runtime在写入第一个自动物化字节前 MUST对整批输入重新预留实际文件数与Manifest冻结大小；按需物化和写入 MUST在创建目标文件前预留对应分区名额和剩余容量。失败或完整性校验不通过 MUST删除不完整文件并释放预留。重复物化同一`file_id + version_id` MUST复用已有输入和handle，不重复占用文件数或字节。Claude Code Agent只可在该沙盒内使用`Read`、`Grep`、`Glob`、`Write`和`Edit`，且写/编辑动作仍受冻结文本格式策略限制；Bash、Web、NotebookEdit、沙盒外路径、符号链接逃逸和其它开放执行能力 MUST保持不可用。Job成功、失败、取消或超时后 MUST清理沙盒，Runtime异常退出后 MUST由恢复扫描清理无RUNNING Job归属的残留目录。

#### Scenario: Agent读取Office派生Markdown
- **WHEN** Job工作集获得受控DOCX source Version及其Markdown representation
- **THEN** Runtime只在安全`inputs`路径物化经过大小和SHA-256校验的Markdown并计为一个输入
- **AND** 原始DOCX、Docling JSON和内嵌图片不进入Sandbox

#### Scenario: File MCP物化达到输入上限
- **WHEN** Sandbox已经成功物化40个不同File/Version输入且Agent请求第41个
- **THEN** Runtime与File Service在创建目标文件前拒绝`job_file_working_set_limit_exceeded`
- **AND** 不创建transfer残留、Sandbox文件或第41个有效工作集输入

#### Scenario: 输入文件数未满但容量不足
- **WHEN** 下一份Markdown会使Sandbox实际文件总量超过224MiB
- **THEN** 统一预算在下载字节前拒绝并返回安全容量错误
- **AND** 不因File MCP路径不同而绕过Write/Edit使用的容量边界

#### Scenario: Agent在沙盒内生成输出
- **WHEN** 40个输入均已占用且`work/outputs`仍有分区名额和总字节余量
- **THEN** Runtime允许在16个输出/工作文件上限内创建受支持文本
- **AND** 输入文件数不得消耗输出分区名额

#### Scenario: Agent尝试写沙盒外路径
- **WHEN** `Write`或`Edit`目标通过绝对路径、`..`、符号链接或其它方式离开Job Sandbox
- **THEN** Runtime在文件系统副作用前拒绝并记录安全工具结果

## ADDED Requirements

### Requirement: 工作区文件目录支持有界一致分页发现
File Service SHALL提供只读工作区目录发现能力，使用当前RUNNING Job的Principal、Publication、workspace和Manifest冻结的`workspace_catalog_revision_id`解析授权范围，并以游标分页返回默认20、最多50项安全元数据。查询 MUST只接受代码注册的名称、格式、来源接收时间和可读状态过滤，结果 MUST包含精确`file_id + version_id`、安全显示名、格式、大小、机器时间、可读状态、`observed_at`和冻结目录revision；MUST NOT包含正文、对象位置、Bucket、凭据或跨工作区数据。模型输入 MUST NOT声明workspace、tenant或revision身份。

工作区目录 MUST具有不可变revision身份和时间化成员事实。ACTIVE成员、逻辑名或选中版本发生变化时 MUST在同一事务创建下一revision并保留仍被Job引用的旧revision查询能力；不得为每个Job复制整个目录。分页cursor MUST绑定workspace、过滤摘要、`workspace_catalog_revision_id`和最后排序键。同一Job在当前目录变化后 MUST仍按冻结revision无重复无漏项地继续分页；新成员或新版本只可由后续Job的新revision发现。现有`task_workspace_list_files` MUST继续只列当前Job初始Manifest/工作集语义，新目录发现 MUST使用独立Tool identifier和schema hash。

#### Scenario: 分页发现1000个ACTIVE文件
- **WHEN** 授权Job以limit 50遍历一个含1000个ACTIVE文件的工作区且目录revision保持不变
- **THEN** 每页最多返回50个不含正文的精确元数据项和不透明下一页cursor
- **AND** 各页按确定性顺序无重复无漏项

#### Scenario: 翻页期间当前目录发生变化
- **WHEN** Agent取得冻结revision的第一页后另一个事务上传新文件并创建下一revision
- **THEN** 原Job使用旧cursor继续得到旧revision的下一页且无重复无漏项
- **AND** 新文件只对冻结新revision的后续Job可见

#### Scenario: 查询尝试声明workspace或对象位置
- **WHEN** Tool参数包含workspace ID、tenant ID、catalog revision ID、Bucket、对象键或任意URL
- **THEN** 封闭Schema在数据库或对象存储访问前拒绝

#### Scenario: 冻结版本后来不再是当前版本
- **WHEN** Job冻结目录中的V3在分页后被工作区V4取代，但V3内容仍可用且当前主体仍有权访问
- **THEN** Agent可精确选择V3并由工作集事实冻结V3
- **AND** File Service不得静默替换为V4

### Requirement: 每个Job输入物化工作集最多40项且选择事实只追加
每个Job自动物化与运行中按需物化的输入按`file_id + version_id`去重后 MUST不超过40项。运行中追加选择 MUST保存不可变Job工作集事实，包含Job/Snapshot、workspace、`workspace_catalog_revision_id`、精确File/Version、适用时的精确Representation身份与hash、选择来源、序号和时间；重复选择或物化同一版本 MUST幂等返回同一事实与既有Sandbox输入，不得重复计数、改写初始Manifest、Manifest hash或Runtime request digest。

只有Job冻结兼容工作区发现Tool时，`file_prepare_materialization`才 MAY把Manifest外但属于冻结目录revision的精确版本原子加入输入工作集。加入前 MUST实时复核Job状态、当前主体、tenant、Session、Publication、Tool schema hash、workspace/revision归属、精确Version内容可用性、Representation血缘、40项上限以及Runtime Sandbox预留结果；追加选择只授予本次受治理读取所需动作，不得自动授予EDIT、COMMIT或DELIVER。

#### Scenario: Agent选择目录搜索结果
- **WHEN** 兼容Job从目录结果取得当前精确File/Version并请求准备物化，当前工作集只有7项
- **THEN** File Service原子记录第8个追加工作集事实并准备受控物化
- **AND** 初始Manifest和Runtime request digest保持不变

#### Scenario: 第41个输入被拒绝
- **WHEN** 自动与按需输入去重后已有40个不同File/Version，Agent再选择一个不同版本
- **THEN** File Service返回`job_file_working_set_limit_exceeded`
- **AND** 不创建追加事实、transfer或Sandbox文件

#### Scenario: 重复物化同一版本
- **WHEN** 同一Job再次请求已经成功物化的相同File/Version
- **THEN** Runtime返回既有安全handle或等价幂等结果
- **AND** 输入计数、Sandbox文件数和字节用量均不重复增加

#### Scenario: 旧Job尝试动态晋升
- **WHEN** 历史Job未冻结兼容工作区发现Tool却请求物化Manifest外File/Version
- **THEN** File Service沿用Manifest-only边界并在读取内容前拒绝

#### Scenario: 冻结版本内容已经不可用
- **WHEN** Agent选择冻结目录revision中的V3，但V3内容已按生命周期清理或当前授权已撤销
- **THEN** File Service在创建transfer前失败关闭
- **AND** 不自动改用V4或其它Representation
