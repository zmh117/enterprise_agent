## Why

当前任务工作区最多只能保存20个ACTIVE逻辑文件和100MiB计费内容，且每次Job会把工作区全部ACTIVE文件逐条冻结进Job File Manifest。与此同时，Runtime的40文件总上限同时承担输入、输出和临时文件，File MCP物化路径又绕过了Sandbox文件数与总容量检查；直接调大`quota.py`常量既会放大Manifest，也可能让物化占满Sandbox或突破本地安全边界。

## What Changes

- 将持久工作区、Job输入工作集和Runtime Sandbox分层治理：工作区默认200个ACTIVE逻辑文件、平台硬上限1000；工作区计费容量默认2GiB、tenant硬上限10GiB。
- Job Manifest不再复制200至1000个目录条目，也不内嵌元数据候选；它只冻结`workspace_catalog_revision_id`、当前附件、明确引用和创建时已经选定的精确工作集。
- 新增不可变工作区目录revision和分页发现能力。Agent通过当前Job冻结的目录revision查询有界元数据，再精确选择File/Version；搜索结果不授予内容访问，也不进入Manifest。
- 每个Job最多物化40个不同File/Version输入，自动物化与按需物化累计计数；重复物化同一版本幂等复用，不重复占用输入名额。
- Runtime Sandbox总文件上限调整为64并按用途固定分区：`inputs`最多40，`work/outputs`合计最多16，`tmp`及安全余量最多8；总容量暂时保持224MiB。
- Job创建前对全部计划自动物化的实际文本/Markdown大小和文件数做完整预检，超限时不创建Job并要求缩小工作集；PDF、Office和图片只按真正进入Sandbox的Markdown计费，每个原始File/Version算一个输入，原始二进制不得进入。
- 将自动物化、File MCP按需物化、Runtime Write/Edit及内部临时文件统一接入同一Sandbox预算与预留器，修复当前File MCP下载直接写文件而绕过数量和总容量检查的问题。
- 工作区数量和字节配额由平台/tenant治理策略决定，不写入Business Application Publication；Job冻结配额revision、目录revision和追加式工作集事实以便审计。
- 采用兼容上线：先发布schema、目录Tool、统一Sandbox预算和兼容Agent/Application Publication，再把tenant有效配额从20个/100MiB提升到200个/2GiB；Runtime 1.2/1.3执行协议保持不变。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `task-file-workspace`: 拆分持久目录、冻结目录revision和40项Job输入工作集，增加200/1000文件与2/10GiB tenant配额、分页发现和原子预检要求。
- `execution-delivery`: Job File Manifest改为冻结目录revision与有界初始工作集，增加追加式精确选择和统一Sandbox预算；保持既有Runtime协议版本。
- `builtin-tool-resource`: 增加封闭Schema的冻结目录发现能力，并要求File MCP物化经过Job工作集和Runtime Sandbox双重准入。
- `business-application`: 新Publication在启用大工作区能力时必须冻结兼容File MCP Tool子集；文件数、字节数和Sandbox配额均不得进入Application Publication。
- `platform-operations`: 平台运行配置增加文件数200/1000和容量2/10GiB的tenant治理，并冻结64文件/224MiB Sandbox部署、就绪和上线证据。

## Impact

- 数据与迁移：复用平台运行配置保存tenant文件数和字节配额，新增不可变目录revision、时间化目录成员、Job工作集及配额预留事实；不回填或改写历史Manifest。
- File Service：事务配额预留、Manifest v5生成、冻结目录查询、File MCP授权、物化工作集、归档/召回和审计路径。
- Control Plane：Job创建前完整输入预检、兼容Publication校验和无Job拒绝路径。
- Agent/Runtime：新增固定File MCP目录Tool和Agent提示；Sandbox从40调整为64文件并让所有写入路径共享预算，Runtime请求协议保持不变。
- 管理与运维：tenant文件数/字节配额配置与诊断、兼容性预检、分阶段启用，以及200/1000文件、2/10GiB边界、40输入和64文件Sandbox压测。
