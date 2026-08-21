## Context

当前实现有四个被错误耦合或不一致的边界：`WorkspaceQuotaService`把每个工作区限制为20个ACTIVE逻辑文件和100MiB临时计费内容；`JobFileManifestService._manifest_items`查询并冻结该工作区全部ACTIVE文件；Runtime使用40文件、224MiB的Job Sandbox同时承载输入、输出和临时文件；`JobSandbox._authorize_write`只保护Write/Edit，而`FileTransferCoordinator._materialize`通过File MCP下载后直接`open("xb")`写入Sandbox，没有调用同一文件数与总容量检查。`task_workspace_list_files`的数据源又只是当前Job Snapshot，不能发现未复制进Snapshot的工作区文件。

因此不能只修改`quota.py`常量。设计必须同时拆开持久容量、冻结目录、Job输入授权和本地Sandbox预算，保持File Service唯一对象事实入口、Principal JWT、当前授权复核、精确File/Version/Representation身份、不可变历史Job和既有Runtime 1.2/1.3协议。

## Goals / Non-Goals

**Goals:**

- 持久工作区默认容纳200个ACTIVE逻辑文件和2GiB计费内容，tenant覆盖绝不超过1000个与10GiB代码硬上限。
- 每个Job累计最多物化40个不同File/Version输入；自动与按需物化共用同一计数，重复同一版本不重复计数。
- Job Sandbox固定为64文件：`inputs`40、`work/outputs`16、`tmp`及安全余量8；总容量保持224MiB。
- Job创建前对全部计划自动物化输入执行文件数与实际字节完整预检，超限不创建Job，不产生部分物化。
- Manifest只冻结不可变`workspace_catalog_revision_id`及已经选定的精确工作集；Agent通过分页读取该冻结目录，再追加选择精确版本。
- 自动物化、File MCP物化、Write/Edit和内部临时文件都经过同一Sandbox预算与预留器。
- 先升级schema、Tool与兼容Publication，再提升tenant配额；旧Publication和历史Job不被静默扩权。

**Non-Goals:**

- 不把任务工作区扩成长期知识库、案件资料库或跨 Session 文件集合。
- 不在本变更增加向量检索、全文检索、模糊语义搜索或一次读取数百份正文。
- 不修改单文件15MiB、Docling源文件25MiB/PDF 300页或Sandbox 224MiB总容量；本变更明确修改工作区100MiB容量和Runtime 40文件总上限。
- 不新增 Runtime 协议版本，不改变历史 Job Manifest、Tool Snapshot 或 Publication。
- 不在本变更新增手工归档/恢复工具；既有工作区到期、附件保留和精确历史召回语义保持不变。

## Decisions

### 1. 持久容量、Job输入与Sandbox预算独立治理

采用五个互不替代的边界：

| 层级 | 默认/上限 | 含义 |
|---|---:|---|
| 持久工作区 ACTIVE 逻辑文件 | 默认 200，平台硬上限 1000 | 同一工作区可持续管理的逻辑文件目录 |
| 持久工作区计费内容 | 默认 2 GiB，tenant硬上限 10 GiB | 工作版本、冲突、staging与派生内容的受治理容量 |
| Job 输入物化工作集 | 最多 40 | 自动与按需物化累计的不同 File/Version；重复版本去重 |
| Runtime Sandbox 文件数 | 总计 64 | `inputs` 40、`work/outputs` 16、`tmp`与安全余量 8 |
| Runtime Sandbox 容量 | 224 MiB | 所有分区共享的实际本地字节硬上限 |

同一逻辑文件的新版本不增加ACTIVE文件数，但其实际计费字节仍按工作区容量规则处理。工作区已超过后来降低的tenant文件数或字节上限时，File Service允许按当前授权读取已有内容，但所有会继续增加对应用量的新逻辑文件、新版本、派生内容或staging必须失败关闭，直至用量回到有效上限；不得以另一个维度尚有余量为由放宽超限维度。

备选方案是只把20改成500或1000。否决原因是它没有拆开持久目录、单次输入授权和Sandbox资源，Manifest、数据库与Runtime仍会线性放大，File MCP绕过也仍存在。

### 2. 租户配额复用受治理 Runtime Config，不进入 Application Publication

新增两个非敏感整数定义：`FILE_WORKSPACE_ACTIVE_FILE_LIMIT`默认200、代码硬上限1000；`FILE_WORKSPACE_BILLABLE_BYTES_LIMIT`默认2GiB、代码硬上限10GiB。两者只适用`file-service`。平台Runtime Config增加`tenant` scope，`scope_code`使用平台tenant ID；File Service按tenant构造同一有效配额快照并记录config revision/source。定义校验、管理API和消费端都必须再次夹紧代码硬上限，配置和数据库值不能放宽。

字节计费延续文件领域的临时内容语义：未提升为独立Retained内容的工作版本、开放冲突候选、未终结staging和工作区派生表示/处理资产均计费；同一不可变对象在同一工作区按稳定身份只计一次。实现增加事务配额预留事实，将并发导入、处理、提交的预计新增字节和逻辑文件名额先预留，成功终结后转为实际用量，失败或过期后可重试释放；不得采用“先写对象、最后才发现超限”的竞争路径。

Business Application Publication继续冻结格式、文档处理Profile、File MCP Tool和执行策略，但不冻结tenant存储配额或Sandbox数值。Job File Snapshot记录创建时观察到的两个有效配额、配置revision/source和代码限制版本，供审计解释当时为什么允许或拒绝；Runtime协议不接收tenant配置对象。

备选方案是新建独立租户配额表。否决原因是现有 Runtime Config 已提供 typed value、scope、revision、管理认证和配置审计；新增第二套配置生命周期会重复治理。实施时必须为 `tenant` scope 增加严格 ID 校验与优先级，不能允许客户端伪造 tenant 上下文。

### 3. Manifest v5冻结目录revision与初始工作集，不复制候选目录

Manifest 生成按以下顺序构建：

1. 在Job创建事务中取得或创建当前不可变`workspace_catalog_revision_id`，冻结到Manifest v5头部；不复制该revision的200至1000个目录成员。
2. 将当前消息附件、明确引用、显式File/Version和创建前已经选定的精确工作集去重，冻结精确Version/Representation及自动物化标志；这些条目共同受40项Job输入上限。
3. 汇总全部计划自动物化的实际文本File Version或Markdown Representation大小，在写入Job与dispatch outbox前一次性预检40项输入上限和224MiB Sandbox容量；超限时保留已导入的工作区文件，但不创建Agent Job。
4. 不把名称、时间、格式查询候选或工作区全部ACTIVE文件写入Manifest。Agent只能通过分页Tool查询Manifest冻结的目录revision，再把精确结果追加到Job工作集。

计划输入超过40项或实际字节总和超过224MiB时，系统返回固定缩小工作集说明，不得通过只物化前缀、跳过大文件或创建随后必然失败的Job来降级。PDF、Office和图片只冻结其精确原始File/Version身份与最终可读Markdown Representation，预检和Sandbox均只计算实际进入`inputs`的Markdown；每个原始File/Version计一个输入。

历史Manifest v1-v4继续按原事实读取且不回填目录revision。Manifest v5增加`workspace_catalog_revision_id`和有界工作集语义，但Agent Worker投影给Runtime 1.2/1.3的文件条目结构保持不变；目录revision只供File Service搜索与授权，因此不需要Runtime协议升级。

备选方案是在Snapshot审计列中旁挂目录revision而继续声称Manifest v4。否决原因是目录revision决定该Job可发现的文件集合，属于Job不可变文件上下文身份；应明确发布Manifest v5，同时保持Runtime协议投影兼容。

### 4. 新增只返回元数据的工作区发现 Tool

新增固定 File MCP Tool `task_workspace_search_files`。其封闭输入只允许：

- `cursor` 与 `limit`（默认 20，最大 50）；
- 完整名称或名称前缀；
- 代码注册的 `format_codes`；
- UTC RFC 3339 `source_received_from/source_received_to`；
- 代码注册的可读状态过滤。

服务端从Principal JWT解析Job、用户、tenant、Session、Publication、workspace和Manifest冻结的`workspace_catalog_revision_id`；输入不得声明这些身份、revision、对象键、Bucket或URL。结果只含安全显示名、精确`file_id + version_id`、格式、大小、来源/版本时间、可读状态、`observed_at`、冻结目录revision和不透明下一页cursor。每页默认20、最多50；翻页次数不改变40项输入上限。

新增不可变`task_workspace_catalog_revision`及时间化目录成员事实。ACTIVE成员、逻辑名或选中版本变化时，在同一事务关闭旧成员有效区间、写入新事实并创建下一revision；不得为每个Job复制一整份目录。查询以Job冻结revision上的有效区间执行确定性keyset分页，cursor绑定workspace、过滤摘要、revision ID和最后排序键。同一Job在目录随后变化时仍稳定遍历旧revision；新Job冻结新revision。

精确选择时File Service重新检查当前主体与Application访问、source/representation血缘和内容可用性，但不因该版本不再是当前选中版本而自动替换或拒绝；只要它属于Job冻结目录revision且仍可访问，就按精确历史Version处理。内容已清理或权限撤销时失败关闭，不回退到当前最新版本。

现有 `task_workspace_list_files` 保持“只列当前 Job Snapshot”语义，避免悄悄扩大旧 Tool schema/hash。新发现能力使用新的 Tool identifier和schema hash。

备选方案是让cursor绑定当前可变目录并在revision变化时要求重查。否决原因是同一Job会因并发上传得到不同目录事实，无法重放。另一个备选是修改现有`task_workspace_list_files`；这会改变已冻结Publication的Tool schema和“Snapshot only”安全语义，因此新增独立Tool。

### 5. 运行中选择使用追加式 Job 工作集事实

新增`agent_job_file_working_set_item`，至少保存Job/Snapshot、workspace、冻结目录revision、精确File/Version、可选Representation身份与hash、选择来源、序号和时间。记录只追加不改写Manifest；`(job_id, file_id, version_id)`唯一，自动与按需路径都使用该去重键，重复物化同一版本幂等返回既有sandbox handle或相同精确选择，不重复计数。

`file_prepare_materialization` 输入 schema保持不变。若目标已在初始 Manifest 且有 `MATERIALIZE` 权限，沿用现有路径；若目标不在初始内容工作集，则仅在该 Job 同时冻结新 `task_workspace_search_files` Tool 时允许原子晋升：

1. 复核 Job仍为 RUNNING、Principal、用户、tenant、Session、Publication、workspace和当前角色；
2. 要求File/Version存在于Job冻结目录revision或初始附件/明确引用，并保持当前访问和内容可用；不得替换为“当前最新”版本；
3. 对文档冻结该Version在选择时AVAILABLE/PARTIAL的精确Markdown Representation；不可用时返回既有可读状态错误；
4. 对自动与按需输入按`File/Version`去重计数，超过40返回`job_file_working_set_limit_exceeded`；
5. 事务写入追加事实并创建受控materialization transfer；Runtime在下载前必须取得Sandbox输入文件数与字节预算预留。

追加项不改写初始 Manifest、不改变 Runtime request digest，也不成为长期授权。物化、交付和提交仍按各自动作实时复核；本变更只允许动态晋升为受治理读取内容，不自动授予 EDIT、COMMIT或DELIVER。

备选方案是运行中修改`agent_job_file_snapshot_item`。否决原因是它会破坏不可变Manifest hash和历史重放。备选方案是只依赖“Agent知道精确UUID”直接读取。否决原因是缺少Job级40项上限、冻结目录归属和审计事实。

### 6. 所有Sandbox写入共享一个预算与预留器

`JobSandbox`成为本地文件数、分区名额和总字节的唯一执行事实源，固定限制为：`inputs`40、`work/outputs`合计16、`tmp`与内部安全余量8、全Sandbox总计64文件和224MiB；marker、目录和不可见控制元数据不计普通文件数，但其实际磁盘开销仍由部署容量承担。15MiB单文件限制保持不变。

Runtime在首次模型请求前对自动物化批次调用`reserve_input_batch`，以去重File/Version、目标相对路径和Manifest冻结的实际大小一次性验证全部40/64文件数及224MiB容量；任一超限则在下载第一个字节前拒绝整个Job。File MCP按需物化也必须先调用同一预留器，再由`FileTransferCoordinator`下载、校验并提交预留；失败时删除不完整文件并释放预留。Write/Edit调用`reserve_work_output`，内部临时文件调用`reserve_tmp`，不得各自维护不一致的计数器。

Control Plane在Job创建事务前使用相同代码限制对计划自动物化集合做第一道完整预检，Runtime在本地创建Sandbox后再次验证，形成跨进程防御纵深。224MiB是所有分区共享的字节池，不承诺16个输出都能达到15MiB；输出或临时写入在当时剩余容量不足时仍须在副作用前拒绝。文件数分区则保证40个输入不会耗尽输出和临时文件名额。

当前`FileTransferCoordinator._materialize`直接创建目标文件而绕过`JobSandbox.usage()`，必须改为只接受绑定当前Sandbox预算的context/reservation；任何测试替身或新桥接路径也不能绕过。备选方案是在File Service单独估算Sandbox用量。否决原因是File Service不知道Runtime本地`work/outputs/tmp`实时状态，无法成为本地容量事实源。

### 7. 兼容性由新 Tool Presence 门禁，而不是 Runtime 协议版本

新 Agent Publication必须冻结 `task_workspace_search_files` 的精确 schema hash；Application Publication只有显式选择该 Tool后才具备大工作区动态发现/选择能力。File Service以当前 Job Tool Snapshot中是否存在该精确 Tool作为动态晋升门禁，旧 Job即使提交相同 File ID也仍只能访问原 Manifest。

旧 Publication在工作区 ACTIVE 文件数不超过20时继续得到现有兼容清单；当工作区已超过20且Job没有新发现Tool时，Job创建失败关闭为 `file_workspace_publication_upgrade_required`，而不是生成不完整上下文或把数百项放回 Manifest。

租户配额从20提升前，管理 API必须预检该租户所有启用且开启任务工作区的 Application Publication均已冻结兼容 Tool；存在不兼容发布时拒绝提升并列出安全的应用/发布身份。该门禁不会修改旧 Publication。

### 8. 索引与压测按目录查询模式设计

为时间化目录成员增加覆盖`workspace_id + valid_from_revision + valid_to_revision + logical_name + file_id`的分页索引，并为来源时间/格式过滤使用能从冻结revision有效集合开始的组合索引或等价执行计划。SQLite和PostgreSQL必须使用相同的快照可见性、确定性排序与cursor语义；不得为每个Job复制1000行目录快照。

验收至少覆盖200和1000个ACTIVE文件、2GiB默认/10GiB硬容量边界、冻结目录revision分页、40个输入、64文件/224MiB Sandbox、多个并发Job、Docling处理中/可用表示以及所有物化入口。性能证据记录Snapshot行数、Manifest大小、Job创建P95、搜索P95、数据库查询计划和Sandbox预检耗时；容器健康不能替代完整Job链路证据。

## Risks / Trade-offs

- [Agent 需要多一次搜索/物化调用] → 保留当前附件、引用和完整文件名的直接初始绑定；只有不明确目标才分页发现。
- [动态工作集看起来绕过不可变Manifest] → 使用冻结目录revision、独立追加事实、精确Tool Snapshot门禁、40项硬上限和实时授权，绝不修改Manifest/hash。
- [tenant降低文件数或字节配额后已有工作区超限] → 保持既有内容可读，但拒绝任何继续增加超限维度的创建/处理/提交，并显示当前用量、预留和有效上限。
- [目录变化导致同一Job重放不一致] → Job冻结不可变catalog revision，时间化成员支持稳定分页；新变化只进入后续Job。
- [历史目录事实增长] → 只为发生变化的成员写时间化事实并按工作区生命周期安全压缩不可再引用的revision，不为每个Job复制目录。
- [224MiB不足以同时容纳40个15MiB输入] → 使用实际Markdown大小做整批预检；40是数量上限而非容量承诺，超容量要求缩小工作集，不物化前缀。
- [File MCP再次绕过Sandbox限制] → `FileTransferCoordinator`必须持有统一预算预留，合同测试枚举自动物化、按需物化、Write/Edit和tmp全部入口。
- [旧Application在大工作区产生错误认知] → 超过20且缺少新Tool时在Job创建前失败关闭，配额提升前做租户级兼容预检。
- [新增tenant runtime scope被其它配置误用] → 只允许代码注册为tenant-compatible的定义使用该scope，并从认证上下文解析tenant，不接受任意请求覆盖。

## Migration Plan

1. 使用下一可用forward migration增加tenant Runtime Config scope、两个配额定义所需schema、不可变目录revision/时间化成员、Manifest v5头部、Job工作集、配额预留事实和索引；现有tenant先显式保持20个/100MiB有效值。
2. 在Python Runtime实现64文件分区和统一Sandbox预算预留，让自动物化、File MCP物化、Write/Edit和tmp路径全部接线；保持224MiB并先通过绕过回归测试。
3. 发布File Service的Manifest v5、冻结目录搜索Tool、追加选择、事务工作区配额和授权逻辑；旧Tool、历史Manifest v1-v4和历史Job回归必须通过。
4. 发布包含新Tool schema hash的Agent Release，并创建兼容Application Publication；不原地修改已发布对象。
5. 对目标tenant运行只读兼容预检，以及200/1000文件、2/10GiB边界、40输入和64文件/224MiB Sandbox压测；通过后把有效配额改为200个/2GiB并记录配置审计。
6. 进行真实Runtime→冻结目录分页→精确选择→Markdown物化→Agent输出/Delivery全链E2E；确认未选文件及原始二进制未进入Sandbox，所有写入入口均受统一预算。
7. 回滚时先把tenant有效上限恢复到20个/100MiB并停止新兼容Publication流量；已超限工作区保持已有内容可读但不得增加超限维度。保留新schema、历史目录revision和工作集事实，不删除或改写已完成Job。

## Open Questions

- 无阻塞问题。首版固定为工作区默认200个/2GiB、tenant硬上限1000个/10GiB、Job输入40、Sandbox文件64（40/16/8）和总容量224MiB；后续若需调整Job或Sandbox边界，必须通过新的OpenSpec与代码合同，不得使用tenant配置放宽。
