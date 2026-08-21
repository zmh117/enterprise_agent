## Context

当前实现有三个被错误耦合的数量边界：`WorkspaceQuotaService` 把每个工作区限制为 20 个 ACTIVE 逻辑文件；`JobFileManifestService._manifest_items` 查询并冻结该工作区全部 ACTIVE 文件；Runtime 再接收整份 Manifest，并在 40 文件、224 MiB 的 Job Sandbox 内物化被标记的内容。`task_workspace_list_files` 虽有游标，但数据源只是当前 Job Snapshot，不能发现未进入 Snapshot 的工作区文件。

因此把 `MAX_WORKSPACE_FILES` 直接从 20 改成 200 或 1000 会让每次 Job 的 Snapshot、Manifest hash、Runtime 请求和 Agent 文件提示一起线性增长，也无法证明未选中文件没有进入单次执行授权。设计必须保持 File Service 唯一对象事实入口、Principal JWT、当前授权复核、精确 File/Version/Representation 身份、不可变历史 Job 和既有 Runtime 1.2/1.3 协议。

## Goals / Non-Goals

**Goals:**

- 持久工作区默认容纳 200 个 ACTIVE 逻辑文件，租户有效值可调但绝不超过代码硬上限 1000。
- 每个 Job 最多携带 50 个元数据候选和 20 个内容工作集项；未选中文件不进入 Sandbox。
- Agent 可以通过分页和有界过滤发现大工作区中的精确 File/Version，再以显式、可审计动作选择内容。
- 保持 Job 初始 Manifest 不可变；运行中新增选择使用独立的追加事实，不改写 Manifest 或历史 Runtime 请求。
- 先升级 Tool Publication，再提升租户配额；旧 Publication 和历史 Job 不被静默扩权。

**Non-Goals:**

- 不把任务工作区扩成长期知识库、案件资料库或跨 Session 文件集合。
- 不在本变更增加向量检索、全文检索、模糊语义搜索或一次读取数百份正文。
- 不修改单文件 15 MiB、Docling 源文件 25 MiB/PDF 300 页、工作区临时容量 100 MiB、Runtime 40 文件/224 MiB 等既有内容边界。
- 不新增 Runtime 协议版本，不改变历史 Job Manifest、Tool Snapshot 或 Publication。
- 不在本变更新增手工归档/恢复工具；既有工作区到期、附件保留和精确历史召回语义保持不变。

## Decisions

### 1. 三层配额独立治理

采用三个互不替代的硬边界：

| 层级 | 默认/上限 | 含义 |
|---|---:|---|
| 持久工作区 ACTIVE 逻辑文件 | 默认 200，平台硬上限 1000 | 同一工作区可持续管理的逻辑文件目录 |
| Job 元数据候选 | 最多 50 | 不含正文、对象位置和凭据的发现结果 |
| Job 内容工作集 | 最多 20 | 本 Job 可取得内容或精确 Representation 的 File/Version |
| Runtime Sandbox | 保持 40 文件、224 MiB | 输入、输出和必要临时文件的最终本地硬边界 |

同一逻辑文件的新版本不增加 ACTIVE 文件数，但继续计入既有临时容量规则。工作区已超过后来降低的租户上限时，File Service允许读取和为既有逻辑文件创建新版本，但拒绝新增逻辑文件，直到 ACTIVE 数量回到有效上限以内。

备选方案是只把 20 改成 500。否决原因是它没有拆开持久目录和单次执行，Manifest、数据库与 Runtime 仍会无界放大。

### 2. 租户配额复用受治理 Runtime Config，不进入 Application Publication

新增非敏感整数定义 `FILE_WORKSPACE_ACTIVE_FILE_LIMIT`，代码默认值 200，适用 `file-service`。平台 Runtime Config 增加 `tenant` scope，`scope_code` 使用平台 tenant ID；File Service按 tenant 构造有效配置快照并记录 config revision/source。值必须在 `1..1000`，1000 是代码常量，配置和数据库值均不能放宽。

Business Application Publication 继续冻结格式、文档处理 Profile、File MCP Tool 和执行策略，但不冻结租户存储配额。Job File Snapshot记录创建时观察到的有效文件数上限与配置 revision，供审计解释当时为什么允许或拒绝，不把该值加入 Runtime schema 或 Manifest v4 hash。

备选方案是新建独立租户配额表。否决原因是现有 Runtime Config 已提供 typed value、scope、revision、管理认证和配置审计；新增第二套配置生命周期会重复治理。实施时必须为 `tenant` scope 增加严格 ID 校验与优先级，不能允许客户端伪造 tenant 上下文。

### 3. 初始 Manifest 只冻结有界初始项和候选

Manifest 生成按以下顺序构建：

1. 当前消息附件、引用消息、显式 File/Version ID、完整文件名等确定性内容依赖；去重后最多 20 个，冻结精确 Version/Representation 并按既有规则决定自动物化。
2. 从 File Context Resolver 已命中的时间/格式/名称条件中选择不超过 50 个元数据候选，候选只获得 `READ_METADATA`，不得自动物化。
3. 不再执行“查询工作区全部 ACTIVE 文件并逐条写 Snapshot”的默认路径。

内容依赖超过 20 时，附件仍完成导入并保留在工作区，但系统返回固定缩小范围说明且不创建 Agent Job，不静默丢弃后面的文件。候选超过 50 时只返回固定缩小过滤范围说明或冻结确定性排序的首 50 项并明确 `truncated=true`；涉及正文读取的请求不得让模型从截断集合猜测目标。

历史 Manifest v1-v4 继续按原事实读取。新 Snapshot 仍使用 Manifest schema v4；新增的配额与目录 revision 是控制面审计字段，不进入 Runtime v1.2/v1.3 请求，因此不需要协议升级。

备选方案是发布 Manifest v5。否决原因是本变更没有改变 Runtime 自动物化条目结构，只改变控制面如何选出条目；为此升级跨服务协议会扩大兼容范围。

### 4. 新增只返回元数据的工作区发现 Tool

新增固定 File MCP Tool `task_workspace_search_files`。其封闭输入只允许：

- `cursor` 与 `limit`（默认 20，最大 50）；
- 完整名称或名称前缀；
- 代码注册的 `format_codes`；
- UTC RFC 3339 `source_received_from/source_received_to`；
- 代码注册的可读状态过滤。

服务端从 Principal JWT 解析 Job、用户、tenant、Session、Publication和workspace；输入不得声明这些身份、对象键、Bucket或URL。结果只含安全显示名、精确 `file_id + version_id`、格式、大小、来源/版本时间、可读状态、`observed_at`、目录 revision和不透明下一页 cursor。

`task_workspace` 增加单调 `catalog_revision`。活动目录成员、逻辑名或选中版本变化时在同一事务递增。cursor 绑定 workspace、过滤摘要、catalog revision和最后排序键；revision变化或过滤不一致时返回 `workspace_catalog_changed`，要求重新开始查询，避免并发编辑导致跨页漏项或重复项。

现有 `task_workspace_list_files` 保持“只列当前 Job Snapshot”语义，避免悄悄扩大旧 Tool schema/hash。新发现能力使用新的 Tool identifier和schema hash。

备选方案是修改现有 `task_workspace_list_files`。否决原因是这会改变已冻结 Publication 的 Tool schema和“Snapshot only”安全语义。

### 5. 运行中选择使用追加式 Job 工作集事实

新增 `agent_job_file_working_set_item`，至少保存 Job/Snapshot、workspace、精确 File/Version、可选 Representation 身份与hash、选择来源、选择时目录 revision、序号和时间。记录只追加不更新；`(job_id, file_id, version_id)` 唯一，重复选择幂等返回原记录。

`file_prepare_materialization` 输入 schema保持不变。若目标已在初始 Manifest 且有 `MATERIALIZE` 权限，沿用现有路径；若目标不在初始内容工作集，则仅在该 Job 同时冻结新 `task_workspace_search_files` Tool 时允许原子晋升：

1. 复核 Job仍为 RUNNING、Principal、用户、tenant、Session、Publication、workspace和当前角色；
2. 要求 File仍是该 ACTIVE workspace成员，提供的 Version仍是当前选中版本；目录已变化则要求重新搜索；
3. 对文档冻结当时 AVAILABLE/PARTIAL 的精确 Markdown Representation；不可用时返回既有可读状态错误；
4. 对初始项与追加项去重计数，超过 20 返回 `job_file_working_set_limit_exceeded`；
5. 事务写入追加事实后再创建受控 materialization transfer。

追加项不改写初始 Manifest、不改变 Runtime request digest，也不成为长期授权。物化、交付和提交仍按各自动作实时复核；本变更只允许动态晋升为受治理读取内容，不自动授予 EDIT、COMMIT或DELIVER。

备选方案是运行中修改 `agent_job_file_snapshot_item`。否决原因是它会破坏不可变 Manifest hash和历史重放。备选方案是只依赖“Agent知道精确UUID”直接读取。否决原因是缺少 Job 级选择上限和审计事实。

### 6. 兼容性由新 Tool Presence 门禁，而不是 Runtime 协议版本

新 Agent Publication必须冻结 `task_workspace_search_files` 的精确 schema hash；Application Publication只有显式选择该 Tool后才具备大工作区动态发现/选择能力。File Service以当前 Job Tool Snapshot中是否存在该精确 Tool作为动态晋升门禁，旧 Job即使提交相同 File ID也仍只能访问原 Manifest。

旧 Publication在工作区 ACTIVE 文件数不超过20时继续得到现有兼容清单；当工作区已超过20且Job没有新发现Tool时，Job创建失败关闭为 `file_workspace_publication_upgrade_required`，而不是生成不完整上下文或把数百项放回 Manifest。

租户配额从20提升前，管理 API必须预检该租户所有启用且开启任务工作区的 Application Publication均已冻结兼容 Tool；存在不兼容发布时拒绝提升并列出安全的应用/发布身份。该门禁不会修改旧 Publication。

### 7. 索引与压测按目录查询模式设计

为 `task_workspace_file` 增加覆盖 `workspace_id + status + logical_name + file_id` 的分页索引，并为来源时间/格式过滤使用能从 workspace ACTIVE集合开始的组合索引或经 `managed_file` 连接的等价执行计划。SQLite和PostgreSQL必须使用相同的确定性排序与cursor语义。

验收至少覆盖 200 和1000 ACTIVE文件、50候选、20内容项、并发目录revision变化、多个并发Job、Docling处理中/可用表示以及 Runtime沙盒上限。性能证据记录Snapshot行数、Manifest大小、Job创建P95、搜索P95和数据库查询计划；容器健康不能替代完整Job链路证据。

## Risks / Trade-offs

- [Agent 需要多一次搜索/物化调用] → 保留当前附件、引用和完整文件名的直接初始绑定；只有不明确目标才分页发现。
- [动态工作集看起来绕过不可变 Manifest] → 使用独立追加事实、精确 Tool Snapshot门禁、20项硬上限和实时授权，绝不修改 Manifest/hash。
- [租户降低配额后已有工作区超限] → 允许读取和更新既有逻辑文件，只拒绝新增逻辑文件；管理端明确显示当前用量与有效上限。
- [并发编辑导致分页错乱] → cursor绑定 `catalog_revision`，revision变化立即失败并要求重新查询。
- [50个候选仍增大模型上下文] → 候选只含有界元数据；正文不预加载，超限要求缩小过滤条件。
- [旧Application在大工作区产生错误认知] → 超过20且缺少新Tool时在Job创建前失败关闭，配额提升前做租户级兼容预检。
- [新增tenant runtime scope被其它配置误用] → 只允许代码注册为tenant-compatible的定义使用该scope，并从认证上下文解析tenant，不接受任意请求覆盖。

## Migration Plan

1. 添加 `tenant` Runtime Config scope、`FILE_WORKSPACE_ACTIVE_FILE_LIMIT` 定义、`task_workspace.catalog_revision`、Job Snapshot审计字段、追加工作集表和目录索引；现有租户先显式保持有效上限20。
2. 发布 File Service 的有界 Manifest、搜索Tool、追加选择与授权逻辑；旧Tool和历史Manifest回归必须通过。
3. 发布包含新Tool schema hash的 Agent Release，并创建兼容 Application Publication；不原地修改已发布对象。
4. 对目标租户运行只读兼容预检和200/1000文件压测；预检通过后把该租户有效上限改为200并记录配置审计。
5. 进行真实 Runtime → File MCP搜索 → 精确选择 → Markdown物化 → Agent回复/Delivery 的全链E2E；监控 Manifest项数、工作集拒绝、目录revision冲突和搜索延迟。
6. 回滚时先把租户有效上限恢复到20并停止新兼容Publication流量；已超过20的工作区保持可读但不得新增逻辑文件。保留新表和历史选择事实，不删除或改写已完成Job。

## Open Questions

- 无阻塞问题。首版固定为默认200、硬上限1000、候选50、内容工作集20；后续若压测显示需要调整候选或工作集上限，必须通过新的代码Profile和OpenSpec变更，而不是普通租户配置放宽。
