## ADDED Requirements

### Requirement: 资源查询结果必须复用 Job 临时只读文件
Runtime SHALL 对已冻结授权的 query_database、query_redis_get、query_redis_scan、query_loki、diagnose_loki_probe 的成功正文使用 JobSandbox 原子预留和只读发布，模型仅接收安全元数据、代码生成的 work/*.md 相对路径与 Read/Grep 提示。正文 MUST 标为外部不可信数据并保持现有脱敏。目录/schema/标签元数据不强制落盘。无 File MCP 的查询 Job 只派生 Read/Glob/Grep，不授予 Write/Edit/提交或跨 Job 权限。使用 512 MiB/128 文件、单文件 15 MiB、inputs 40、work/outputs 共 80、tmp 8 的 sandbox-v2 数值配额及终态/恢复清理，不能自动持久化结果或删除独立审计。

#### Scenario: 大于摘要预算的查询正文
- **WHEN** 已授权查询取回超过 4000 字符但未超过独立结果容量的正文
- **THEN** 全部实际返回正文写入只读文件，内联响应只保留数量、完整性、分页控制和文件元数据

#### Scenario: 非完整分页
- **WHEN** Redis SCAN 仍有 next_cursor 或 Loki 达到查询行数上限
- **THEN** 当前文件内容完整但查询 complete=false，保留可用的原分页状态而不自动无界翻页

#### Scenario: 容量或协议失败
- **WHEN** 结果超过容量、协议校验失败或文件写入失败
- **THEN** 清理未完成文件并释放预留，返回安全错误而不发布成功路径或回退内联大正文

#### Scenario: Job 结束
- **WHEN** Job 成功、失败、取消、超时或异常退出后被恢复扫描确认不再运行
- **THEN** 临时结果随该 Sandbox 清理，不触及其他 Job 或独立审计

## MODIFIED Requirements

### Requirement: Job 创建时冻结精确文件清单
非空文字经准入后，File Service MUST 冻结 schema v5 Job File Manifest 与 hash，包含 Job/workspace、`workspace_catalog_revision_id` 以及本轮确定性绑定的精确 File/Version 工作集；不得复制全部工作区目录。需转换文档的可物化项 MUST 同时冻结 Markdown Representation ID、kind、format、size、SHA-256、创建时间与安全物化名。只自动物化本轮已绑定且能力就绪的直接文本或表示；时段发现保持元数据。其余版本通过冻结目录分页后精确选择。源/表示身份固定，授权在操作时重新校验。

Manifest MUST 区分 source_received_at、version_created_at、representation_created_at 与 observed_at。source_received_at 来自原 message_attachment 创建时间并沿版本/表示保持不变，Agent 生成文件为 null。非空机器时间使用 UTC RFC 3339 并进入 canonical hash；不能生成、读取、投影或恢复 Manifest v1–v4。无文件 Job MUST 使用合法空文件上下文。

#### Scenario: 新版本或新表示产生
- **WHEN** Job 冻结 source V3、representation R1 后出现 V4 或 R2
- **THEN** 当前 Job 继续物化 V3/R1，新版本只进入后续目录与 Job

#### Scenario: 大目录小工作集
- **WHEN** 工作区目录有 1000 个 ACTIVE 文件，本轮只有两个精确输入
- **THEN** Manifest 只保存目录 revision 与这两个输入，Runtime 只预检和自动物化这两个

#### Scenario: 自动物化整批超限
- **WHEN** 本轮自动物化超过 40 个不同版本或其实际文本/Markdown 超过 512 MiB
- **THEN** 创建 Job 和 Outbox 前完整拒绝并要求缩小范围，不启动只有部分输入的执行

#### Scenario: 表示被替换或旧 schema 到达
- **WHEN** 请求使用不属于精确 source Version 的表示或旧 Manifest schema
- **THEN** 在对象读取与模型调用前失败关闭，不投影、不计算旧 hash

#### Scenario: 无来源生成文件
- **WHEN** 文件由 Agent 生成而非聊天附件导入
- **THEN** source_received_at 为 null，version_created_at 非空，不把生成时间说成上传时间

### Requirement: 每个 Agent Job 使用隔离临时沙盒
Runtime MUST为每个Agent Job创建独立Job Sandbox，并只把当前Job已授权工作集、ONES查询结果和代码派生证据按各自规则写入该目录。Sandbox MUST固定总文件上限128和总容量512MiB，并分别限制`inputs`最多40个文件、`work/outputs`合计最多80个文件、`tmp`及内部安全余量最多8个文件；目录、marker和不可见控制元数据不得被模型用来规避普通文件计数。PDF、Office、图片原始二进制、Docling JSON和OCR Layout JSON MUST NOT进入Agent Sandbox。

模型提交的路径 MUST 为安全相对路径；若 bundled CLI 在权限回调前解析为绝对路径，Runtime 仅可将词法上精确属于本次随机 Sandbox 根、规范化和符号链接检查均通过的路径还原为相对路径。沙盒外绝对路径、相邻前缀和模型可见绝对路径能力仍须拒绝。

自动物化、File MCP按需物化、Runtime Write/Edit、日志证据扫描生成的临时`work/`证据包和内部临时文件 MUST共享同一Sandbox预算与原子预留器。Runtime在写入第一个自动物化字节前 MUST对整批输入重新预留实际文件数与Manifest冻结大小；按需物化、写入和日志证据扫描 MUST在创建目标文件前预留对应分区名额和剩余容量。失败或完整性校验不通过 MUST删除不完整文件并释放预留。重复物化同一`file_id + version_id` MUST复用已有输入和handle，不重复占用文件数或字节。Claude Code Agent只可在该沙盒内使用`Read`、`Grep`、`Glob`、`Write`和`Edit`，以及在当前Job冻结只读物化能力时使用Runtime派生的`scan_log_evidence`；写/编辑动作仍受代码固定`text-v2`格式矩阵限制。Bash、Web、NotebookEdit、沙盒外路径、符号链接逃逸和其它开放执行能力 MUST保持不可用。Job成功、失败、取消或超时后 MUST清理沙盒，Runtime异常退出后 MUST由恢复扫描清理无RUNNING Job归属的残留目录。

#### Scenario: Agent读取PDF派生Markdown
- **WHEN** Job获得受控PDF source Version及其Markdown representation
- **THEN** Runtime只在安全inputs路径物化经过大小和SHA-256校验的Markdown
- **AND** 本地副本不改变MinIO、原始版本或representation

#### Scenario: Agent在沙盒内编辑文本输出
- **WHEN** Job按冻结文本策略获得可写TXT或Markdown并调用Edit
- **THEN** Runtime只允许规范化后仍位于该Job沙盒的目标路径
- **AND** 本地修改不直接改变MinIO或文件版本

#### Scenario: Agent尝试写沙盒外路径
- **WHEN** `Write`或`Edit`目标通过绝对路径、`..`、符号链接或其它方式离开Job Sandbox
- **THEN** Runtime在文件系统副作用前拒绝并记录安全工具结果

#### Scenario: Agent尝试读取原始二进制
- **WHEN** Agent或Runtime请求把PDF、Office或图片source Version直接物化到沙盒
- **THEN** File Service拒绝并只允许Manifest冻结的Markdown representation路径

#### Scenario: Agent在沙盒内编辑Markdown
- **WHEN** `text-v2` Job获得受控`.md`文件并调用`Edit`
- **THEN** Runtime只允许规范化后仍位于该Job沙盒且format允许`EDIT`的目标路径
- **AND** 本地修改不直接改变MinIO或文件版本

#### Scenario: Agent尝试编辑LOG
- **WHEN** Agent对沙盒内`.log`调用`Write`或`Edit`
- **THEN** Runtime在文件系统副作用前以稳定只读格式错误拒绝
- **AND** 不允许通过改名、绝对路径或handle复用绕过

#### Scenario: Agent读取Office派生Markdown
- **WHEN** Job工作集获得受控DOCX source Version及其Markdown representation
- **THEN** Runtime只在安全`inputs`路径物化经过大小和SHA-256校验的Markdown并计为一个输入
- **AND** 原始DOCX、Docling JSON和内嵌图片不进入Sandbox

#### Scenario: File MCP物化达到输入上限
- **WHEN** Sandbox已经成功物化40个不同File/Version输入且Agent请求第41个
- **THEN** Runtime与File Service在创建目标文件前拒绝`job_file_working_set_limit_exceeded`
- **AND** 不创建transfer残留、Sandbox文件或第41个有效工作集输入

#### Scenario: 输入文件数未满但容量不足
- **WHEN** 下一份Markdown会使Sandbox实际文件总量超过512MiB
- **THEN** 统一预算在下载字节前拒绝并返回安全容量错误
- **AND** 不因File MCP路径不同而绕过Write/Edit使用的容量边界

#### Scenario: Agent在沙盒内生成输出
- **WHEN** 40个输入均已占用且`work/outputs`仍有分区名额和总字节余量
- **THEN** Runtime允许在80个输出/工作文件上限内创建受支持文本
- **AND** 输入文件数不得消耗输出分区名额

#### Scenario: 日志扫描证据包占用工作分区
- **WHEN** Runtime准备为已物化LOG生成一个证据包
- **THEN** 证据包在读取首个输入字节前原子预留一个`work/outputs`文件名额和代码固定的最大容量
- **AND** 不得挤占输入分区名额、绕过512MiB总容量或把未完成文件暴露给模型

#### Scenario: 保持既有 sandbox-v2 标识扩容
- **WHEN** 系统按新配额部署并完成 136 迁移
- **THEN** 新 Job 快照冻结 512 MiB/128 文件且 sandbox_limit_version 仍为 sandbox-v2；Runtime 协议、Manifest v5 与派生工具 schema 不升级
- **AND** 历史快照的数值、版本及 hash 保持不变；升级前排空旧 Job，启动 env 必须匹配当前代码配额


### Requirement: Runtime 通过受控文件桥完成物化和提交
Runtime MUST通过File Service受控流式接口下载Job初始Manifest或追加工作集中的精确文本File Version或精确Markdown Representation，并上传Agent显式选中的受支持沙盒文本文件。PDF、Office、图片原始二进制和Docling JSON不得进入Agent Sandbox。File MCP只创建物化或提交意图并返回不透明标识，流式传输不得把完整文件字节直接嵌入初始模型上下文、MCP传输控制JSON或普通Tool审计；Agent通过授权Read/Grep实际读取并进入SDK消息的片段由 execution-delivery 的完整审计专用链处理。Runtime不得获得MinIO凭据、Bucket、对象键或可供模型使用的上传URL。

Python Runtime MUST使用代码注册的进程内File MCP bridge代理Job冻结的部署固定File Service工具，并在远端ToolResult交回模型前处理隐藏传输控制信息。bridge MUST使用当前Job File Principal JWT和固定内部流式路径；文档传输控制信息还 MUST绑定精确representation ID、source Version、size和SHA-256。bridge不得接受模型提供的URL、Header、Token、绝对路径、对象位置或冻结目录revision外的representation；SDK消息返回后再处理的旁路不满足本要求。

Agent Worker MUST验证Manifest v5 hash后，将schema v5文件上下文原样传给当前受支持 Runtime 协议，MUST NOT投影、生成或读取Manifest v1-v4。对所有`auto_materialize=true`项，Control Plane MUST在创建Job和outbox前按不同File/Version数量及待进入Sandbox的实际字节执行完整预检；Runtime MUST在首次模型请求前先为全部不同File/Version取得File Service基于冻结事实签发的隐藏传输控制及精确预期大小，在任何下载发生前整批预留，再主动物化全部精确文本版本或Markdown表示。任何prepare、整批预留或下载失败均使Job失败关闭且不得形成部分可见输入。其余文件只能由Agent先查询Manifest冻结的目录revision，再以精确File/Version请求并追加工作集；File Service从同一冻结事实解析可用文本版本或Markdown representation。

自动物化、File MCP按需物化、Write/Edit和内部临时文件 MUST全部通过同一个Job Sandbox预算与预留服务。自动物化bridge MUST先准备完整批次、再原子预留完整批次，只有整批预留成功后才可开始首个下载；File MCP bridge MUST在创建目标文件或下载首字节前预留`inputs`槽位与容量，并在失败、取消或完整性不匹配时清理部分文件并释放预留；不得因File Service已授权transfer而绕过40项输入、128文件分区或512MiB总容量。

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

#### Scenario: 当前消息文本附件在模型执行前已进入沙盒
- **WHEN** Job File Manifest包含合法`auto_materialize=true`的当前消息TXT、LOG或Markdown精确版本
- **THEN** Runtime在首次模型请求前通过受控File bridge完成下载、format、大小和SHA-256校验及sandbox entry登记
- **AND** 模型只从安全相对路径读取且LOG entry不包含写操作

#### Scenario: Agent尝试提交LOG沙盒文件
- **WHEN** Agent把`.log`路径或handle传给输出选择器或提交工具
- **THEN** Runtime与File Service均在接收正文前拒绝
- **AND** 不创建Commit Intent、staging、版本或Delivery

#### Scenario: Agent按需物化仍在处理的文档
- **WHEN** Agent 对 Manifest 中一份可读表示未就绪的候选调用 `file_prepare_materialization`
- **THEN** File Service 在读取对象前拒绝并返回稳定未就绪错误码
- **AND** Runtime 不把该结果升级为自动物化失败，也不向模型提供伪造正文

#### Scenario: 自动物化预检失败
- **WHEN** 计划自动物化的输入超过40个不同File/Version或实际Markdown总大小会突破512MiB
- **THEN** Control Plane在Job和outbox创建前完整拒绝并要求缩小工作集
- **AND** 不物化子集、不启动Runtime且不产生不完整Manifest
