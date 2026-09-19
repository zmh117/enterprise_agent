# 受治理知识检索实施证据

## 实施前核对（2026-09-18）

- 实施起点 commit：`898a853`；开始时工作区干净。未执行 Docker 清理、真实部署、数据发布、授权配置或归档。
- 当前 canonical 的 platform-operations 仍只覆盖离线存储/导入，未同步清洗分块与本地向量索引 delta；前置两个 change 在 `openspec list --json` 中分别为 8/8、19/19。当前变更明确依赖其代码事实，不自动同步或归档它们。
- 当前 catalog 最后一项为 `136_expand_sandbox_v2_capacity.sql`。知识存储通过同库 `knowledge` schema；新增治理元数据不得改写 131/133/134 或原有文档、分块、向量身份。
- `VectorService.query` 仅为受限运维检索：READY/profile 检查、本地 Embedding、至多 200 个候选点、当前收录与版本核验、文档去重和每文档最多 3 个证据；尚无 KB/ONES 双权限或用户模型边界。
- 当前 MCP policy 尚无 knowledge-mcp；`PrincipalTokenVerifier` 校验 scope 必须恰好等于当前完整冻结集合，并核对 authorization_hash，不能为权限桥弱化为 scope 子集。
- 当前模型连接发布固定 revision/config hash；Runtime 通过主模型及 Opus/Sonnet/Haiku/Subagent 映射调用 Anthropic-compatible 服务。内部网关白名单只属于连接准入，不构成无外部转发认可。受保护 Session/摘要/产物传播仍需本变更实施。
- 已核对相关 canonical 的管理/业务权限隔离、同一事实源、固定 MCP、精确 Snapshot、模型发布和离线存储边界。本 delta 尚未发生前置同步冲突。

## 验收分层

| 层级 | 状态 | 证据边界 |
| --- | --- | --- |
| 代码与静态合同 | 实施中 | 按实际修改与检查记录，不代表已部署 |
| 合成单元/接口 | 已分阶段执行，端到端未完成 | 不使用真实业务文本/凭据；详见下方逐轮记录 |
| 隔离数据库/容器 | 待执行 | 不迁移正式库，不替代真实 Provider |
| 真实 ONES 来源和本人权限 | 未完成 | 待批次来源确认、技术交叉验证及两位测试用户 |
| 内网模型与出口 | 未完成 | 待实际模型/网关和所有映射出口证据 |
| 人工业务效果 | 未完成 | 待约 50 条人工标签及用户确认质量/时延目标 |

原文自查询、合成案例和真实人工评测必须分别记录。任何失败不得回显查询、标签、原始 Provider 响应、凭据或业务正文。

## 本地评测工具

- 新增严格 JSON 标注集合同和 owner-only 文件/目录读取；明确区分人工、合成、自查询。真实目录 `.local/knowledge-evaluation/` 被 Git 排除，只提交虚构样例。
- `evaluate_knowledge` 支持无数据库的 `--validate-only` 和当前 schema 的离线 dense 评测。复用现有 query，不写索引/来源；全部标签先解析到当前收录文档，再发查询，结束复核语料与实现摘要。
- 输出文档 Recall@10、MRR@10、无答案误报、nearest-rank 延迟、partial/bounded 和固定失败分类；调用失败不从有答案分母消失，无答案故障不伪装成正确拒答。问题、query_id、标签、命中明细和原始异常均不输出。
- 权限后可见相关集合的纯指标测试已覆盖，但离线 CLI 不执行真实用户权限/详情链路：`authorization_verified=false`、`end_to_end_latency=null`，不接受 JSON 自报 allowlist。
- 新增 30 项合成测试；知识评测/向量/分块/导入/Compose/测试治理组合回归：124 passed、3 skipped（38.61 秒）。跳过项要求显式隔离 PostgreSQL/Qdrant 端点，未使用正式库代替。
- 三个新增生产 Python 文件 Ruff 与严格 MyPy 通过，测试文件 Ruff 通过。没有读取真实问题、调用外部模型或更改部署；尚无真实 Recall/MRR 基线。
- 主/可选知识 Compose 配置、全仓库 Markdown 链接、严格 OpenSpec 与已跟踪/新增文件差异检查通过。当前进度 5/39，未提交、未推送、未归档。

## 实施暂停点：直接 Agent 的业务授权对象

任务 5.2 和 identity-access delta 要求直接 Agent 也有明确 KB grant，但目前设计未规定该 grant 归属的业务访问对象、委派及角色编辑合同。实际代码与数据库仅有业务应用路径：

- `rbac_role_application_access.application_id` 为非空外键；其 Tool/数据范围共同归属于该访问记录，没有直接 Agent 对等业务记录。
- `BusinessAuthorizationService.decide` 在找不到业务应用时返回 `application_not_found`；`PrincipalTokenIssuer.issue_business_mcp_for_job` 对每个工具都复核 `business_application_id` 的业务授权。
- `OnesPrincipalResolver.resolve` 同样通过业务应用授权服务复核详情 Tool。因此仅增加 KB 范围关系并不能让直接 Agent 完成 ONES 双权限链。

需要用户确认：首版只通过已有业务应用发布/运行知识 Agent（直接 Agent 继续拒绝），还是本轮增加直接 Agent 的角色业务访问记录、委派/Web 与 Principal/ONES 合同。不得默造应用 ID、借项目 use grant 或跨角色拼接绕过。当前尚未添加迁移、改写授权合同或注册知识 MCP；任务 3–11 保持未完成。收到选择后先同步本 change 的 proposal/design/delta/tasks，再继续 apply。

## 范围决定：首版仅业务应用（2026-09-18）

用户明确选择仅通过业务应用使用知识库，沿用现有授权体系，保留 KB 与本人当前 ONES 双重校验。已同步 proposal、design、identity-access delta 与任务 5.2/5.3；直接 Agent、项目 use grant、其他应用的 KB 授权均不能替代当前应用授权。不新增直接 Agent ACL，不虚构应用身份；该决定不构成正式迁移、资源发布、角色授权或部署许可。

## 治理存储基础（2026-09-18）

- 本轮起点 `bc4ef5e`，工作区干净。新增前向迁移 `137_expand_knowledge_retrieval_governance.sql`，未修改任何历史迁移；正式数据库未迁移，Docker 服务未重启，真实数据未发布。
- 同一 `knowledge` schema 新增 source_binding、retrieval_resource、retrieval_revision、retrieval_verification 四张元数据表；补 PostgreSQL/SQLite 对等定义、中文注释、事实源登记及 schema head 回归。来源默认为 PENDING，资源无发布指针，不预置角色授权。
- 数据库约束覆盖同来源修订唯一、最多一个 VERIFIED 绑定、同知识库最多一个启用资源、资源内修订唯一、草稿/发布/验证引用必须属于同一资源；存储表不代替后续资源发布和业务授权应用服务。
- 来源绑定应用基础支持人工完整批次确认摘要、固定实例/目标摘要、完整来源版本摘要、确定性最多 20 项技术交叉检查、换版撤销旧绑定、幂等撤销和安全审计。抽样数量单列，不把抽样存在当完整来源证明；Provider 异常不回显。来源导入锁和外部 I/O 后复核用于防止换版、撤权和语料变更竞争。
- 技术核验目前只通过合成适配器验证合同，生产适配器未配置时明确拒绝；没有管理 API 或运行端调用接线，任务 3.2 保持未完成。未注册 knowledge-mcp，未实现角色 KB 授权或模型边界，不得称为 Agent 已可检索。
- 组合回归：231 passed、3 skipped（105.04 秒），覆盖新增治理、知识评测/向量/分块/导入/Compose、迁移 catalog/注释/事实源、DingTalk/文件/资源/outbox 迁移和测试分层。三个跳过项需要隔离 PostgreSQL/Qdrant 端点，未使用正式库代替。
- 加强缺少当前版本和 20/21 项核验边界后，治理专项 25 passed（30.19 秒）。原始七表内容摘要、分块行、Qdrant 替身点/payload 保持一致；导入重放无重复，索引重放零编码。此为 SQLite/合成证据，不是真实 ONES、真实向量服务或 PostgreSQL 运行验收。
- Ruff、治理模块严格 MyPy、主/可选知识 Compose 配置、Markdown 链接与严格 OpenSpec 校验通过。任务 3.1、3.3 已完成，进度 7/39；未提交、推送、归档。

## 身份接线决定：复用现有 ONES JWT（2026-09-18）

用户提出使用之前的 JWT 核验 ONES 身份。按现有代码合同复用 ONES Business Principal JWT 签发/验证机制，不复用已结束 Job 的历史 Token，不扩大 scope，也不把 JWT 当 ONES 登录凭据。`OnesPrincipalResolver.resolve` 要求 RUNNING 业务应用 Job、本人身份、Publication/Snapshot 与当前详情 Tool grant，再解析其唯一 ONES 绑定、默认 Team 和受管 Credential。

设计与 platform-operations delta 已补此边界。固定技术核验接线、有效 Job 上下文与权限桥仍待实现；没有签发/读取真实 JWT，没有调用真实 ONES，也没有增加管理员代查通道。

## ONES 来源核验与资源管理接线（2026-09-18，后续进展）

本节更新上述“仅合成适配器、无管理 API”的历史实施状态，不改写既有证据。继续基于 `bc4ef5e` 和上一轮未提交工作；未迁移正式库、发布真实资源、配置角色授权、重启服务或提交代码。

- 已接通来源管理 API → 平台既有 ONES Principal 签发 → 固定 `ones-mcp` 内部来源核验入口。浏览器只提交本人 RUNNING 业务应用 `job_id`，使用 Cookie/CSRF 管理鉴权；签发与每项核验保留精确完整 scope、当前详情 Tool grant、本人 ONES 身份/默认 Team 和 Job/Publication/Snapshot 检查。
- ONES 内部入口独立覆盖 Host/Origin、唯一 Bearer、4 KiB 请求限制、严格字段、每进程最多 4 个在途核验及同 Job 每分钟一次。复用固定详情 Operation、既有一次 401 刷新和响应解析；核对 UUID、Team、来源项目。核验响应和 MCP 操作审计仅保留引用/安全摘要，正文和 Token 不持久化。没有新增模型可见 Tool 或通用代调用入口。
- 来源核验技术证明记录 `verified_job_id`；该字段为历史不透明引用，不要求已清理 Job 永久存在。仍要求人工完整批次证明，最多 20 项技术抽样不能冒充全量来源证明。
- 新增知识检索资源应用服务和管理 API：默认未发布、追加草稿、外部服务验证、最新验证事实、显式发布、停用/归档、业务无关的管理 CAS。验证不持有外部 I/O 事务，返回前检查撤权、来源/索引/草稿变更；失败验证提交安全事实，不能沿用较早成功结果。
- 单调用 pin 绑定发布版本、来源证明、索引配置/语料摘要及状态版本；返回前重验，无旧索引/未发布 fallback。编辑未发布草稿不使当前发布失效；停用再启用仍使原 pin 失效。当前为可复用解析服务，Knowledge MCP 调用方仍待后续任务接线。
- 未应用的 migration 137 补核验 Job、首次发布事实、验证管理 revision 和资源状态 revision；PostgreSQL/SQLite 对等列、约束、中文注释与事实源登记同步更新。最新验证按管理 revision 排序，不依赖可能回退的时钟。
- 管理 API 严格拒绝未知字段、重复 JSON key、环境/任意 URL/凭据覆盖、超限或异常嵌套 JSON。管理接口只有元数据状态投影；Web 表单尚未实现。新增[治理运行说明](../../../docs/runbooks/knowledge-governance.md)。

验证边界：

- 扩大回归 **399 passed、3 skipped（140.79 秒）**，覆盖治理、资源/API、真实签验合成 JWT + Mock ONES HTTP、原 ONES MCP/Provider/Principal、知识评测/向量/分块/导入/Compose、相关 migration/catalog/注释/事实源和测试分层。
- 随后补异常嵌套 JSON 拒绝并统一新增代码格式，管理 API 专项 **10 passed（4.08 秒）**；Ruff/MyPy 再验通过。
- 核验专项包括正确核验、直接 Agent/非本人或终态 Job 拒绝、详情撤权、来源/实例/Team 不符、跨 audience/非完整 scope/旧 authorization hash、Provider 200 业务失败/错误结构/归属变化、403/404/429/500/超时、首次 401 刷新及第二次 401 不再刷新、请求过程中撤权。所有数据与密钥均为测试合成值，没有真实 ONES 调用。
- 三项跳过为需显式隔离 PostgreSQL（导入、分块）及 PostgreSQL+Qdrant（向量）的集成测试；本次明确取消继承这些端点变量，没有以正式数据库替代。未得到真实 PostgreSQL/向量服务或真实 Provider 验收证据。
- 新增文件已登记测试分层；Ruff、7 个生产源文件严格 MyPy、主/可选 Compose `config --quiet`、Markdown 链接及严格 OpenSpec 校验通过。没有 Web 改动，因此没有声称 Web 表单已验收。
- 任务 3.2、4.1、4.2、4.3 完成，当前 **11/39**；任务 6 的完整知识服务双身份桥、任务 7–10 和真实验收仍未完成。已实现来源投影不能代替知识检索权限桥或 60 秒搜索预算。

## 实施暂停点：知识库显式拒绝的事实源

按任务 5.1 核对时发现设计前提不符：canonical identity-access 要求受管显式拒绝，本 change design 写“沿用现有机制”，但当前 `AuthorizationEvaluator`、`BusinessAuthorizationService.decide`、`AuthorizationCenterRepository` 和迁移中只有启用应用访问/Tool/范围的允许链路，没有可复用的显式拒绝存储或判定链路。不能把未授权/撤销授权当作覆盖其他角色允许的显式拒绝，也不能读取已退役策略表作为 fallback。

依 `openspec-apply-change` 在任务 5 暂停并请求用户确认：建议仍在现有角色业务访问记录下增加 typed KB allow/deny；同一应用中任一有效角色对 KB 的 deny 覆盖其他角色的 allow，不能影响其他应用；修改要求二次确认与原因，委派和原子保存保持约束。另一选择是明确修订首版 delta，暂不支持显式拒绝。当前没有擅自选择或修改角色授权代码/表；该问题未解决前不勾选 5.1–5.3。

## 范围决定与授权配置实现（2026-09-19）

用户明确沿用“角色 → 多个业务应用 → 各应用独立知识库允许范围”，不增加拒绝配置。角色 A 的 app1 有 KB、app2 无 KB，则不能把 app1 的允许借到 app2；某角色未配置不否决其他角色在同一应用下的完整允许。该确认解决上一节暂停点，proposal/design/identity-access delta/tasks 已同步；没有静默改写 canonical baseline 的其他领域规则。

- 未应用的 migration 137 增加 public `rbac_role_application_knowledge_base`，归属既有角色应用访问记录并外键引用 knowledge.knowledge_base；只有明确 KB ID，无 effect/deny/通配符。不自动回填、发布、授权或改文档、分块、索引。
- 角色管理接入业务 revision、原子替换、角色复制、当前明确集合、同应用委派上限、严格请求字段和元数据审计。规范化及 current-all 展开处于保存事务；管理权限拒绝审计仍在事务外保留。
- RBAC 求值要求同一条有效角色应用记录同时允许 Tool 与 KB；平台管理员不绕过业务范围。用户/角色/成员/应用/访问停用、成员过期和 KB 撤权即时影响求值。授权投影与单 KB 判定一致，但目前尚未连接 Knowledge MCP 的列表/搜索端点。
- 新 Job 的既有 authorization hash 纳入 KB 集合、应用/访问标识、角色业务及元数据修订、成员修订与到期时间。使用实际 Job 创建与快照服务验证授权变化产生新摘要，旧快照不被改写；此测试使用已注册的合成只读 Tool，不冒充 Knowledge MCP 完整 Job 验收。
- Web 沿用每个应用授权卡片，只选择 KB 引用；展示明确 ID、当前全部和撤权语义。原有 KB 选择在修改 Tool/数据范围时保留，不可授予的旧 ID 显示并可显式移除。预览只说明当前 RBAC，不代表资源/Job/ONES 验收。保存冲突保留本地选择；没有拒绝开关或重复资源表单。

验证记录：

- 后端扩展回归 **269 passed（84.12 秒）**：授权、迁移/注释/事实源、Principal、知识治理/资源/API、来源核验及 ONES MCP。发现并修正角色测试对旧种子描述为空的过时假设：测试显式构造旧描述，保留业务断言；新增 RBAC 表的 public catalog 更新为 131 表 / 1744 列。
- 补 API 管理权限/按应用保存回读、拒绝审计与并发重复检查后，KB 专项 32 项及既有角色授权 19 项组合 **51 passed**。并发用隔离 SQLite 文件库运行五次，避免 shared-cache 内存库的表级锁限制影响用例；仍要求一成功、一 revision_conflict，不容忍锁错误或部分写入。
- 原导入/分块/向量/资源 schema/Compose 回归 **91 passed、3 skipped（36.42 秒）**。跳过项为缺少显式隔离 PostgreSQL、PostgreSQL+Qdrant 端点，不以正式库替代。
- Web 授权组件 **10 passed**，覆盖 app1/app2、已有 KB 保留和 409 草稿保留；`tsc -b`、改动文件 ESLint、后端 Ruff/MyPy、主/可选 Compose 配置、Markdown 链接、严格 OpenSpec 和 diff 校验通过。
- 任务 5.1、9.2 完成，进度 **13/39**。5.2/5.3 仅完成 RBAC 部分：RUNNING 业务 Job、直接 Agent 拒绝、精确 Snapshot 的知识执行接线，以及 KB+ONES 双权限端到端仍未完成，因此保持未勾选。任务 6–8、工具资源 Web 管理和真实验收继续保持未完成。
- 本轮没有迁移正式数据库、配置真实角色授权、发布资源/应用、注册模型可见 Knowledge Tool、调用真实 ONES/模型、重启服务或提交/推送/归档。

## Job 关卡与 ONES 候选只读投影（2026-09-19，继续实施）

本节更新上一节 5.2 的实施状态；不是平台双身份桥、模型边界或真实 Agent 检索验收。

- 新增共享 `KnowledgeJobGate`：仅接受本人启用 human 用户的 RUNNING 业务应用 Job，核对 Session/Agent/Application Publication、内容哈希、Agent 工具包络、应用工具子集、精确 Job Snapshot 与冻结 authorization hash。目录/检索必须同时在同一当前角色应用记录完整获准，并具备冻结且当前获准的 ONES 详情 Tool；返回前重验当前授权摘要。
- KB 范围同时受创建 Job 时冻结集合和当前完整允许集合约束；后来扩大角色 KB 不扩大旧 Job，不改旧快照。知识 Tool 的冻结授权不再要求 environment/base/workshop，其他 Tool 原合同不变。直接 Agent 携带知识能力时在创建 Job 前拒绝。Knowledge Principal 签发显式接入该关卡，缺少关卡时失败关闭，保留完整 scope 与独立 audience。
- 未应用的 137 迁移扩展三张 Agent/Application Tool 表的固定 Server 域，允许未来注册的 `knowledge-mcp`。SQLite 重建逐列复制、PostgreSQL 仅替换 CHECK；合成迁移验证旧发布行保持一致，任意 Server 仍被拒绝，外键完整。没有修改应用过的历史迁移或增加旧发布工具。
- 将只读发布解析拆为 `KnowledgeResourceReader`，与管理服务共享来源/配置/发布/索引验证逻辑；消费者只需固定目标配置及数据库，不持有管理权限、签名私钥、Embedding/Qdrant 客户端。原资源治理回归保持通过。
- `ones-mcp` 新增非模型可见的固定 `/internal/knowledge/work-item-readability`。独立 Host/Origin/唯一 Bearer、4 KiB 请求体、严格 JSON 字段、最多 50 个唯一块 ID、每实例 4 个在途批次；只接受当前 KB/资源版本/索引内的块引用，从 PostgreSQL 解析当前文档/工作项，先去重再访问 Provider。
- 复用本人 ONES 完整 scope Principal、身份/默认 Team、固定详情 Operation 与一次 401 刷新；核对任务 UUID、来源实例/Team 和项目 UUID。允许结果只输出引用及当前编号，不输出离线标题/正文/附件或 Token。明确 403/404 过滤；其余 Provider/凭据/响应结构/预算错误使整批失败，无部分成功。每次重新检查，不缓存允许结果；返回前复核 Job/角色/KB/详情权限、身份、来源、索引与候选版本。
- 调用内预算传播到 Provider HTTP、登录 HTTP 和刷新锁等待，过期结果丢弃；不改变未设置预算的普通 ONES 行为。此处不冒充任务 7.3 的完整检索总 deadline/Job 剩余预算，后续知识工具编排仍须接线。

验证记录：

- 扩展回归 **423 passed（107.65 秒）**：知识 Job/只读投影/RBAC/治理/资源/API/来源核验，Principal/多业务 audience，ONES 运行/身份/HTTP/架构，角色授权、Job 创建、调试授权及 schema/事实源。
- 随后补来源撤销、项目/默认 Team 变化和详情撤权在请求前/中的 8 个场景，内部投影专项 **52 passed（7.27 秒）**。Job 关卡专项 **27 passed**；上述数字有重叠，不累加为独立用例数。
- 新测试登记分层。Ruff、12 个生产源文件 MyPy、主/可选 Compose 配置、严格 OpenSpec、Markdown 链接、diff 检查通过；没有本轮 Web 改动。所有 JWT、身份、文档、模型向量和 Provider 响应均为测试合成值，未调用真实 ONES、Embedding、Qdrant 或聊天模型。
- 任务 **5.2、6.3 完成，15/39**。5.3/6.4 的完整平台桥及目录/检索一致性矩阵仍未完成；6.1/6.2、7–8、工具资源 Web、正式部署及真实验收继续保留未勾选。生产 Manifest 尚未开放知识工具，不能声称 Agent 知识检索已可用。
- 本轮未执行正式迁移、授权/发布、服务重启、提交、推送或归档；未访问真实密钥和业务数据。

## 平台双身份可读性桥（2026-09-19，继续实施）

- 平台新增固定 `/api/internal/knowledge/work-item-readability`，必须同时提供独立知识 Service Principal 和原 Knowledge Principal。前者固定 issuer、`sub/azp=knowledge-mcp`、`aud=knowledge-readability-bridge`、完整唯一内部 scope、授权摘要和不超过 300 秒 TTL；后者复核独立 audience、完整 scope、RUNNING Job/用户/发布/快照以及当前 KB/详情授权。文件 Worker、ONES Principal、交换两种 Token 或伪造 actor 都不能补全身份。
- 可选 `KNOWLEDGE_BOOTSTRAP_TOKEN_FILE` 进入现有服务身份签发机制；未配置时不读取知识凭据、不装配平台桥，原三个 Worker 角色保持兼容。启用时受管文件规则、与其他角色凭据不得复用等约束保持有效。知识服务无需签名私钥；可选 Compose 接线仍属于未完成任务 10.1。
- 平台签发前按 PostgreSQL 当前 KB/已发布资源/来源/索引/块成员解析文档引用，复用原完整 ONES scope 签发器，只在内存固定调用 ONES 只读投影。无 URL、server、scope、Team、operation、Provider 凭据或工作项 UUID 覆盖；不跟随重定向或继承环境代理。
- 请求合同与候选成员逻辑抽到共享模块，ONES 和平台共用；可读性请求上限统一 8 KiB（可容纳 50 个合法长 ID），来源管理核验入口仍为 4 KiB。响应最多 64 KiB，严格核对 Job/用户/KB/资源/索引和每个块对应的当前文档/版本/UUID；同一文档不能出现矛盾结果。只返回允许引用与编号，不转发正文或 Token。
- 返回前重验两种 Principal、当前授权、来源/资源/索引/候选和本人 ONES 身份/默认 Team/ACTIVE 凭据状态；平台只读取身份及凭据状态字段，不读取/解密凭据。Provider 403/404 只产生无工作项信息的内部不可读项，其他故障整批失败，无允许结果跨调用缓存。401 刷新继续复用 ONES 原路径，仅一次。
- Host、Origin/Cookie/query、重复 Header、JSON 重复/未知字段、输入大小、每实例 4 个在途批次、HTTP 响应大小/重定向/错误结构及审计脱敏均有独立覆盖。调用内 I/O 预算和过期结果丢弃不替代任务 7.3 的整体搜索 deadline/Job 剩余预算。
- 桥专项 **91 passed（11.93 秒）**，使用实际合成签验、Job/发布/授权/知识元数据以及 Mock ONES HTTP；包括平台收到 ONES 成功后再发生撤权、身份解绑、凭据停用和候选变化的情况。签名密钥、服务凭据及业务数据均由测试合成，未访问真实凭据或真实 ONES。
- 最终扩展回归 **566 passed（131.87 秒）**：包含上述桥专项、ONES 内部投影/运行/身份/HTTP、Knowledge Job/RBAC/治理/资源/API/来源核验、Principal/服务身份、多业务 audience、角色授权、Job 创建/调试、schema/事实源、特性配置、运行配置协调和测试分层；与专项数字有重叠，不相加。Ruff、9 个生产源文件 MyPy、主/可选 Compose `config --quiet`、严格 OpenSpec、Markdown 链接和 diff 校验通过。本轮没有 Web 修改，未新增 Web 验收声明。
- 任务 **6.1、6.2、6.4 完成，18/39**。生产 Manifest 仍未注册知识工具，目录/检索、内网模型/Session 数据边界、工具资源 Web、可选部署和全部真实验收保持未完成。未执行正式数据库迁移、授权或发布、服务重启、提交、推送或归档。

## 授权目录与有界检索核心（2026-09-19，继续实施）

- 完成 `KnowledgeDirectory` 应用服务：独立 Knowledge Principal、完整冻结 scope、RUNNING 业务应用 Job、当前角色应用 Tool/KB 与冻结范围交集；按本人 ONES 实例/默认 Team 及当前已发布资源过滤。每页固定 50 个稳定 KB ID，只有身份/管理名称/安全状态，没有文档数、样本或标题。
- cursor 由进程内临时 Fernet 密钥保护，绑定 Job/用户/应用/发布/Snapshot/冻结授权、当前授权和全部可见资源/身份摘要，300 秒到期。重复使用相同 cursor 可重读同页，篡改/跨主体/过长/过期/重启失效；角色、来源、资源或页外集合变化要求从首页重查。没有新增共享 Secret 或游标表，不承诺跨副本连续分页。
- 完成 `KnowledgeSearch` 应用服务：严格 KB/query/top_k 输入，固定内部 Embedding/Qdrant 客户端；一次最多 200 个候选点，回 PostgreSQL 核对当前收录/修订/点身份，按文档去重，在同一池内每批至多 10 个文档通过固定双身份桥补足，最多检查 50 个工作项、每实例最多 4 个在途检索。不使用离线 CLI 的重复扩大 top-N 作为在线补候选，避免累计读取超出上限。
- 候选验证与证据聚合抽为离线/在线共用纯函数；原离线构建、索引身份/payload、查询输出和默认重试保持兼容。在线 HTTP 不额外重试，Knowledge 服务不签发 ONES Principal，不读取 ONES 凭据；严格响应投影抽到共享合同模块，避免客户端依赖平台签发器。
- 只返回已核验工作项及文档/版本/索引/来源绑定引用、有限分数、每文档最多 3 个证据位置。明确 403/404 才过滤；Provider、身份、解析或依赖故障整次失败，先前允许项也不返回。预算内无法补齐标记通用 partial，不返回被拒绝数量或身份；查询/正文/Token/原异常不进入结果或安全审计，不跨调用缓存允许结果。
- 16 格目录/搜索矩阵补齐任务 5.3 的应用服务证据，结合既有 app1/app2、跨角色拼接、并发 revision、直接 Agent/旧 Snapshot 测试，验证当前双权限。矩阵发现知识 Tool 撤销后目录仍返回空集合；已在共享 Job 关卡逐一要求两个知识 Tool 和详情 Tool 的当前权限，使 Tool 撤权明确拒绝。仅 KB 允许范围为空时目录仍可返回空集合；目录可见而 ONES 拒绝时搜索没有命中。
- 已实现本地调用预算：以当前 Job claim 的 `locked_at`、retry_count 和执行策略计算至多 60 秒，I/O timeout 取剩余预算，阶段之间/每批/返回前复核并丢弃迟到结果。**任务 7.3 仍不勾选**：服务身份刷新及 HTTP 平台/ONES 子调用尚未接收统一剩余 deadline，同步阻塞 I/O/数据库操作也没有端到端硬取消证据。合成推进时钟测试只证明结果作废与部分返回语义，不代表真实 60 秒墙钟保证。
- 任务 **5.3、7.2、7.4 完成，21/39**；7.1 生产 Manifest/Streamable HTTP/Runtime 接线、7.3 完整 deadline、8 内网模型与 Session 数据边界等继续保留未完成。测试只在进程内注册合成知识合同，没有对生产开放工具。
- 本轮没有读取真实业务数据/凭据，没有真实 PostgreSQL、ONES、Embedding、Qdrant 或聊天模型请求，没有正式迁移/发布、服务重启、提交、推送或归档。真实召回质量与时延仍未验收。

本轮验证记录：

- 修正共同关卡后扩展回归 **780 passed、3 skipped（189.31 秒）**：知识目录/检索/双身份桥/内部投影/治理/RBAC/Job，原导入/分块/向量/评测/Compose，Principal/服务身份、角色配置、ONES 运行/身份/HTTP/架构、迁移/资源 schema/事实源、特性配置、运行配置协调及调试授权。三项跳过仍为要求显式隔离 PostgreSQL、PostgreSQL+Qdrant 的集成测试；运行时取消继承这些端点变量，不使用正式库替代。
- 随后补 UTF-8 非法代理字符参数拒绝，搜索专项 **73 passed（11.90 秒）**；该数字与扩展回归部分重叠，不相加。专项还覆盖 200 点/50 工作项/4 并发、过期 claim、软截止 partial、硬预算结果作废、逐阶段撤权、失败脱敏、在线无额外重试及离线原策略。
- 独立 Runtime/MCP 合同与架构专项 **52 passed（2.34 秒）**，没有提前注册生产知识工具。目录覆盖 0/1/50/51/121 库及多库多文档，分页无重复遗漏；平台与 ONES HTTP 跳转使用实际合成签验和 TestClient/Mock Provider，不是部署验收。
- 新测试已登记分层；Ruff、11 个生产源文件严格 MyPy、主/可选 Compose `config --quiet`、严格 OpenSpec、Markdown 链接与 diff 校验通过。本轮没有 Web 改动或新增 Web 验收声明。

## 跨跳预算与部署侧模型认可（2026-09-19，继续实施）

- 搜索将 UTC 毫秒截止时间经固定 `X-Knowledge-Deadline-Ms` Header 传到平台与 ONES，每跳仍验证完整原身份/授权/候选合同，并取传入值、本地 60 秒、当前 Job attempt 剩余预算的最小值。非法、重复和过期值在 Provider 前拒绝；未来时间不能扩大本地预算。Header 不是授权、不进入模型参数或 JWT scope；没有读取真实凭据或来源数据。
- 知识调用内共享剩余预算到 Service Principal 缓存命中/刷新锁/兑换、ONES 登录/刷新锁/Provider；过期刷新结果不能缓存或使用旧 Token 兜底。系统预算耗尽不再把正常 ONES Credential 标成 REAUTH_REQUIRED。无预算的普通服务身份/ONES 行为和离线向量构建重试保持兼容。
- 生产路径新增有界 HTTP 传输助手：沿用原客户端的固定目标、认证和解析，仅在知识预算下用可取消网络协程覆盖整次 HTTP 请求；关闭环境代理、拒绝重定向及非 identity 编码响应，保持原字节限制。知识 HTTP 期间抑制 httpx/httpcore 的 URL/连接日志，保留平台安全审计，调用结束后不影响普通库日志。没有新增 Provider Operation、登录实现或通用模型 HTTP Tool。
- 临时本机 127.0.0.1 HTTP 服务验证停止响应及持续滴流都会触发总 timeout，滴流端可观察到断连。补充双 HTTP 跳截止时间传播、生产客户端分支、刷新锁与 Token 兜底、非法 Header、大小/编码/代理/重定向及日志隔离；最终预算专项 **27 passed（5.26 秒）**。这些是合成/本机传输证据，不是 ONES 生产验收。
- **7.3 保持未完成**：生产 MCP/ASGI 入口的全调用取消、数据库连接池/SQL 等待控制，以及同步入口 DNS/事件循环清理的故障注入证据仍缺失。本轮没有以网络 timeout 通过冒充完整 60 秒墙钟保证，现有返回前预算检查仍丢弃迟到结果。
- 完成任务 **8.1**：可选部署配置 `INTERNAL_MODEL_POLICY_FILE`，默认空，不修改实际 `.env`。受控只读文件绑定连接 ID/revision ID/revision/config hash、固定内部网关和五个有效模型映射、路由 ID/配置摘要、出口证据摘要、UTC 有效期；文件和单条认可均生成稳定 hash。限制绝对路径、普通文件、所有者/写权限、64 KiB/100 条、严格字段及唯一修订；原模型协议和主机白名单不放宽。
- 认可每次重新读取：缺省、非法、过期、撤销、配置或目标不匹配均不能授予 internal_only；新连接版本不自动继承旧版本认可。模型 API 增加严格只读 `internal_model_deployment` 投影，普通编辑请求不接受“认可/内网”字段。模型映射先沿用现有空值继承主模型规则，再核对认可。文件内容是受信部署声明，真实路由/出口证据仍须任务 11.2 验收，不能仅凭摘要或私网地址证明。
- **8.2/8.3 仍未完成**：当前只交付部署认可事实及 API 投影，没有将其冒充已实施的发布/运行阻断或 Session/摘要/结果引用标记。生产 Knowledge Manifest 仍未注册，不开放外部模型读取知识内容。
- 最终扩展回归 **956 passed、3 skipped（197.40 秒）**：知识全模块、双权限、Principal/服务身份、ONES、迁移/schema、模型连接/Agent 发布、运行配置、Runtime/MCP 协议与架构等。跳过项为显式隔离 PostgreSQL、PostgreSQL+Qdrant 集成测试；运行时取消继承相应端点变量。预算日志专项和空映射复验属于追加覆盖，与扩展回归重叠，不累计数字。
- Web 模型页面兼容性 **13 passed**，`tsc -b` 通过；没有改 Web 页面或宣称知识资源 Web 管理完成。Ruff、15 个相关生产源文件 MyPy、主/可选 Compose 配置、严格 OpenSpec、Markdown 链接和 diff 校验通过。
- 进度 **22/39**。未部署/重启/执行正式迁移、修改实际模型/角色配置、发布资源、调用真实 ONES/模型或提交/推送/归档；未生成虚假的路由和出口认可文件。

## 发布门禁与 Runtime 协议设计关卡（2026-09-19，继续实施）

- Agent 草稿校验/发布增加部署认可与 ONES 详情 Tool 依赖检查；Publication 固定模型快照及 `model_data_boundary` 的单条认可摘要。运行用途读取和回退会复核，普通编辑请求不能自行填边界。Application 子集不能移除检索所需详情 Tool，发布/激活复核模型认可。撤销、过期、文件失效、路由/出口证据或映射变更拒绝使用，管理页仍可查看；其它连接的策略增补不使本条未变认可失效。
- Worker 使用原 KnowledgeJobGate 在模型/摘要前复核当前工具授权；在受签名 Runtime 边界及 Session 传播完成之前，受保护 Publication 一律以 `knowledge_runtime_boundary_unavailable` 拒绝执行，即使 Application 子集已去掉知识 Tool。Runtime 也在模型凭据解析前拒绝知识请求。没有注册生产 Knowledge Manifest 或向旧 Job 注入工具。
- SDK 层准备内网防护：固定全部映射、禁止独立 fallback/自定义子 Agent/SDK 历史恢复，隔离继承的 Provider/代理/外部遥测环境变量，保留 Job 本地 API 捕获；错误正文不进入一般诊断及异常链。仅以合成绑定和 SDK 替身测试，尚没有来自生产 Runtime 协议的 internal_only 标记，不能描述为已接通内网模型调用。
- **设计关卡，任务 8.2/8.3/8.4 保持未完成**：检查 `agent_runtime_grants.sql` 确认 Runtime 不能读取 Job、Publication、Session 或 RBAC。已撤回尝试读取这些表的 Runtime 实现，没有扩权限；既有模型凭据列权限保持不变。建议新增版本化合同，将 Worker 确定的模型边界/认可摘要纳入 request digest / Runtime Grant，配合控制面 Session/摘要/结果引用的持续传播；具体协议升级待用户确认，已记录在 design Open Questions。不能把合成 SQLite 中可读业务表当成真实 Runtime 准入证据。
- 修复知识测试装配，改为临时目录内真实解析的合成认可文件，关联实际保存的模型 revision/hash；不以 Mock 宽放生产门禁。修复两处扩展回归的陈旧测试准备：版本排序测试明确构造当前 `query_database` schema；Runtime tmpfs 断言同步现行 Sandbox v2 的 1 GiB 默认值，未修改生产容量、DDL 或历史发布。
- 补 Worker 镜像对 knowledge 代码模块的必要 COPY（此前 bootstrap 已依赖该模块）。按 Dockerfile COPY 白名单复制到临时目录执行独立导入，Worker 与 Runtime 均通过；Runtime 未引入业务模块，不扩大镜像/数据库边界。此为本机隔离包导入证据，不是 Docker 构建或部署证据。
- 新增测试登记 `test_suite_tiers.toml`，静态检查包含 11 个相关生产文件 MyPy 和 Ruff。工程回归结果见本节后续记录；总进度仍为 **22/39**。未读取真实凭据/业务正文、执行正式迁移、部署/重启、真实 ONES/模型请求、提交、推送或归档。
- 最终扩展回归 **1069 passed、3 skipped（214.04 秒）**，覆盖知识全模块、模型/Agent 发布、Application 控制面、RBAC/Principal、ONES、Runtime/SDK/审计/协议、镜像与 Compose 安全、迁移/schema 等。三项跳过为要求显式隔离 PostgreSQL、PostgreSQL+Qdrant 的集成测试；运行前移除继承端点变量，没有访问正式数据源。另补 Worker/Runtime COPY 白名单独立导入 **2 passed**，与主回归的 Runtime 导入测试重叠，不累计数字。
- 主 Compose 与可选 `knowledge/compose.yml` 的配置校验通过，严格 OpenSpec、Markdown 链接、Ruff、11 文件 MyPy 与 `git diff --check` 通过。未修改 Web 页面，本轮不新增 Web 或容器运行验收声明。

## 简化模型要求与 Knowledge DDD 整理（2026-09-19，用户确认后）

本节记录新决策和本轮代码证据，取代前述强制内网聊天的待实施要求，不修改此前历史记录或将已取消的协议/继承任务冒充完成。

- 用户已接受授权后的检索引用、ONES 正文与上下文进入 Agent 既有聊天模型，包括外部模型；Embedding 仍固定本地/内网。取消部署认可文件、模型 API 认可投影、internal_only 发布/执行门禁、SDK 特殊覆盖与 Session/摘要/产物继承设计；不再为此扩展 Runtime 协议。原规则专属源码/测试已备份后移除，替换为新决策的行为测试。
- 保留模型版本/config hash 冻结、既有映射规则和 Runtime 请求签名/最小数据库权限。保留知识工具和 ONES 详情 Tool 发布依赖、Worker 模型/摘要前当前权限复核，以及检索的 KB + 本人 ONES 双重授权。Worker 关卡改由 bootstrap 注入，不在 AgentContextBuilder 内创建跨模块仓储。没有重写历史 Publication 或放开默认 Tool 注册。
- knowledge 按 api/application/domain/infrastructure 整理。领域包含规范化、分块、稳定身份、点 payload、合同与 Tool 依赖；应用用例只依赖实际使用的仓储/服务端口；SQL、文件和固定 HTTP 访问归基础设施。可读性桥的限流、候选和返回前复核归应用，具体 JWT/SQL/ONES 访问归适配器。不引入通用 CRUD 框架、事件总线或插件层。
- 原导入与分块的 SQL/事务/checkpoint 移入独立仓储，领域规则保持不变；目录/检索不再读取其他服务的数据库属性，管理 API 不构造客户端。CLI、bootstrap、ONES 和 Embedding 镜像 COPY 全部更新，不保留平铺转发层；schema 事实源清单和当前手册链接同步指向新实现。
- 与 Git 基线逐项比较规范化、分块、稳定 ID、点 payload 等 **24 个定义，AST 差异为 0**。固定 Embedding profile/锁文件和 Runtime 数据库 grant 文件未改动；新增 golden profile/ID/payload 与分层/镜像回归。评测 implementation code_hash 如实变化，不影响语料、索引或向量身份。
- 回归过程中修复测试故障注入仍指向旧类、ONES 入口旧预算构造、目录桥适配器接线以及 schema 事实源清单旧路径；模型专项明确构造合成保存的外部模型版本，避免把无模型的旧夹具当外部模型验收。未以放宽断言或授权规则消除失败。
- 最终知识全量：**578 passed、3 skipped（152.92 秒）**。覆盖导入/分块/向量/评测、来源与资源、API、目录分页、当前权限/撤权、双身份桥、跨跳 deadline、模型边界及分层/精简镜像。三项跳过分别需要隔离 PostgreSQL、PostgreSQL、PostgreSQL + Qdrant；没有访问正式数据库或真实向量服务。
- 最终扩展回归：**590 passed、2 subtests passed（99.50 秒）**。覆盖模型/Agent 发布、业务应用、RBAC/Principal/服务身份、ONES、Runtime/SDK/审计/协议/数据库权限、Worker、迁移/schema 和测试分类。与知识全量为不同测试文件；此前专项/中间失败重跑不重复累计。
- Ruff 通过；后端及相关适配入口 MyPy **477 source files** 通过；本轮分层/入口文件格式检查通过。主 Compose、可选 knowledge Compose 配置、严格 OpenSpec、Markdown 链接与 git diff 检查均通过。精简镜像证据仅为按 Dockerfile COPY 白名单独立导入，不是实际 Docker 构建/启动验收。
- 本轮完成修订后的 **8.1–8.4、12.1–12.4**，整体 **29/43**。7.1 生产 MCP 注册/接线、7.3 完整墙钟 deadline、知识资源 Web、可选部署及全部真实环境/人工评测门槛仍未完成，不补勾。无新增 Web 验收声明。
- 本轮没有读取真实凭据或原始业务消息，没有真实 ONES/聊天模型/Embedding 请求、正式迁移、重导入、重分块、重编码、资源/角色发布、服务重启、提交、推送或归档。删除的旧限制实现保留在本机临时源码备份；现有数据与索引无需重建。
