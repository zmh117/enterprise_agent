# 实施证据

## 2026-11-09 退役范围盘点

- 当前本机 PostgreSQL schema head：159。通过只读事务执行 code_knowledge_inventory，未读取正文或认证材料，未修改数据库。
- 清单：`.local/code-knowledge-redesign/retirement-inventory-20261109.json`。包含具体来源/KB/文档/修订/构建/操作/工具发布标识，摘要 `6d94fd227303ef5693b7d3b633816ead109c072d9afbdd918ef322511f806ca5`；这是本次观察，切换前必须重新计算，不能直接复用旧摘要执行删除。
- 1 个旧代码绑定，79 条代码文档及 79 条修订；其他来源 15,778 条文档。代码专属向量索引为 0；代码/其他 KB 混合收录、跨来源关系引用计数均为 0。
- 8 个旧构建：7 个 FAILED，1 个 VALIDATING/active；未发现未确认停止的已准入代码 Runtime invocation。切换仍需排空旧写者，并明确关闭残留构建；未因这一观察自动清理。
- 24 条旧 SVN 操作：2 个检出成功、21 个浏览成功、1 个浏览失败。已有目录保留。
- 盘点器本地测试：1 passed；核验重复读取摘要稳定、只列授权元数据、隐藏 JSON/显示字段中的合成敏感值；Ruff 通过。此测试不代表新 schema/按需问答链路已通过。

## 2026-11-09：新存储基础与真实 CLI 隔离验证

- 新增迁移 `160_replace_code_preextraction.sql`：10 张代码专用表、共享内容表扩展、旧表的显式清理前置门禁。现有运行库仍为 159，没有执行删表/数据清理或重新部署。
- 临时 SQLite 升级与独立 PostgreSQL 18 测试库的新建迁移通过；PostgreSQL 中新代码表列注释无缺失。真实 PostgreSQL 锁并发/业务写入尚待验证，不能用本项替代。
- 迁移/事实源目录测试 61 passed：包含 ONES 数据保留、旧数据未清理时拒绝升级及事务回滚、来源复合 FK、当前表列中文注释覆盖。表数量由旧 41 更新为新 31（代码专属减少 10 张）。
- `test_code_analysis_store.py` 5 passed：同版本双读、过期不释放、取消一个保留另一个、写转读、重复申请和目录重叠拒绝（SQLite 单进程合同，非两个真实 Runtime 并发）。
- `test_code_answer_store.py` 9 passed：r100/r101 独立身份、重复保存、同版本纠错 CAS、partial 不索引、未读/错版本/越范围/未验证证据拒绝、每次有效问答独立记录且缓存命中不重复入队。
- `test_code_svn_history.py` 在当前 `knowledge-sync` 镜像启动的临时 Linux 容器中运行，网络禁用，2 passed：中文/空格路径、固定版本日志分页、改后还原的端点差异、单文件差异、blame 行归属和非法范围拒绝。只使用容器临时创建的合成 SVN 仓库，不是 MES 历史，不是三平台验收。
- 新存储类和 SVN 历史类当前属于实现基础，尚未接入正式 MCP、Runtime 授权、UI 或后台索引执行器。Task 2–6 不提前勾选。

### 真实 PostgreSQL 并发补充

当前 API 容器仅复用已有 PostgreSQL 连接环境，在 PostgreSQL 18 创建随机命名的独立数据库，装载当前迁移及本轮 160，以合成用户/Job/答案完成以下检查，结束后删除该测试库。未读取实际业务消息或凭据值到输出。

- 两个线程使用独立数据库会话同时准入同目录 r100 读占用；两者代次相同。
- 第三个 Job 申请 r101 时返回 WORKSPACE_BUSY。
- 两个读者并发保存相同规范问题/条件/证据内容，最终只有 1 条 document_revision 和 1 条 code_index_task。
- code_qa_record 的 PostgreSQL BIGINT[] 保存和读取成功。
- 两个读者完成保存后，r101 写者准入；模拟执行器确认后原子转为新代次读者。

上述是真实数据库事务/并发验证，SVN 完成确认由测试替身提供；并非真实 Runtime A/B 联调、真实 update 并发或模型问答验收。旧 Worker 晚到、CAS 双纠错、移除再收录等其余 Task 5.9 场景仍待补充。

### 当前进度与待确认项

Task 1.1–1.3 已完成（3/39）。其余任务只记录已验证子项，不因存在存储类/CLI 适配器而视为已接入正式系统。

- 新增专项检查 28 passed（盘点、schema、目录协调、答案/问答记录、版本选择、事实源清单）。包含同版本纠错后不回退到仍有旧向量的旧答案；最近更高版本先过滤路径授权、收录状态和索引就绪。
- 当前镜像的真实隔离 SVN 检查扩展为 4 passed，增加原目录 update、dirty 拒绝且不 revert、mixed 拒绝及 sparse 选择保持。源码读取与 SVN 调度尚未接入 Runtime。
- ONES 导入/分块/向量/增量同步检查：127 passed，3 skipped，1 failed。失败为 `test_knowledge_vectors.py::test_single_writer_and_stale_membership_filter`：同线程可重入 SQLite 锁没有抛出预期异常。本轮未改 source_lock；加载 Git HEAD 中完整 storage.py 实现单独重跑，同样失败。保留该未解决项，不宣称整套回归通过。
- 两份实际工单相关 C++ 文件做了只输出元数据的编码检查：不能严格 UTF-8 解码、可按 GB18030 解码。没有输出文件正文。Runtime 原生读取的编码转换、证据行号与 SDK 实际工具响应仍需后续验证。
- 实施发现 SVN 原文结果缺少非持久化返回通道，补充提案见 `svn-result-transport.md`。已请求确认在现有 knowledge-sync 内增加内部有界内存结果端点。依 openspec-apply-change 的设计问题暂停规则，相关 MCP/Worker 接线等待答复。
- 未执行线上数据清理、迁移、镜像更新、提交或模型调用；现有服务仍运行旧版本。

## 2026-11-09：继续实施

用户已确认 svn-result-transport.md 的内部内存结果端点方案。已纳入 design、SVN 合同、platform-operations delta 及 Task 2.1/5.4；解除该设计等待，继续接线。

### 内部结果通道、管理接线与页面进度

- API 本地签发固定 code-knowledge-control-plane Service Principal，knowledge-sync 仅挂公钥验签；不增加 Bootstrap 凭据、宿主端口或面向 Agent 的 MCP 服务。单响应 512 KiB、总内存 8 MiB、最长 60 秒且受操作截止限制；缓冲过期不落盘。
- 内部端点/客户端/持久操作和执行器测试涵盖错误角色/代次、浏览器拒绝、授权再核对、到期、超限、禁止重定向、响应摘要校验、结果丢失重取和重取变更拒绝。原文没有进入 operation.result_json。当前 MCP 桥/Runtime 原生读取仍未完成，不能视为已端到端。
- knowledge-sync 主循环改为新的源码操作 Worker，管理浏览/检出与分析 SVN 操作共用 code_svn_operation；旧预提取 Worker 不再启动。Compose 草稿增加内部公钥挂载及 Runtime A/B 同一 checkout 的只读挂载；没有更新运行容器。
- 补齐初次配置状态：未完成管理浏览允许 source_id 为空，真实 info 后才能补齐；初次 checkout 预留目录时 physical_key 可空，ready 强制非空。不提前伪造已核实的仓库或 inode。迁移草稿同步更新，线上仍未执行。
- 空代码 KB 创建/绑定/受管独立 collection 初始化/验证/发布基础测试通过，使用模拟 Embedding/Qdrant；不能替代真实索引服务验收。新增资源与结果/操作相关测试 17 passed。
- 前端移除旧快照/预提取/更新计划全局面板，增加 ONES/代码类型、代码库源码配置与受管存储/索引入口；保留文件和文件夹多选及对齐。生产构建通过，既有资源/检出交互测试 33 passed；新增代码配置专项测试另行运行。
- ONES 资源测试另有同类 SQLite 重入锁失败：test_draft_mutation_obeys_same_source_lock_as_import_and_retention；该组 43 passed、1 failed。尚待以 HEAD 存储实现单独复核，不冒称全回归通过。
- Task 2.6（CLI 选型）和 5.5（隔离 SVN 合同）完成，当前 5/39。4.1/4.5 等已有实现子项，但真实 UI/API/权限、索引执行、Runtime 和部署仍未验证，不提前勾选。

## 2026-11-09 18:48 本地实现继续（7/39）

已完成页面类型分流、旧预提取入口移除、SVN 检出移入代码配置，以及空代码 KB 的显式增量索引初始化/验证/发布合同（4.1、4.5）。新集合身份固定本 KB/source/profile，拒绝已存在索引改到其他 collection 或恢复 RETIRED 索引。

增量执行器复用 ChunkRepository、IncrementalVectorWriter 和现有 Embedding/Qdrant 客户端；加入 full conditions/context、固定版本 payload、确定点重试、暂停/进度/重试管理入口。只重试已确认返回的同步调用；running 租约过期仍不接管，旧执行器实际停止后的恢复接线尚未完成，3.8 不勾选。

- 后端新索引/答案/资源与共享分块检查：50 passed, 1 skipped。随后资源负面合同、迁移及 schema facts：72 passed。
- 新版本检索与增量索引/答案合同：19 passed，验证 exact、授权后的最近更高版本提示、缺 SVN 拒绝、空库依赖故障不可当未命中。该检索函数尚未接通 MCP 主入口。
- 前端生产构建通过；配置/检出/资源页面 36 tests passed。未验证真实浏览器或部署 API。
- 隔离 Linux 容器合成 SVN 仓库：9 个真实 CLI 测试通过，新增仓库根绑定与中文空格目录测试；不代表 MES 真实提交历史或三平台宿主验收。
- 再次在现有 PG 服务中创建独立临时数据库，迁移 160、双并发读、写者阻塞、相同身份并发保存合并、QA 数组与原子写转读通过，测试数据库已删除。现有业务库仍为旧版本，未执行退役删除或部署。

仍需接通原 Job 的搜索凭据、SVN MCP、Runtime 原生只读路径守卫/读取证据、收尾问答记录与停止恢复，再进行实际切换。没有启动模型提取或真实 MES 问答。

## 2026-11-09：原 Job 接线、恢复与完整性检查

以下证据更新前述“尚未接通”的阶段性记录；现有运行库仍未切换，不能把本节当作部署验收。

- 已接通 Knowledge MCP 的版本化答案搜索/读取、SVN update/info/log/diff/blame、操作查询、答案保存。前置成功搜索凭据绑定原 Job、invocation、用户版本、配置与当前权限；工具 Manifest、mutating intent、发布校验和 Skill 同步，旧 frozen Job 不获取新工具。
- Runtime 能力在启动时冻结，目录占用后只收窄授权。只读挂载目录的 Read/Glob/Grep 通过前置和后置 hook 验证，读取证据来自实际跟踪文件/行号/哈希/编码；拒绝 .svn、未跟踪、链接、Bash/Write/Edit。原问答 Skill 负责按条件判断缓存和追踪跨模块规则，未调用真实 MES 模型验收。
- 安装环境 SDK 0.2.178、CLI 2.1.318 的真实初始化烟测通过，未发送模型 prompt；此前隔离本机合成 Provider 的真实 CLI Read/Glob/Grep 与失败阻断烟测已保存为 `backend/tests/support/claude_sdk_native_smoke.py`。合成 Provider 不证明真实模型质量。
- 标准 AgentResultService 收尾增加私有 QA 记录。仅记录实际全文读取/成功保存且最终引用的答案版本；不把检索候选算作引用，更高版本不改标目标版本。7 项专用测试覆盖缓存命中、幂等、不重复派生、未引用/失败记录排除、比较版本、缺版本和结果事务失败回滚。
- 移除旧预提取 Worker/来源快照/状态机投影模块及旧合同测试；本地无数据库完整检出 CLI 因 scripts/local_svn.py 仍调用而保留。旧 extract-business-knowledge Skill 退出运行目录，使用 code-business-query。未删除源码目录、业务数据库数据或 Job 审计。
- Compose 修改为 knowledge-sync 可写、两个 Runtime 只读的共同检出根；控制器从真实 daemon 挂载解析 checkout/state 路径。37 项 Compose/Windows 路径静态测试通过；`docker compose config --quiet` 当前环境通过。尚未在 Windows/Linux 宿主启动验证。
- 代码 KB 配置、分块/增量暂停/重试、索引状态和 ONES 类型隔离页面：38 项组件测试通过，前端生产构建通过（保留既有大 chunk 提示）；没有冒称真实浏览器验收。
- SVN 子进程继承本地 OS 文件锁；恢复需要锁释放及 owner/claim 相符，不能仅因租约超时回收。索引执行器也使用实际停止证明；远端迟到请求通过代次化点 ID、PG ready 代次召回过滤、带上限 remove 隔离。11 项索引/搜索专项测试包含响应丢失复用、迟到 upsert/delete、移除再收录、暂停和 Worker 恢复。迟到旧代次点可能暂时残留但不参与检索。
- 16 项真实 Linux 容器 SVN CLI 测试通过：包含 GB18030 正文与中文 UTF-8 diff 头、EOL/keywords、复制/删除重建、时间筛选、稀疏检出、混合/dirty 拒绝和真实 pristine 证据。新加检出前容量预估与执行中剩余空间门禁后再次通过；不是 MES 的实际 SVN 历史。
- 新增维护 CLI：摘要绑定旧候选退休、现有 checkout 只读登记。退休需明确维护声明，拒绝摘要变化、未知停止、混合来源和未规划的旧向量集合；保留目录和 Job/audit。4 项迁移/退休 SQLite 测试、8 项管理检出/登记/磁盘容量测试通过。实际退休尚未执行，原盘点摘要因字段增加已失效，切换时必须重新生成。
- 本轮综合按需后端测试 86 passed；MCP/身份桥/源码操作检查 182 passed。全量 MyPy（backend/app、services，726 个文件）通过，变更 Python 文件 Ruff 通过。之后新增测试/改动仍按对应套件再验证。
- 第二个独立、临时 PostgreSQL 18 容器：22 项真实读库角色和新代码答案读取检查通过，验证先前修复的 UUID JSON 转换及新增 claim_version 最小列权限。3 项持久化 PG 集成测试通过：双读与到期拒绝回收、逐个释放、原子写转读；同身份并发保存合并与双纠错 CAS；清单变动回滚、旧代码退休/迁移并保留其他来源。
- 真实 PG 并发测试发现并修复 release_stopped 中 CASE 时间类型推断错误；同步修复操作失败/取消的同类表达式。该发现证明 SQLite 通过不足以替代 PG。PG 测试使用合成 Job、答案和 SVN 完成事件，不是两个实际 Runtime 的模型执行。

维护步骤见 `docs/operations/code-knowledge-on-demand.md`。尚未执行真实库清理、160 迁移、容器更新、Agent/Application 发布或 MES 模型问答；跨平台运行、真实重排负载和最终切换仍留作未完成验收。

### 22:28 回归、镜像和会话落盘检查

- 综合后端检查 1491 passed、62 skipped、12 failed。逐项修复架构依赖、历史迁移 fixture 默认字段、Service Identity 测试替身位置、MCP 截止说明、Runtime 镜像 COPY 清单和同来源锁重入。修复后定向回归 275 passed/2 skipped、历史迁移 56 passed/2 skipped，架构 68 passed；没有把初次综合结果改写成全绿。
- 增加代码会话禁用 SDK session persistence/prompt history 和初始化审计字段。SDK 0.2.178/CLI 2.1.318 真实 Read/阻断烟测通过，独立配置目录没有转录或合成原文；78 项 Runtime/内部 hook/HTTP 测试通过。使用合成 Provider，没有调用真实 MES 问答模型。
- 真实 PostgreSQL 测试扩为 7 passed，覆盖操作失败和排队过期的 timestamp 类型处理；对应测试容器已删除。
- API、两个 Runtime、knowledge-sync/mcp、迁移器、前端及调度/执行 Worker 新镜像构建成功；隔离 Runtime 镜像导入成功，报告 prompt v13、SDK 0.2.178。补齐 Docker build context 的 maintenance 目录白名单。运行容器此时尚未切换。
- 新只读退休盘点摘要为 `478dc6ed7050dedc810a52b241b44281e2ca1182d4e228e75b7d7b770f1a6862`，仍为 schema 159、79 条代码文档、15,778 条其他来源文档、无代码向量索引、无混合来源引用。查询时没有非终态 Job。维护执行前仍重新核对，不凭此提前删除。

### 22:40 本机切换与真实管理链路

- 确认无非终态 Job、旧代码 invocation 均有 quiesced 标记后，停止旧 API/Worker/Runtime/知识服务。以维护期同摘要清单执行退休，实际删除 79 条旧代码文档，保留 15,778 条其他来源文档和 24 条旧 checkout 元数据清单。未删除源码目录或 Job/audit。
- 真实业务数据库 Migrator 成功应用 160；既有管理员、凭据保留，Runtime grants 更新并验证。按当前源码构建并应用新 API、Worker、知识 MCP/sync、前端与两个 Runtime，服务恢复运行。
- Runtime A/B 实际报告 SDK 0.2.178、prompt v13，code_analysis.py SHA256 相同；Docker Inspect 确认同一宿主 checkout 根在两个 Runtime 为 RW=false，在 knowledge-sync 为 RW=true。此项不代替实际双模型并发验收。
- 真实 Chrome 页面验证 ONES/代码类型分流、旧预提取全局入口消失；从页面创建空库 `mes-code-answers`（MES 代码知识库）。现有 `mes` 只有 set_web 且含 .DS_Store，保留原样，不强行登记。
- 真实目录预览发现 1417 个目录/7541 个文件的路径元数据约 558 KB，超过原文 512 KiB 限制。修复为管理预览单独 2 MiB、严格字段验证，总缓冲 8 MiB/60 秒不变；原文仍 512 KiB。18 项传输/管理回归通过。新 API/sync 镜像应用后，真实预览已成功，页面勾选 set_server、set_web/EBR、set_web/JTH，发起固定 r2 检出到 mes-business。

### 23:00 检出、索引初始化及 assist03 发布

- `mes-business` 已完成 SVN r2 检出并通过管理页面绑定，包含 set_server、set_web/EBR、set_web/JTH。旧 `mes` 及其他检出保持原样；不自动清理未跟踪文件或补齐旧目录。
- 真实初始化暴露共用 Qdrant 客户端仍只接受 ONES 的 collection 前缀。修复为按代码 chunk profile 选择 UUID 派生的 `code_answers_` 前缀，ONES 仍使用原前缀，拒绝任意集合名。47 项相关资源/向量回归通过、1 项跳过；其中代码测试使用真实隔离 PG/Qdrant，Embedding/重排合成。
- 新资源 `mes-code-answers` 已在真实页面初始化、验证和发布 v3。独立索引 `19840138-4f3f-536a-b2fc-55d1fdf4bc87`，集合 `code_answers_198401384f3f536ab2fc55d1fdf4bc87`。此时没有模型答案、QA 记录或分析占用，不能算问答入库验收。
- 用户选择 assist03 后，发布 Agent revision 51（新增 code-business-query 与 8 个代码工具，保留原 Skill/模型/文件能力），发布并激活 Application revision 67，publication 为 `business_app_publication_6c4707cfd77942a8987d1004ebf67d6a`。知识工具共 10 个，含原目录/搜索；纯 ONES 请求不要求 SVN。原触发器、交付和执行策略保留。
- 修复源码 hook 对同一任务附件工具的误拦截：source 路径走 grant/只读/实际证据检查；非源码路径继续受 JobSandbox 约束。代码单独任务没有 Write/Edit；混合文件任务可使用原授权的文件操作，但不能写 source。API 与两个 Runtime 最新镜像已应用。
- 最终 Runtime/JobSandbox/源码 hook/Compose 定向测试 **158 passed**；Ruff、MyPy（726 个文件）、OpenSpec strict 和 git diff --check 通过。Runtime A/B 的 5 个相关模块 SHA256 一致，SDK 0.2.178、CLI 2.1.318、prompt v13；实际 checkout 挂载 A/B 均 RW=false、knowledge-sync 为 RW=true。
- 实际库仍有 15,778 条非代码文档，旧 MES代码知识构建应用已 disabled。新代码 KB 尚未授予业务角色；已向用户呈现将其和 8 个工具授予现有 e2e 角色（4 名成员）的具体范围，等待二次确认。未启动模型提取或真实 MES 问答，不向外部渠道发送测试消息。
- Task 4.3/4.4/5.6 完成，当前 30/39。5.6 是本地迁移/合同/前端/构建与 ONES 回归证据，真实双 Runtime 并发、模型质量、真实重排负载及 Windows/Linux 宿主仍分别未完成。

### 23:10 授权与隔离 PG 补验

- 用户二次确认后，通过现有授权服务将新 KB 和 8 个代码工具授予 e2e，business revision 16；成员和既有数据范围不变，两个 ONES KB 保留。未更改其他角色。
- 隔离 PostgreSQL 18 + Qdrant 1.19.1 容器补验：13 项通过，新增 schema 注释检查因测试 SQL 百分号转义失败；改用参数后该项通过。合计 14 个场景已通过，涵盖全部新表/列注释、跨来源 FK/ready CHECK、同版本双读、停止证明/CAS、最近更高版本权限过滤、旧 Worker 停止恢复、迟到 upsert/remove 代次隔离和真实 Qdrant 响应丢失复用。答案/Embedding/重排及 SVN 完成事件仍是合成输入，不代表真实 MES 模型质量。临时容器和数据已删除。Task 5.9 完成，31/39。
- 实际调试候选为空暴露既有 bug：入口错误地将 local 部署环境用于过滤用户已授权的业务环境。依据 canonical business-application 领域边界和 execution-delivery 调试 Requirement，移除这层错误过滤，继续只使用当前授权候选，并在创建时复核。新回归验证 local 部署下授权 factory-test 可调试、撤权后消失、默认不外发；35 项调试授权/查询测试通过。没有新增数据范围授权。

### 真实问答启动与合同问题

- 为本机初始化缺失的内置 debug_api 入口（仅入口、无地址/凭据/交付能力），使用现有 Job 创建服务及当前 admin/e2e 权限，Delivery 固定 none；记录管理审计。没有借用外部渠道发送验收消息。
- 首次 Job `job_a3b73054b3084e818dcdaca802094894` 在模型启动前因 `knowledge_storage_unavailable` 失败。修复 CodeSourceGrant 使用同一受管 ContentAccess/ResourceReader；新测试覆盖真实显式 storage_config 的资源发布后能力解析，27 项资源/桥/源码守卫检查通过。
- 后续 Job `job_d870da1501c74a939e73eb36cce0e71b` 在模型启动前失败，原因是启动命令未加载代码问答 Compose overlay，Runtime 缺少专用身份。使用已有 `/Users/mhz/.config/enterprise-agent/code-runtime-bootstrap-token`，只登记宿主文件路径，显式加载 overlay 应用 API/两个 Runtime；核对文件存在/可读，不输出凭据。运维说明补充该组合，不能用基础 Compose 更新三个服务后宣称代码能力仍已接线。
- 第三个 Job `job_975c8570673644218af5ca7b7f863c91` 已实际调用模型、完成空代码 KB exact/higher 检索、取得 r2 共享读授权，并由原 Runtime 原 Job 读取前后端源码；宿主记录实际证据。正在等待结果和缓存验收。
- 实际调用暴露操作查询合同不一致：工具输入只有 operation_id，桥却要求 analysis_id。修复为从操作记录解析分析，并先验证原 Job 归属；16 项桥测试通过，包含使用公开输入 schema 的查询及跨 Job 拒绝。镜像已构建，当前读取任务结束后再应用，避免中途重启影响授权心跳。

- 跨模块 Job 在 300 秒预算后停止，最终 `runtime_invocation_outcome_unknown`，未形成最终答案或缓存；不能标为业务核验成功。已观察 invocation 实际 quiesced，分析 cancelled 且读占用已释放。该运行共记录 44 段源码证据，覆盖工单前后端、处方与物料模块。
- 在确认原读取停止后应用操作查询修复，创建两个更窄的内部问题：EBR 批量发布前端的处方一致性校验（`job_4bbc5098b7a643d191d6450fe79b96a4`）和处方 PublishFor 的物料校验（`job_8c0544f5144b4917a4151d3c029afa58`）。实际分配到 Runtime B/A，均 Delivery none；结果待验，未提前标记完成。

- 23:21 实际数据库同时观察 Runtime B/A 对同一 checkout `0c149573-1034-5031-99c4-9136ce8710fd` 的两个 reading，占用版本均 r2、generation 1、均未释放；不是合成并发。两次 knowledge_get_source_operation 已 SUCCEEDED。其余修改互斥/撤销/异常场景仍以对应单元和隔离 PG 证据区分。

### 23:35 真实答案、索引与同版本复用

- 两个窄范围问题均正常结束。EBR 前端规则保存为 supported，读占用于 23:22:09 释放；PublishFor 的内部依赖未核实，保存为 partial、不进入共享索引，于 23:22:37 释放。两个读者独立释放，不会清除其他任务的占用。任务 5.2 的真实证据为双 Runtime 读共享；修改互斥、停止证明、别名和重复调用仍以对应单元及真实隔离 PG 测试证明，不声称所有故障都已在模型运行中触发。
- 真实收尾发现旧 Runtime 仍把业务答案替换为“代码提取已结束”，导致 QA 没有业务内容与引用。删除该旧预提取替换分支；源码/工具原文的审计省略继续保留。新增真实消费循环的合成 SDK 回归，证明业务答案保留、原文不进入工具记录或 SDK 审计。
- 索引后台查询把 PostgreSQL boolean 与整数 0 比较，任务一直 queued。改用 false；新增运行实际后台循环的 SQLite/隔离 PG 回归。140 项 Runtime/索引/QA 回归通过；独立 PG 后台测试 1 passed（初次测试收尾的连接清理问题修复后重跑通过）。全量 MyPy 726 文件、相关 Ruff、diff check 通过。
- 确认没有运行中 Job/读者/SVN 操作后，于 23:29 应用两个 Runtime 和 knowledge-sync 新镜像。真实任务 `9bbd1c0d-43c0-5d42-a53f-57e867a8177b` 完成 1/1 分块及实际 Embedding，23:29:38 ready，独立 Qdrant 集合已可检索。不是合成 Embedding 测试。
- 同版本复用 Job `job_2a2f7b38924b4b32971e13a26b907b3b` SUCCEEDED，仅目录/搜索/答案详情三次知识调用，没有 code_analysis/源码读取/新索引任务。收尾实际写入 supported/cache 私有 QA，requested r2、引用 r2，保留正常业务回答与实际 document/revision。旧占位答案审计保留，不伪造回填。
- 处方提交审核 Job `job_408bcbcb3d414c6ca577a0ecc796f5e2` SUCCEEDED，实际读取 `_CheckFormatRelMatVerify` 与调用分支，独立人工复核源码：组成物料编码为空时按名称查未验证记录，存在即 isOk=false，提交审核返回 ERROR_FOR_MAT_STATE_ERROR；查询失败返回 ERROR_DBOPERATE。因模型把界面文案/完整审核结果写成缺少 critical 字段的未知项，现有门禁保守地保存 partial，未索引。补充 Skill 的 critical 字段及局部结论范围说明，不降低校验门槛。
- 所有这些验收任务为内部 Debug Job、Delivery none，没有查询生产业务数据库或发外部消息。临时 PG 测试容器已删除；现有源码目录、ONES 和运行审计保留。

- 工单后端 Job `job_7cf29ef160704de8a8c16eb1753d7062` SUCCEEDED，读取 `_CheckRelatedStatus` 的正式工单分支。独立复核确认：formulaId 非零时先查有效期；开关关闭要求 S_PUBLISHED，开启只放宽为非 S_ABANDONED；过期仍拒绝，主配方的放宽代码处于 #if 0，不生效。该任务按 partial 记录，不冒称整个发布流程都已核验。结合前端工单与后端处方/物料的独立阅读，完成任务 6.3 的限定范围业务核验；广泛的生产故障诊断仍受预算和现场证据限制。
- 更新受管 Skill 的保存字段说明后，发布 Agent revision 52、assist03 Application revision 68（`business_app_publication_9905e4447413474f8651ba5dfc15be6d`），local deployment revision 42。原模型/工具/触发器/交付/预算均沿用；只有 versioned Skill 内容变化，Runtime 通过冻结发布接收相同文本。e2e 仍为 business revision 16、4 名成员、3 个 KB（原 2 个 ONES + 代码 KB）。

### 23:44 局部规则准入与规范同步

- 新 Skill 的实际 Job `job_40b59540d9a849b18310c8eaaa094e9d` SUCCEEDED，处方物料规则保存 supported，23:40:17 释放读取占用，PG 修订 `feca337f-89b8-58f9-8997-5de0214a4d67`；实际 1/1 分块完成，Embedding/Qdrant 就绪。每条范围外未知显式 critical=false，真正关键未知的存储拒绝逻辑没有修改。QA 为 supported/code_analysis，包含正常业务回答与实际引用。
- 对工单前端旧答案的独立复核发现提示优先级需要明确工单类型判断在先。首次模型纠错没有先将 exact 问题切回原文档身份，被 CODE_QUESTION_MISMATCH/CODE_ANALYSIS_ALREADY_ACTIVE 拒绝；它另存了不同问题的规则，这不算原文档纠错成功。后续限定原问题身份的纠错另行验证，不能用新文档冒称 CAS 已成功。
- 按实际实现将本变更 delta 合并进 builtin-tool-resource、execution-delivery、identity-access、platform-operations 四份 canonical，其他领域未改。保留原场景，新增 31 个 Requirement、修改 4 个；移除规范正文对活动 change 的 postgresql-schema.md 的依赖，用本规范中的实体边界表达。10 份 canonical 严格校验通过，主规格表达合同，不代表以下验收已完成。
- 未完成：Windows 与 Linux 宿主实机验证；真实 MES 的相邻 SVN 规则变化及高版本线索回到旧版核验；页面完整跨版本闭环；与 ONES 同时请求重排的质量/队列/负载测试。当前本地 SVN r2 是导入基线，不包含原公司 SVN 历史，不能把隔离测试中的 r100/r101 当作实际 MES 证据。保持 change active，不归档。

### 23:46 纠错结果及最终收尾

- 原问题身份的纠错 Job `job_d381f864a4c6469390140510ab2f928d` SUCCEEDED，实际读取前端函数，knowledge_save_code_answer 一次成功。原 document `cd1fb5e3-2bd0-5820-ba18-a062aeea0950` 保持不变，从旧修订 `e10d6336-059e-55d7-b853-4600ad2d1413` 切换到 `282974b3-28de-5e06-9d28-055e18b97359`；旧修订 remove、新修订 upsert 都 succeeded，新修订 23:44:26 ready。独立阅读与新结论一致：类型不同先提示类型，只有类型一致才检查编码，再检查版本。QA 为 supported/code_analysis，引用新修订。
- 首次纠错 Job `job_114a702cf9fb4cc7b11bf4265f8f1b05` 最终 FAILED/runtime_invocation_outcome_unknown，其已提交的新问题文档和未完成纠错分析分别保留，未把该运行标为成功。未完成分析确认停止后 cancelled、释放占用。真实结果说明原问题身份必须在准入前确定，不能在持有分析占用后换题；运维说明补充该纠错步骤。
- 最终检查：没有未释放 code_analysis、queued/running SVN 操作或非终态验收 Job；相关服务运行，API/两个 Runtime/knowledge-sync/MCP 健康；临时 PG 容器不存在。所有代码索引任务 succeeded。没有提交或推送 Git。
- 当前任务 35/39；6.1、6.4、6.5、6.6 保留未勾选。canonical 与 active change 严格校验、diff check 通过。
