# 2026-11-18 重建后未完成验收与未勾选任务
本文件保留关闭时的未勾选任务原文。关闭不等于完成；不得补勾。
共 16 个变更、51 条未勾选项。

## add-mcp-inspector-smoke-tests
- 领域：platform-operations, builtin-tool-resource
- 归档后路径：`../2026-11-18-add-mcp-inspector-smoke-tests/tasks.md`
- [ ] 6.1 取得 Linux CI 上 Inspector job 及受影响原门禁的真实运行结果，核对失败时镜像门禁不会放行；没有实际 CI 运行证据时保持本项未完成，不能用工作流文件存在或本地通过代替。

## add-versioned-code-business-knowledge
- 领域：platform-operations, builtin-tool-resource, task-file-workspace
- 归档后路径：`../2026-11-18-add-versioned-code-business-knowledge/tasks.md`
- [ ] 8.2 验证工单→处方/主配方→物料依赖及配置分支、前后端限制、受理与完成差异；覆盖集团应用启停/授权，使用独立核验预期而非提取模型自评。
- [ ] 8.7 对获准的当前本地源码执行实际基线提取与问答抽查，记录模型配置、来源清单、覆盖、疑点、耗时及资源用量；真实模型不可用时该项保持未完成。
- [ ] 9.1 在实际内网核验 SVN 地址、同仓库/同分支组件路径、认证引用、external 和当前本地包映射；无法映射时建立明确 SVN 起点并保留本地身份。
- [ ] 9.2 使用获准真实模型和发布的提取配置完成工厂端/集团端首期知识构建，由业务人员或独立源码核验确认关键问答，记录未覆盖范围，不把模拟 Provider 结果计入真实验收。
- [ ] 9.3 验证一次真实新增提交到知识更新的完整链路、共享依赖传播、历史版本按需构建及精确规则差异；固定样本需有真实变更证据。
- [ ] 9.4 验证部署环境每日调度、停启恢复、故障重试、当前权限和查询版本隔离；记录实际耗时/成本及历史冷查询等待，不能用本地测试代替目标环境容量结论。
- [ ] 9.5 汇总实现、检查和验收证据，逐项保留真实环境欠账；仅在全部所需任务完成后进入同步/归档流程，未完成项不得补勾。
- [ ] 10.9 验证实际查询和版本隔离，汇总实现/部署/业务核验结果；不把未知 SVN 基线冒充真实历史提交，仍缺条件的原验收项保持未完成。

## auto-decode-compressed-database-fields
- 领域：builtin-tool-resource, task-file-workspace
- 归档后路径：`../2026-11-18-auto-decode-compressed-database-fields/tasks.md`
- [ ] 5.1 确认三种测试数据库资源、只读账号和独立获准的合成记录准备流程；核对实际业务写入/读取代码的包装与文本编码规则，只记录安全格式事实，不读取/打印/保存凭据或真实字段正文。
- [ ] 5.2 在真实 MySQL MEDIUMBLOB 中用合成 C_OPTEXT 记录验证原始及 ASCII 包装、普通二进制、中文解码、容量和流式清理，经 tool-mcp 与新 Job 结果文件链路记录安全验收证据。
- [ ] 5.3 在真实 SQL Server VARCHAR(MAX) Chinese_PRC_CS_AS 中用合成记录验证标准 Base64/Hex、字符串保真、中文明文及超限；单独确认现场存储是否属于支持集合，不按 COLLATE 猜编码。
- [ ] 5.4 在规范要求的真实 Oracle 11.2.0.4/Instant Client 19c Thick 中用合成 BLOB 记录验证原始及 ASCII 包装、分块读取、连接生命周期、大小/超时和文件链路。
- [ ] 5.5 汇总三个引擎的实际版本、客户端、Job/调用关联、安全状态、大小/计数和文件校验事实；缺少环境或格式规则时保留对应任务未完成，不用 Mock、客户端健康或 DDL 冒充真实验收。
- [ ] 6.2 在用户请求同步/归档时按对应工作流处理，保留未完成真实验收任务与欠账；归档不补勾，镜像回滚不修改历史 Job、Publication、Resource Revision 或独立审计。

## enable-governed-knowledge-retrieval
- 领域：builtin-tool-resource, execution-delivery, governed-api-capability
- 归档后路径：`../2026-11-18-enable-governed-knowledge-retrieval/tasks.md`
- [ ] 11.2 验收本地/内网 Embedding 与 Agent 既有聊天模型的真实知识新 Job 链路；聊天模型可为外部服务，不再要求内网部署认可或全文不外发证明。缺真实调用证据则仍未完成。
- [ ] 11.3 用户批准正式部署后，核对非终态工作及镜像/schema 兼容，执行正式 Migrator 和可选服务部署并验证 readiness；显式配置知识资源、角色与新的 Agent/Application Publication，不改旧 Job 权限。
- [ ] 11.4 使用两位真实 ONES 可读范围不同的测试用户创建新 Job，验收 KB/ONES 双权限、引用回源、工作项权限撤销、KB 撤权、服务重启和既有模型版本/会话访问边界；记录是否真实调用 Provider 和每项结果。
- [ ] 11.5 由人工完成并复核首批约 50 条真实问法和相关文档标签，存入受限目录；运行离线 dense 与双权限端到端评测，输出脱敏 Recall@10、MRR@10、无答案误报、p50/p95 和失败分类。
- [ ] 11.6 根据实测基线由用户确认质量/时延准入目标并完成复测，保留未达标项；更新 evidence 与运行手册，只有取得相应真实证据才勾选验收，不自动提交、推送或归档。

## fix-code-answer-save-finalization
- 领域：execution-delivery, platform-operations
- 归档后路径：`../2026-11-18-fix-code-answer-save-finalization/tasks.md`
- [ ] 3.1 部署 API/agent-worker、knowledge-mcp 和两个 Runtime，使用新 Job 在对应环境/版本重跑两问，核对答案与索引结果

## ground-code-answers-in-ui-workflows
- 领域：builtin-tool-resource, execution-delivery
- 归档后路径：`../2026-11-18-ground-code-answers-in-ui-workflows/tasks.md`
- [ ] 3.1 协调部署、重新发布 Skill/应用，以新 Job 验证配置操作、旧知识缺口补查与前端不可读三种情形；核对实际读取证据和保存支持状态。

## harden-schema-pagination-cursors
- 领域：builtin-tool-resource
- 归档后路径：`../2026-11-18-harden-schema-pagination-cursors/tasks.md`
- [ ] 3.1 Windows 环境部署一致新版本、完成迁移，以新 Job 连续读取至少四页并核对完整性。

## implement-incremental-knowledge-sync
- 领域：platform-operations
- 归档后路径：`../2026-11-18-implement-incremental-knowledge-sync/tasks.md`
- [ ] 4.3 目标 ONES、真实模型和部署环境验收（本地合成验证不得替代）。

## improve-knowledge-retrieval-ranking
- 领域：builtin-tool-resource
- 归档后路径：`../2026-11-18-improve-knowledge-retrieval-ranking/tasks.md`
- [ ] 7.1 由有权人员准备经脱敏、人工复核的调参和冻结验收集，按问题/事项分组隔离；建议首批至少 50 条独立问法，包含复合症状、近似干扰、长文本、跨项目及无答案，不复制生产历史原始会话到仓库。
- [ ] 7.2 在真实模型与固定候选上完成新旧对照，验证冻结集 MRR@10 提高、Recall@20 不下降；由用户现场原始问法验证目标工作项 #250449 进入前 3，保留未达标和候选未召回的事实，不硬编码目标 ID。
- [ ] 7.3 在目标环境测试前冻结 CPU/内存、并发和业务 p95 门槛；测单请求与四请求并发的排队/推理/总检索时延、内存、超时和拒绝，确认既有硬预算及新依赖资源开销可接受。
- [ ] 8.1 在明确的目标部署范围按既有发布流程协调新服务和工具合同，用新 Publication/Job 验证真实 ONES 可读性、最新详情、撤权/不可读过滤及索引资源身份保持；仅完成代码不得勾选。
- [ ] 8.2 用已知漏排、低分尾部、同义问法、无答案和仅同族机制场景验证真实 Agent 的查询、去重、核实停止与回答边界，记录详情调用次数和端到端时延，不以检索排序指标替代。

## optimize-code-search-and-business-tracing
- 领域：builtin-tool-resource, execution-delivery
- 归档后路径：`../2026-11-18-optimize-code-search-and-business-tracing/tasks.md`
- [ ] 2.5 另一部署环境 test2/r52422 复测原拆批问题（当前无法访问，保留现场待验收）。

## optimize-ones-knowledge-backfill
- 领域：platform-operations
- 归档后路径：`../2026-11-18-optimize-ones-knowledge-backfill/tasks.md`
- [ ] 4.2 目标环境执行计划、同规模耗时对比及真实 ONES 日期补采验收（需后续环境授权，本次保持未完成）。

## replace-code-preextraction-with-on-demand-knowledge
- 领域：platform-operations, builtin-tool-resource, execution-delivery
- 归档后路径：`../2026-11-18-replace-code-preextraction-with-on-demand-knowledge/tasks.md`
- [ ] 6.1 在 Windows（PowerShell/WSL2 启动）、macOS、Linux 分别验证实际 CLI、中文/空格路径、两个 Runtime 只读挂载、同版本并发读、修改互斥和异常恢复，注明 amd64/arm64 与未验证环境。
- [ ] 6.4 验证真实 PG 保存、Qdrant 就绪、再次同版本提问复用且不占源码目录；工作副本更新后旧版答案仍可检索，新版不会复用旧规则，未知依赖不升级为确定答案。
- [ ] 6.5 从页面创建空代码 KB，绑定现有 PG/Qdrant/检出目录，验证一次新问题回答入 PG→分块→Embedding→独立集合就绪；再验证重复问答只新增回答记录，以及更高版本线索必须核验请求版本后才能缓存。
- [ ] 6.6 用真实代码答案验证共用重排的检索质量，并与 ONES 同时请求验证队列/截止和负载；只记录实际通过环境，不把接口可复用等同于完整链路验收。

## sync-ones-knowledge-work-items
- 领域：platform-operations
- 归档后路径：`../2026-11-18-sync-ones-knowledge-work-items/tasks.md`
- [ ] 8.2 在隔离 PostgreSQL 验证迁移、source 排他、候选不可见和多 KB 原子激活，SQLite 行为保持等价；不把 SQLite 通过当正式数据库验证。
- [ ] 8.3 用隔离 Qdrant 和合成 Provider 验证首次构建、向量复用、失败保留旧版、无变化零编码、断点续跑和空库；故障注入仅作用于测试归属资源。
- [ ] 8.4 验证目录/检索的同应用角色 KB 范围与本人 ONES 权限，覆盖采集账号广权限不传递、不同应用隔离、停用和并发换版；明确使用合成 Provider。
- [ ] 9.1 执行前重新核对输入摘要、目标 schema head、非终态 Job、容量/索引保留空间及缺陷发布基线；必要服务重启和兼容接续按明确维护授权执行，采集仍停用。
- [ ] 9.2 在批准范围内运行 Migrator 和旧知识发布的 KB 范围兼容接续，验证缺陷旧数据与索引可用；发生冲突停止后续正式导入。
- [ ] 9.3 正式候选导入预检通过的全部工单和 Story，记录安全入库/版本/关联统计及缺描述数量；重放验证不新增重复项，不能用部分成功冒充全部完成。
- [ ] 9.4 完成两类正式清洗分块，核对逐文档覆盖、稀疏块标记、块边界和摘要；保留既有缺陷 profile/向量不变的证据。
- [ ] 9.5 在本地/内网 BGE-M3 做有界吞吐基准并报告估算，执行可恢复全量向量构建与逐点完整校验；后台进度仅输出安全统计，不使用外部模型。
- [ ] 9.6 激活两类完整内容与 READY 索引，报告实际文档/块/点数、版本、失败项和关联解析；确认默认同步停用、角色/应用授权未改。
- [ ] 9.7 在明确批准的新资源发布和现有授权范围内验收 Knowledge MCP 集成；本机使用合成 ONES 时注明证据边界，未批准发布或真实权限验收保持未完成。
- [ ] 10.1 在能够访问真实 ONES 的目标环境配置受管只读身份与明确来源/范围，验证 TLS、分页、来源版本单位、新增和已有项修改；不从本机脚本提取认证值。
- [ ] 10.2 显式单次采集验证三类更新、重放、失败不换版、自动切版和实际用户权限，并人工评估标题-only Story 与正文记录的检索效果；真实证据未取得不得勾选。
- [ ] 10.3 获得该环境启用授权后开启每小时调度，观察至少一个实际周期、长运行恢复及关闭行为；当前本机按用户要求保持停用。

## unify-main-compose-knowledge
- 领域：platform-operations
- 归档后路径：`../2026-11-18-unify-main-compose-knowledge/tasks.md`
- [ ] 3.3 完成实际检索成功验收：真实调用已执行但未通过，存在 ONES 目标不可达及约 60 秒预算失败；用户明确将本次范围限定为统一部署，保留后续处理，详见 evidence.md。

## use-docker-volume-for-svn-checkout
- 领域：platform-operations
- 归档后路径：`../2026-11-18-use-docker-volume-for-svn-checkout/tasks.md`
- [ ] 2.3 Windows 目标环境更新后完成真实仓库长检出和问答读取验收（待现场执行，不以本地测试代替）。

## verify-knowledge-hits-with-ones-timeline
- 领域：builtin-tool-resource, governed-api-capability
- 归档后路径：`../2026-11-18-verify-knowledge-hits-with-ones-timeline/tasks.md`
- [ ] 3.3 ONES 服务可达后，完成真实知识命中 → 详情 → 评论文件读取链路验收（当前本机 ONES 测试端点未监听）
