## ADDED Requirements

### Requirement: Job文件工作集选择必须可恢复且不改变Runtime协议
系统 SHALL把Job初始文件Manifest与执行期间追加的精确文件工作集事实分开持久化。Manifest v5 MUST冻结`workspace_catalog_revision_id`以及当前附件、明确引用和预选项，不复制整个工作区目录；追加工作集事实 MUST使用Job、Snapshot、精确File/Version和可选Representation身份保持幂等，并在Worker重试、Runtime断线恢复和相同invocation恢复时复用，MUST NOT重新选择“当前最新”版本或产生第二套内容授权。初始项与追加项按精确File/Version去重后累计 MUST不超过40项；重复选择同一版本不重复计数。

追加工作集事实属于控制面与File Service授权事实，MUST NOT新增或改写Runtime 1.2/1.3请求、事件或终态字段。Runtime只通过已经冻结的File MCP Tool、短时Principal和受控transfer取得动态选择内容，仍不得接收MinIO凭据、对象位置或原始二进制。

#### Scenario: Runtime断线后恢复同一Job
- **WHEN** Job已经追加选择V3及Representation R1并创建受控transfer，Worker在Runtime终态前断线
- **THEN** 恢复继续使用相同Job工作集事实和精确V3/R1
- **AND** 不重新解析当前V4或Representation R2

#### Scenario: 并发重复选择同一版本
- **WHEN** 同一Job并发两次选择相同File/Version
- **THEN** 唯一约束和事务只保留一个追加工作集事实
- **AND** 两次调用得到一致身份且工作集计数只增加一次

#### Scenario: Runtime合同仍使用受支持版本
- **WHEN** 兼容大工作区Job执行搜索、动态选择和物化
- **THEN** Worker与Python Runtime仍使用已发布的Runtime 1.2或1.3合同
- **AND** Runtime schema校验不要求新的文件工作集字段

#### Scenario: Job重试时权限已经撤销
- **WHEN** 追加工作集事实仍存在但当前用户或Application访问在重试前被撤销
- **THEN** File Service在再次物化前失败关闭
- **AND** 不把追加事实解释为长期访问授权

### Requirement: Runtime统一实施Sandbox文件分区与容量预留
Python Runtime SHALL以同一个`JobSandbox`预算与预留服务约束自动物化、File MCP按需物化、Agent Write/Edit、输出选择和内部临时文件。每个Job MUST最多具有64个Sandbox常规文件槽位，其中`inputs`最多40个、`work/outputs`合计最多16个、内部临时与安全余量保留8个；全部分区共享224MiB总容量。输入计数按进入Sandbox的唯一File/Version计算，同一版本重复物化复用既有entry；Office、PDF和图片只计算实际进入Sandbox的Markdown，原始二进制不得进入Sandbox或另行计数。

自动物化批次 MUST在创建Job与outbox前根据实际待物化表示的数量和大小执行完整预检，超过40项或224MiB时完整拒绝并要求缩小工作集，MUST NOT只物化一部分。Runtime在执行前再次复核。File MCP按需物化 MUST在下载任何字节或创建最终目标文件前获得输入槽位与容量预留；Write/Edit和内部临时文件也必须使用同一预算。失败、取消、完整性不匹配或进程恢复 MUST清理部分文件并释放预留。

#### Scenario: 自动物化批次超过输入上限
- **WHEN** 计划自动物化41个不同File/Version或其Markdown总大小会突破224MiB
- **THEN** Control Plane在创建Job和outbox前完整拒绝该请求
- **AND** 不创建只有部分输入可见的Job

#### Scenario: File MCP尝试物化第41个输入
- **WHEN** RUNNING Job已经物化40个不同File/Version且Agent选择第41个
- **THEN** Runtime在下载字节与创建目标文件前返回稳定的有界拒绝
- **AND** File Service授权成功不构成绕过Sandbox预算的理由

#### Scenario: 输入已满后生成输出
- **WHEN** Job已经使用40个输入槽位但仍有共享容量
- **THEN** Agent仍可在`work/outputs`分区内创建最多16个受治理文件
- **AND** 输入文件不得消耗输出文件槽位，但全部文件仍共享224MiB容量

## MODIFIED Requirements

### Requirement: Agent Job 固定文件清单但实时复核访问
Agent Job创建事务 MUST固定任务工作区ID、不可变`workspace_catalog_revision_id`，以及Job File Manifest中的精确初始File/Version ID；对需转换文档还 MUST固定精确Markdown Representation ID、kind、size和SHA-256。Manifest SHALL以有界、无正文、无凭据、无对象位置形式只包含当前附件、明确引用和预选工作集，不得复制200至1000个目录元数据项。Runtime按需物化或交付时 MUST由File Service重新检查RUNNING Job、当前内部用户、Business Application访问、私聊所有者或同群会话边界、source Version与representation血缘。

RUNNING Job只有在冻结兼容目录发现与物化Tool后，才可从同一冻结目录revision把精确File/Version追加到工作集；初始项与追加项合计去重后不得超过40项。File Service MUST复核该精确版本属于冻结revision、内容仍可用且当前授权仍成立；不得读取冻结revision外、之后产生、已被删除或内容不可用的版本/表示，也不得用“当前最新”版本静默替换。该追加事实不改写初始Manifest、Runtime request digest或Runtime 1.2/1.3协议。

#### Scenario: 执行期间当前版本或表示变化
- **WHEN** Job固定source V3和representation R1后另一Job提交V4或处理器产生R2
- **THEN** 当前Runtime仍只把R1用于阅读并把V3用于原件身份
- **AND** 基于V3的后续提交按正常并发规则得到冲突

#### Scenario: Representation与源版本不匹配
- **WHEN** Manifest或传输请求把属于另一source Version的representation绑定到当前文件
- **THEN** File Service在读取对象前拒绝并记录安全完整性错误

#### Scenario: 从冻结目录追加精确旧版本
- **WHEN** Job冻结的目录revision包含V3，当前工作区后来选择V4，但Agent从冻结分页结果精确选择仍可访问的V3
- **THEN** File Service可把V3追加为该Job工作集事实并按V3物化
- **AND** 不自动替换为V4；若V3内容不可用则失败关闭

### Requirement: Runtime 通过受控文件桥完成物化和提交
Runtime MUST通过File Service受控流式接口下载Job初始Manifest或追加工作集中的精确文本File Version或精确Markdown Representation，并上传Agent显式选中的受支持沙盒文本文件。PDF、Office、图片原始二进制和Docling JSON不得进入Agent Sandbox。File MCP只创建物化或提交意图并返回不透明标识，完整文件字节 MUST NOT进入模型上下文、MCP JSON、Tool事件或审计。Runtime不得获得MinIO凭据、Bucket、对象键或可供模型使用的上传URL。

Python Runtime MUST使用代码注册的进程内File MCP bridge代理Job冻结的部署固定File Service工具，并在远端ToolResult交回模型前处理隐藏传输控制信息。bridge MUST使用当前Job File Principal JWT和固定内部流式路径；文档传输控制信息还 MUST绑定精确representation ID、source Version、size和SHA-256。bridge不得接受模型提供的URL、Header、Token、绝对路径、对象位置或冻结目录revision外的representation；SDK消息返回后再处理的旁路不满足本要求。

Agent Worker MUST验证Manifest v5 hash后，将其投影为Runtime 1.2/1.3已经发布的Manifest v4结构，剥离`workspace_catalog_revision_id`与`materialization_size_bytes`并重新派生投影hash，MUST NOT把Manifest v5或新增字段直接发送给Runtime。对所有`auto_materialize=true`项，Control Plane MUST在创建Job和outbox前按不同File/Version数量及待进入Sandbox的实际字节执行完整预检；Runtime MUST在首次模型请求前先为全部不同File/Version取得File Service基于冻结事实签发的隐藏传输控制及精确预期大小，在任何下载发生前整批预留，再主动物化全部精确文本版本或Markdown表示。任何prepare、整批预留或下载失败均使Job失败关闭且不得形成部分可见输入。其余文件只能由Agent先查询Manifest冻结的目录revision，再以精确File/Version请求并追加工作集；File Service从同一冻结事实解析可用文本版本或Markdown representation。

自动物化、File MCP按需物化、Write/Edit和内部临时文件 MUST全部通过同一个Job Sandbox预算与预留服务。自动物化bridge MUST先准备完整批次、再原子预留完整批次，只有整批预留成功后才可开始首个下载；File MCP bridge MUST在创建目标文件或下载首字节前预留`inputs`槽位与容量，并在失败、取消或完整性不匹配时清理部分文件并释放预留；不得因File Service已授权transfer而绕过40项输入、64文件分区或224MiB总容量。

#### Scenario: 当前消息文档在模型执行前已进入沙盒
- **WHEN** Job File Manifest包含一个合法`auto_materialize=true`的当前消息文档和Markdown representation
- **THEN** Runtime在首次模型请求前通过受控File bridge下载表示、校验大小与SHA-256并登记sandbox entry
- **AND** 模型只看到安全Markdown相对路径、原件身份和只读动作

#### Scenario: Agent显式提交沙盒文本文件
- **WHEN** Agent调用已冻结的文件提交工具并选择一个受控沙盒TXT或可写Markdown文件
- **THEN** Runtime使用当前Job绑定流式上传内容到File Service
- **AND** Tool事件只保留文件身份、版本、大小、哈希摘要和结果

#### Scenario: Runtime在模型看到结果前物化文档
- **WHEN** File Service为`file_prepare_materialization`返回绑定冻结目录revision和工作集事实的合法隐藏传输控制信息
- **THEN** Runtime bridge在该ToolResult返回模型前完成预算预留、流式下载、大小与SHA-256校验和sandbox entry登记
- **AND** 模型只收到安全Markdown相对路径、不透明handle、大小和摘要

#### Scenario: Runtime尝试物化原件或Docling JSON
- **WHEN** Runtime传输请求指向PDF、Office、图片原件或Docling JSON
- **THEN** File Service在返回字节前失败关闭
- **AND** 不因该对象属于同一source Version而扩大Agent读取能力

#### Scenario: 自动物化预检失败
- **WHEN** 计划自动物化的输入超过40个不同File/Version或实际Markdown总大小会突破224MiB
- **THEN** Control Plane在Job和outbox创建前完整拒绝并要求缩小工作集
- **AND** 不物化子集、不启动Runtime且不产生不完整Manifest
