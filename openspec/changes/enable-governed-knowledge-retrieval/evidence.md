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
| 隔离数据库/容器 | PostgreSQL 权限边界已验证，完整容器链路未完成 | 临时 tmpfs 数据库，不迁移正式库，不替代真实 Provider |
| 真实 ONES 来源和本人权限 | 未完成 | 待批次来源确认、技术交叉验证及两位测试用户 |
| 本地 Embedding 与既有聊天模型 | 真实链路未完成 | 用户已取消强制内网聊天；仍需真实新 Job 证据 |
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

## 正式工具合同与 Runtime 固定路由（2026-09-19，继续实施）

- 完成任务 **7.1、9.3**，进度 **31/43**。`knowledge_list_bases` / `knowledge_search` 的输入、引用型输出和中文说明进入共享纯合同、生产 Manifest、Tool/角色目录以及 Agent/Application 发布链。知识测试不再 monkeypatch 注册工具，改为使用正式合同；领域/应用层仍不依赖 Runtime 或外部客户端。
- 固定 `knowledge-mcp` Business Principal 策略，独立 audience 与 `mcp:knowledge-mcp:<tool>:invoke` scope；Runtime 默认路由 `http://knowledge-mcp:9108/mcp`，保持部署主机校验及按冻结 Server 集合建立连接。合成测试覆盖两种 audience 凭证隔离、旧 Job 不获得新工具、Manifest 元数据漂移、严格输入/引用型输出，以及无知识工具时不注入知识提示。
- 对齐发布前依赖与既有 Job 门禁：知识目录、检索、ONES 详情必须成套选择，Agent Envelope/Application 子集缺任一项即中文拒绝，不自动扩权。共享工具说明和按有效工具启用的系统提示要求先发现明确 KB、检索引用、再回源详情；不猜 Team，不将零命中/部分结果/服务故障混为全库无数据，业务文本只作不可信数据。
- 新增合同专项 **27 passed**，已包含在以下知识全量中，不重复累计。知识全量 **607 passed、3 skipped（153.45 秒）**；跳过项仍为显式隔离 PostgreSQL 与 PostgreSQL+Qdrant 集成，执行前移除继承端点变量。既有导入/分块/profile/向量身份、授权撤销、分页、桥、预算、分层和最小镜像导入测试继续通过；主/可选 Compose 的合成配置校验包含在该套件中。
- 独立扩展回归 **311 passed（44.99 秒）**：Runtime/SDK、固定 Server 策略、Principal、模型/Agent 发布、业务应用、角色授权、ONES、Runtime 协议和测试分类。两组为不同文件，合计 **918 passed、3 skipped**。Ruff、MyPy（backend/app，**473 source files**）、本轮合同/依赖/测试格式、严格 OpenSpec、Markdown 链接和 diff 检查通过；没有新增 Web 或容器运行验收声明。
- **固定注册不等于检索已上线**。生产 MCP/ASGI 服务入口、安全 MCP 审计与整条链路截止/取消接线仍属于未完成的 7.3，任务描述已显式保留；可选 Compose/最小数据库权限、知识资源 Web、隔离完整服务验收、真实来源与双用户 ONES/模型/人工质量验收仍未完成。未调用真实 Provider/聊天/Embedding、读取正式业务数据、执行正式迁移、重建索引、发布真实资源/角色、重启服务、提交、推送或归档。

## 同级独立 Knowledge MCP 服务入口（2026-09-19，按用户目录要求继续）

- 新增 `services/knowledge_mcp_server/`，与 ONES、钉钉 MCP 同级，不创建单数 service 目录。包含 ASGI/MCP 入口、身份上下文适配、安全错误映射、有界执行、工具适配及狭窄 bootstrap；目录与检索仍由 knowledge 四层用例拥有。新增 `knowledge-mcp` 可选依赖组，沿用项目 `mcp==2.0.0`，不更新其他依赖或引入兼容转发层。
- 固定 `/mcp` 无状态 Streamable HTTP + JSON 响应、9108 端口和 `/health`。独立 Knowledge audience/完整 scope、RUNNING Job、冻结授权、当前角色/应用/KB 与 ONES 双权限继续生效；核对请求上下文与持久化 Job attempt/发布身份。严格关键头/Host/JSON/32 KiB 请求、256 KiB 工具结果检查；SDK 参数错误与依赖异常不回显输入。MCP 根审计不存 query、cursor、库名、命中 UUID 或正文，只保存工具名、安全版本/计数/错误码及关联 ID。
- 服务启动只装配公开 JWKS、受限数据库访问组件、固定内部 Embedding/Qdrant、独立服务短期身份和平台桥，不创建平台全量 Container、不加载主密钥/签名私钥/模型 Key/ONES 凭据仓储。bootstrap 测试使用不存在的合成服务凭据路径，确认装配不提前读取；没有新增真实配置。`/health` 仅证明 schema/审计依赖，不作为向量/ONES/业务资源 readiness 证据。
- 从入口开始收紧 60 秒预算，超时/客户端断开设置取消信号；嵌套 RetrievalBudget 检查父预算，使已有用例在后续检查点观察取消。SDK JSON 等待本身不读断开事件，ASGI 显式监听并取消等待。固定 4 个真实在途线程槽位，未退出的超时线程仍占槽位，不将取消 Future 误当工作线程停止，也不新增无界排队。数据库/DNS 等阻塞 I/O 的物理取消仍待补齐，不声称进程内所有依赖都在截止瞬间退出。
- 入口专项 **30 passed**（已计入知识全量）：官方 MCP SDK initialize/list/call 与 in-process ASGI 传输、两工具完整合成调用、独立 audience/撤权/执行上下文拒绝、非法请求与异常不泄漏、51 个 KB 按 50+1 续页且游标不进审计、过期请求/迟到结果丢弃、取消向嵌套预算传播、HTTP 断开和超时线程继续占并发名额。全部使用合成 SQLite 和 Mock Embedding/Qdrant/平台桥/ONES，不是 Docker 或真实 Provider 验收。
- 最终知识全量 **637 passed、3 skipped（159.33 秒）**；显式移除 `KNOWLEDGE_TEST_POSTGRES_DSN` / `KNOWLEDGE_TEST_QDRANT_URL` 后运行，三项跳过仍需隔离 PostgreSQL、PostgreSQL+Qdrant。独立扩展回归 **349 passed（30.92 秒）**，覆盖 MCP 审计、Server policy、Principal/服务身份、ONES/钉钉 MCP、Runtime/协议/架构及 Tool Runtime。两组不同文件，合计 **986 passed、3 skipped**，不重复累计入口专项。
- Ruff、MyPy（backend/app + 新服务，**480 source files**）、新增/修改入口格式、严格 OpenSpec、Markdown 链接、diff 检查通过；新增测试登记 contract tier。主/可选 Compose 合成配置兼容测试包含在知识套件内，没有改 Compose/Dockerfile、构建或重启服务。
- 任务 **7.3 部分实施，仍不勾选**，整体保持 **31/43**：尚缺数据库池/SQL 等待的统一截止、阻塞依赖取消/清理故障注入；可选部署/最小数据库 grant、工具资源 Web、完整隔离容器及真实验收仍分别保留。按 OpenSpec 保留未完成项，不将入口代码存在替代验收。未读取真实凭据/原始业务消息，未调用真实 Provider/聊天/Embedding，未正式迁移、重建索引、发布资源/角色、提交、推送或归档。

## 知识资源 Web、可选在线部署与独立数据库账号（2026-09-19）

- 完成 **9.1、10.1–10.3**，进度 **35/43**。工具资源新增知识库页签及来源/资源表单、列表和详情：明确区分存储、来源核验、索引、发布；创建、草稿、验证、确认发布/停用/恢复/归档沿用既有管理 API。角色仍仅按应用配置 KB 允许范围，无 deny 或重复连接配置。
- 新的 API/领域解析和查询模块保持前端分层；严格投影安全字段，不展示业务正文或任意地址/凭据。权限失败、系统异常和并发冲突用固定中文信息；冲突不自动重试或覆盖输入。目录刷新失败保留已有编辑输入，只有显式成功重新载入才更新编辑基线。共享 API 错误解析补 `detail.error_code`，保留既有 `detail.code` 优先级。
- 保留原 `knowledge/compose.yml` 离线用法，新增 `knowledge/mcp.compose.yml` 在线扩展：独立 MCP Docker target、非 root/只读根目录/受限 tmpfs、固定健康检查、仅内部网络；API 追加知识网络与独立 bootstrap。主部署和仅离线环境不新增必需服务或 Secret，不改现有模型/向量卷。
- 新增固定 `knowledge_mcp_reader` 列级读取合同、显式运维配置 CLI 与启动权限检查。允许读取当前授权/来源/索引及证据必要字段，只允许三张审计表必要写入；无原始消息、完整 ONES 凭据、完整文档修订、业务写入、DELETE 或角色继承/提权。审计协调器增加仅记录 readiness 选项，默认清理权限检查保持原行为。
- 使用已有 postgres:18 镜像创建独立 tmpfs 容器（无持久卷、512 MiB 内存上限、仅回环测试端口），只运行当前迁移及合成账号/审计。**18 项 PostgreSQL 专项**验证 schema readiness、每张表的明确读取列、审计写入、原始/凭据/业务写入拒绝、额外表/列权限与 schema CREATE 拒绝、收紧旧列权限。容器已停止并自动删除，tmpfs 合成数据随之清理；未连接正式数据库。
- 知识全量 **664 passed、3 skipped（170.55 秒）**，已包含上述 18 项 PostgreSQL 专项、SQLite 实际目录/检索 SQL 表面采集及 Compose 主/离线/在线兼容检查。只设置新的隔离权限测试 DSN；显式取消继承原导入/分块/向量端点，三项跳过仍是需要显式 PostgreSQL 或 PostgreSQL+Qdrant 的外部集成，不以权限测试冒充数据流水线验收。
- 独立扩展回归 **432 passed（55.90 秒）**：MCP 审计、RBAC/Principal/服务身份、Agent/Application/模型发布、ONES、Runtime/Worker/Session、schema/迁移、Secret/Compose 和测试分类。与知识套件为不同文件，合计 **1096 passed、3 skipped**；中间专项重跑不重复累计。
- Web 全量 **171 passed（16 个文件）**，其中知识资源 **11 项**覆盖完整操作链、修订冲突、只读/403/503、来源证明与 Job 核验/撤销、失败刷新保留输入、页签按需加载。TypeScript 构建、Vite production build、全前端 ESLint 通过；无浏览器实际部署验收。Vite 仍提示 native config 的 `__dirname` 兼容与大 chunk，构建成功，本轮未扩大为全站构建拆包改造。
- Ruff 全仓库通过，MyPy **482 source files** 通过；本轮 Python 格式、主/可选 Compose 合成配置、严格 OpenSpec、Markdown 链接与 diff 检查通过。镜像 COPY 白名单独立导入通过，但没有实际构建/重启整套知识服务。运行手册新增独立账号、受管凭据、维护顺序和无删卷回退步骤。
- **7.3、10.4、11.1–11.6 保持未完成**：数据库/DNS 阻塞等待与取消、完整隔离容器/重启、真实来源确认、正式部署批准、双用户 ONES/新 Job 和人工召回质量仍缺证据。没有读取真实 Secret/业务消息、真实 Provider/聊天/Embedding 请求、正式迁移、数据重编码、资源/角色发布、提交、推送或归档。

## 预算故障复现与 DNS 取消设计关卡（2026-09-19，后续核对）

- 继续任务 7.3 前，核对现有数据库池、Unit of Work、Knowledge/平台桥/ONES 预算及 HTTP 传输。数据库池和 SQL 尚不消费调用内剩余预算；只在阶段后检查不能提前终止已阻塞操作。平台桥在进入 RetrievalBudget 之前的鉴权数据库访问也须纳入入口预算。
- 合成 SQLite 单连接池测试：另一线程占住连接，池等待配置 300 ms，外层调用预算 50 ms；实际约 **301 ms** 才报 TimeoutError。只使用内存库和 `select 1`，线程、连接已回收；该实验不是 PostgreSQL 查询取消证据。
- 合成 DNS 测试：将本进程 resolver 替换为延迟 800 ms 后失败的函数，固定虚构域名，不发真实 DNS/HTTP 请求；`request_bytes` 配置 100 ms，总耗时约 **855 ms** 才报 TimeoutError。当前 `asyncio.run` 的 executor 清理等待尚未结束的 DNS 线程，网络协程取消不等于解析线程已退出。
- 需要确认的小范围实现取舍：数据库池等待/SQL/事务收尾仅在知识读取上下文中消费统一剩余预算，并主动取消超时操作、淘汰异常连接；DNS 保留操作系统解析语义，但只把域名解析放入可终止的短生命周期子进程，不把 JWT、查询或业务正文交给它，不迁移整个 MCP 为多进程。另需明确 deadline 后不再返回业务结果，清理有独立有界收尾，不能承诺所有系统调用在同一时刻消失。
- 依 apply 的设计关卡先请求用户确认，尚未实现此方案或改写已接受设计；任务仍 **35/43**。本轮只新增上述证据，不修改生产代码、依赖、真实配置或部署，不补勾 7.3/10.4。

## 删除 Web 来源手工核验表单（2026-09-19，用户确认）

- 按用户“删了”实施已讨论的简化范围。删除 `knowledge-source-panel.tsx` 及前端来源创建/核验/撤销命令，不再出现证明 SHA-256、RUNNING Job ID 或来源手工选择。知识资源详情只读继承所属数据集的唯一有效来源；缺失、撤销、变化或多义时不能保存草稿，错误指向导入侧处理。资源验证/发布和角色应用 KB 允许范围保留。
- 新增受限导入后 `confirm_knowledge_source` CLI 和应用用例，必须显式实例/Team、管理员、预期修订及确认/提交。系统生成声明摘要，不假称外部证明，不签发 JWT、不发 ONES 请求、不自动发布或授权。旧来源 API 保留已有调用兼容且不放宽原鉴权，新 Web 不再依赖该流程。
- 新增前向迁移 **138**，区分导入来源 `CONFIRMED` 与历史 `VERIFIED`，共同受唯一有效来源约束；PENDING 不自动升级。保留全部旧记录、外键引用、原始文档/分块/向量身份，来源换版立即撤销旧绑定。每次目录/检索仍校验 KB、本人实例/Team、工作项身份/项目和 ONES 可读权限。真实批次未代用户确认。
- 后端知识全量及相关迁移回归 **737 passed、21 skipped（210.43 秒）**；其中 18 项跳过的独立 PostgreSQL 权限测试随后显式执行，另 3 项仍缺导入/向量外部集成条件。确认状态已用于原可读性/目录/检索 fixture，使双权限和撤权回归实际覆盖新来源路径。Schema fact manifest 另 **7 passed**。
- 已有 postgres:18 镜像创建独立临时容器，仅回环随机端口、256 MiB tmpfs，无业务卷。**34 passed（26.03 秒）**覆盖 18 项权限、2 项 PostgreSQL fresh/137→138 历史升级，以及重复执行的 14 项来源确认专项（不与 737 重复累计）。升级验证保留 PENDING/VERIFIED 及外键引用，不改原数据，并验证新 CONFIRMED 可读且没有伪造核验 Job。修正旧 PostgreSQL fresh 检查遗漏 migration 137 新增表/列的断言：public 131 表，含 knowledge 的注释 146 表/1924 列；138 未新增表/列。容器已停止并自动删除，临时合成数据已清理。
- Web 全量 **176 passed（16 文件）**，知识页面 16 项包括表单移除、只读来源、CONFIRMED 保存、错误来源/多义/撤销拒绝、换版显式重载、刷新失败保留输入及原发布流程。TypeScript/Vite build、ESLint 通过，既有大 chunk/native config 警告不扩大处理。
- Ruff、知识模块及新增 CLI MyPy（45 文件）、严格 OpenSpec、Markdown 链接、diff 检查通过。主/离线 Compose quiet 校验通过，在线配置由合成 Compose 合同测试验证；实际环境缺独立知识 DSN 时仍按既有合同拒绝，不创建或读取真实凭据来补足配置。
- 本次任务 **13.1–13.3 完成，总进度 38/46**。7.3、10.4、11.1–11.6 保留未完成，11.1 按用户简化决策调整措辞但不补勾；未实施 DNS 子进程、正式迁移/重启、真实 ONES/模型调用、数据删除/重编码、资源发布/授权、提交、推送或归档。

## 取消配置阶段 ONES 地址/Team 来源确认（2026-09-19，用户明确确认）

- 用户确认边界：保存、验证、发布不再要求 ONES 地址或 Team 来源确认；本地数据/索引/依赖技术验证与运行时“角色 KB 授权＋当前用户 ONES 可读权限”保留。本节取代上一节的导入确认前置门禁，不将旧任务 11.1 补勾为已完成。
- 新草稿只提交 index_id 和 expected_revision；本地 source ID、完整文档修订/UUID/项目/内容与 KB 成员、索引/profile/collection 等进入版本 2 配置 hash。来源确认缺失、历史 PENDING/REVOKED/其他 Team 不阻止新草稿，不创建虚假 CONFIRMED 绑定；本地成员或索引变化仍拒绝。资源管理装配不再构造 ONES 来源核验器。
- 前向 migration 139 仅允许 retrieval_revision.binding_id 为空；保留旧来源、资源/验证/发布及外键，不改文档/分块/向量身份。旧配置须重新保存、技术验证和发布，不自动改写历史 hash 或发布状态。SQLite 重建表及 PostgreSQL ALTER 升级均保留已有历史发布、验证和关联关系，随后验证新无绑定版本可以发布。
- Web 删除来源确认门禁，仅展示导入记录与选择 READY 索引；旧版本提示重新保存验证发布。验证失败提示本地数据/Embedding/Qdrant，不再误导用户核验 ONES 权限或地址/Team。
- 运行时知识 MCP 使用本地 source_id 引用，不读取 source_binding 或要求 ONES 地址配置；收紧独立数据库权限合同。平台桥与 ones-mcp 保留本人唯一启用身份、当前默认 Team、固定部署实例、有效 Credential、实际详情 UUID/项目核对和返回前复核。新有效默认 Team 由真实 Provider 结果决定可读性，调用中身份变化仍拒绝，403/404 不返回候选引用。KB 授权、业务应用 Job、精确工具合同和无缓存正文边界不变。
- 后端知识/相关迁移/schema 回归 **750 passed、22 skipped（211.75 秒）**。最后装配解耦和中文身份错误修订另复测资源/API/ONES 可读性 **89 passed（42.70 秒，重复覆盖不累计）**，包含新增“资源装配不得调用来源核验器”用例。
- 使用已有 postgres:18 创建独立回环随机端口/tmpfs 临时容器，未挂业务卷。PostgreSQL fresh/显式 fresh、137→138→139 历史升级与最小权限专项 **22 passed（12.23 秒）**，其中 19 条是主回归跳过的权限用例；余下 3 项外部导入/分块/向量集成仍未验收。另修正显式 fresh 测试残留的 head 126 和旧表/列数断言，按实际迁移验证 head 139、注释 146 表/1924 列。临时容器已停止并自动删除。
- Web 全量 **177 passed（16 文件）**，其中知识页面 17 项，覆盖无来源绑定保存/验证/发布、历史绑定不控制新草稿、旧版本必须重新验证、技术故障不提示 ONES 来源确认及既有权限/冲突/刷新边界。TypeScript/Vite build、ESLint 通过；既有 native config 与大 chunk 警告未扩大处理。
- Ruff、MyPy（54 文件）、严格 OpenSpec、Markdown 链接、diff 检查通过；主/离线 Compose quiet 校验通过，在线 Compose 用合成配置合同回归。任务 14.1–14.3 完成，总进度 **41/48**；旧来源确认任务 11.1 经用户取消，不记为验收通过。
- 本轮不操作正式库、不读取真实凭据或缺陷正文、不调用真实 ONES/聊天/Embedding，不发布资源/角色/应用，不重编码、提交、推送或归档。正式本机迁移/部署已单独询问用户，当前尚未执行。任务 7.3、10.4、11.2–11.6 继续保留真实或完整运行验收缺口。

## 本机更新与配置依赖恢复（2026-09-19，用户继续批准部署）

- 本次授权仅包含迁移 139、相关服务/Web 更新及恢复既有 Embedding/Qdrant，不包括自动保存/发布知识资源、配置角色/应用、创建新凭据或在线 MCP 首次部署。
- 部署前数据库 head=138；Agent Job、文件处理、消息投递均无非终态任务。已有知识资源 revision=3、无草稿/发布，来源绑定为 0；索引 READY，5000 文档、8309 分块。Docker 数据盘有约 65 GB 可用空间。
- 发现主 API 与 PostgreSQL 均未连接知识网络；把 API 的网络追加从在线 MCP 扩展移至离线 `knowledge/compose.yml`，保留主部署无知识依赖、离线环境无新增凭据合同。PostgreSQL 只追加既有内部网络与别名，没有重建或重启；API 随定向更新接入网络。Compose 合成回归 **17 passed**，Ruff 与 quiet 配置检查通过。
- 相关后端镜像以源码 `d71370c63210`、build_id=`knowledge-local-publication-20260919`、平台 `linux/arm64` 构建。对 API、Worker、Processing Worker、Runtime、ONES/DingTalk/Tool MCP、File Service 和 Migrator 共 9 类新旧镜像比较 Python 包版本，全部无依赖变化。Web 定向重建；未升级模型镜像、Qdrant 或其他基础服务。
- 在确认无非终态任务后暂停入口及业务服务，只运行正式一次性 Migrator 的 `app.cli.migrate`，不运行账号/Agent/授权 bootstrap。结果 `head=139 baselined=0 applied=139`；binding_id 已允许空值。随后恢复对应主服务与原钉钉入口。
- 迁移前后 document=5000、document_revision=5000、document_chunk=8309、vector_index_item=8309；身份/修订/内容 hash、分块 embedding/evidence hash 与索引成员状态的聚合指纹完全一致。没有重导入、重分块、重编码、Qdrant 写入或删除卷。
- 本机 `/platform/resources` 与 API `/api/ready` 均 HTTP 200，API status=ready；所有已配置 healthcheck 的主服务均 healthy。新 Web 静态资产已包含“无需确认 ONES 地址或 Team”。API 容器内使用正式客户端只读检查 Embedding profile、Qdrant collection metadata 与精确点数 **8309** 通过，Qdrant collection 状态 green。
- 在只读数据库事务内调用正式资源配置解析器，真实 KB/索引配置通过且 requires_source_binding=false；资源仍 revision=3、无草稿/发布。检查未调用 ONES、聊天模型或 Embedding 编码接口。
- Chrome 浏览器连接不可用，因此未宣称已完成登录 Web 点击验收；用户需刷新后依次保存草稿、验证、显式发布。在线 Knowledge MCP、双用户 ONES、新 Job 和人工评测仍未验收，任务进度保持 **41/48**，11.3 只记录本次已完成部分。

## 平台管理与知识内容连接分离（2026-09-20，用户确认保留主密钥隔离）

- 平台逻辑 KB、资源/草稿/验证/发布、角色应用 KB grant、Job、审计继续使用平台连接；内容 PostgreSQL/Qdrant 按资源修订明确绑定。应用层新增实际使用的内容读取端口；SQL、连接、关闭和凭据装配留在基础设施，不增加通用 CRUD 或向量后端插件层。API 验证、平台可读性桥、ONES 内部核验、Knowledge MCP 都使用所选内容库，不回退平台旧数据。
- migration 140 增加可空 storage_config_json，解除 retrieval_revision.index_id 到平台 vector_index 的外键；外部索引由用例验证归属。旧值为 NULL，保留原部署连接、配置 hash、发布历史和数据身份。外部 KB 首次注册只创建平台逻辑身份，不复制正文。SQLite/PostgreSQL 的历史升级、外键保留与重复迁移均通过；目标内容连接不执行平台 Migrator 或 schema-head 校验。
- Web 新建/草稿可配置 PostgreSQL（固定 knowledge schema）、Qdrant 及凭据中心引用，读取目标内容目录后选择 KB/READY 索引。修改连接使旧目录失效，保存新草稿撤去旧验证但不改变发布版本。密码/Key 无明文表单；凭据中心列出知识资源版本依赖。未配置连接的旧流程和角色按应用允许列表不变，不恢复 ONES 地址/Team 确认。
- 平台固定 storage-connection 内部入口仅接受 KB/当前发布修订，必须同时通过知识服务 Service Principal、Knowledge JWT、RUNNING Job、当前 Tool/KB grant；返回前重验。拒绝 Cookie/Origin、其他服务、任意 Secret 引用、未发布/跨 KB 请求，审计先完成且只含安全 ID。MCP 不加载主密钥/Secret 仓储，单调用取得连接凭据、不缓存；合成加密 Secret 轮换立即使用新值，停用后失败关闭。服务 Token 精确 scope 增加固定连接操作，要求 API/MCP 配套更新并重新兑换。
- 外部 PostgreSQL 使用只读事务及单阶段连接/SQL/锁等待限制；拒绝超级用户、内容表所有者、管理/表级/列级写权限及 schema CREATE。Qdrant 不跟随重定向，凭据只作为请求头，不进入模型参数、普通日志、错误或资源草稿。连接异常稳定脱敏。此处不宣称任务 7.3 的全链路物理取消已完成。
- 在线 Compose 为 MCP 增加专用内容出网网络；Embedding/本地 Qdrant 保持原 internal 网络，没有新增宿主机端口、主密钥挂载或必需外部服务。目录与停用读取平台治理事实，不依赖外部内容服务可达。保持原项目、数据卷和离线 CLI 连接方式。
- 后端知识、相关迁移/schema 与服务身份主回归 **787 passed、23 skipped（220.62 秒）**。其中 20 项 PostgreSQL 最小权限测试已在独立容器显式运行并通过；其余 3 项需外部导入/分块/向量条件，未验收。另资源/API/平台 Secret 安全 **44 passed**；补充真实代码路径的合成 Secret 轮换/停用后，存储专项 **22 passed（7.42 秒）**。重复覆盖不合计为新增测试数。
- 使用已有 postgres:18 镜像创建独立回环随机端口、256 MiB tmpfs 容器，没有业务卷：权限专项 **20 passed**，完整 PostgreSQL migration 集成 **20 passed**，覆盖 fresh/并发/失败回滚与历史升级。按新列修正注释数量为 146 表/1925 列，并更新并发迁移测试残留的 head 126 列表至当前 140。临时容器已停止并自动删除，只有合成临时数据被清理。
- Web 全量 **179 passed（16 文件）**，含知识页面 19 项；TypeScript、Vite build、ESLint、Prettier 通过。Ruff、MyPy（60 文件）、严格 OpenSpec、Markdown 本地链接及 diff 检查通过。Compose 合成配置/隔离回归包含在后端主回归；Vite 既有 native config/大 chunk 提醒不在本次范围。
- 本次 **15.1–15.4 完成，总进度 45/52**。未执行正式迁移 140、业务服务更新、真实外部内容库接入、真实 ONES/聊天请求、数据搬迁/重编码、资源发布/授权或提交推送。7.3、10.4、11.2–11.6 仍未完成，不能以本次工程验收替代完整容器/双用户/新 Job/人工质量验收。

## 本机连接拆分部署（2026-09-20，用户继续批准）

- 本轮范围为 migration 140、既有业务服务/Web 配套更新及原 Embedding/Qdrant 恢复，不包含在线 MCP 首次部署、创建凭据/授权、数据迁移或资源发布。部署前平台 head=139，已有资源 revision=6 且已发布；Job、文件处理、投递和调度无非终态工作，两个待确认外部动作均已过期且不代为处理。Docker 数据盘约 126 GB，总可用约 63 GB。
- 镜像使用 source_revision=`b7a0dde-dirty`、build_id=`knowledge-storage-split-20260920`、platform=`linux/arm64` 构建，明确包含当前未提交改造。API、Agent Worker、Processing Worker、Python Runtime、File Service、Tool/ONES/DingTalk MCP 共 8 类新旧 Python 依赖全部一致（Python 3.12.13）。未升级 PostgreSQL、Qdrant、Embedding 或 Docling 镜像，也未重新下载模型。
- 暂停 API/钉钉入口，复核无执行中任务后停止对应消费者，正式一次性 Migrator 结果 `head=140 baselined=0 applied=140`。核对新增可空 storage_config_json、旧发布值仍为 NULL、平台本地 index_id 外键已解除。随后定向更新配套服务，保留项目、PostgreSQL/模型/向量卷与原数据库网络；API 重新带上离线知识网络。
- 迁移前后 document=5000、document_revision=5000、document_chunk=8309、vector_index_item=8309、retrieval_revision=1、retrieval_resource=1。文档修订/内容 hash、分块 embedding/evidence hash、向量成员身份/状态、资源版本/草稿/发布指针与配置 hash 的服务器端聚合摘要全部一致。没有读取业务正文、重导入、重编码或向量写入。
- 恢复钉钉入口时，`docker compose start dingtalk-runtime` 意外连带启动旧 Migrator 与 MinIO 初始化容器。旧 Migrator 在版本账本检查报 `Migration ledger contains versions unknown to this build` 并退出 1；命令链中后续账号/Agent/授权 bootstrap 未执行。MinIO 初始化重申既有私有桶配置，没有删除对象。改为 `docker start enterprise_agent-dingtalk-runtime-1` 后入口 healthy；正式迁移账本仍为上述 140，本轮未回滚 schema。旧失败 Migrator 为已退出的一次性容器，不作为当前服务健康证据；后续须使用新镜像和受控迁移命令。
- 最终本机 `/platform/resources` HTTP 200，Web 静态资产含“知识内容存储 / 为此知识库配置连接”；`/api/ready` HTTP 200、status=ready、schema_head=140，API/Runtime 返回上述构建身份。主服务现有 healthcheck 全部 healthy，钉钉入口与 Embedding 也 healthy。仅在只读事务内运行正式已发布配置解析器，真实现有 KB 配置可解析且无需重新发布；未调用 ONES 或模型。API 容器中正式客户端检查 Embedding profile、Qdrant collection metadata 和精确点数 **8309** 通过，Qdrant green，未调用编码接口。
- 在线扩展配置校验仍明确缺 `KNOWLEDGE_DATABASE_DSN`，平台没有 `knowledge_mcp_reader` 角色，没有在线 Knowledge MCP 容器；未用平台管理连接绕过独立账号合同。真实外部内容库、登录 Web 点击、新 Agent Job、双用户 ONES 和人工质量验收仍未完成。任务维持 **45/52**，11.3 仅记录本轮部署部分，不补勾；没有提交、推送或归档。

## 内容账号可具备管理或写权限（2026-09-20，用户修订）

- 用户明确希望后续管理知识内容，确认内容 PostgreSQL 可以使用管理员账号。本轮只取消外部内容账号的超级用户/所有者/写权限准入拒绝，不提前实现编辑、任意 SQL、建库或数据搬迁，不更改真实数据库角色；Knowledge MCP 平台治理连接的固定最小权限合同不变。
- 外部内容连接继续以固定 startup options 启用 default_transaction_read_only=on、5 秒连接/SQL 与 3 秒锁等待上限，并在交给用例前检查 transaction_read_only。只读状态缺失或未启用返回专用安全错误，不回退平台连接；凭据引用、TLS、schema、配置 hash 与旧发布不变。此项不是全链路 deadline 物理取消验收。
- Web 将“内容只读用户名”改为“内容数据库用户名”，明确允许管理员/读写/只读账号，但现有读取不修改内容。TLS 不自动关闭；本机 PostgreSQL 未启用 TLS 时仍需用户显式选择“不加密（仅受信内网）”。这次未实现连接失败的全面分类，不将通用错误文案当成 TLS 故障已修复。
- 后端知识 API/治理/存储/平台权限/检索/可读性桥/MCP 回归 **312 passed（69.62 秒）**。另初始存储与权限专项 **28 passed** 是重复覆盖，不累计；合成测试覆盖只读会话启用、未启用/缺失拒绝、连接关闭和 startup options 保留。
- 使用已有 postgres:18 创建独立回环随机端口、256 MiB tmpfs 容器，不挂业务卷；PostgreSQL 权限专项 **21 passed（8.66 秒）**。确认真实超级用户可读取内容目录，两次独立读取连接的 INSERT/UPDATE/DELETE/建表及事务内写入均被 PostgreSQL ReadOnlySqlTransaction 拒绝；原管理员连接仍可写。普通账号具备列级写权限不阻止内容读取，缺少必要 SELECT 仍拒绝；同一账号的超额权限作为平台治理连接仍被拒绝。首次测试的探针误用 name 字段，改为实际 display_name 后完整复测通过；临时容器已停止并自动删除，仅合成数据被清理。
- Web 全量 **179 passed（16 文件）**，包含管理员用户名与凭据引用提交、连接变更失效和既有发布边界；TypeScript/Vite build、ESLint、Prettier、Ruff、MyPy、严格 OpenSpec、Markdown 链接、离线 Compose quiet 与 diff 检查通过。既有 Vite 提示未扩大处理。
- 16.1–16.2 完成，总进度 **47/54**。用户随后批准只更新本机 API、ONES MCP 与 Web；部署结果另记，不自动保存草稿、发布知识资源或创建凭据。完整 MCP/真实 ONES/新 Job/质量与超时验收仍保留缺口。
- 用户批准后，构建并定向更新上述三个服务，source_revision=`b7a0dde-dirty`、build_id=`knowledge-content-admin-20260920`、platform=`linux/arm64`。新旧 API/ONES Python 依赖完全一致；更新前无非终态 Job，没有运行 Migrator、启动 Knowledge MCP、重启数据库或重跑 bootstrap。
- API 与 ONES MCP healthy，API `/api/ready` 返回 ready/head=140 及新构建身份；Web 静态资产包含新用户名和允许管理/读写账号说明。两个部署容器的 ManagedContentAccess 代码摘要与工作区一致，旧账号权限拒绝已移除，只读会话检查保留。服务器端文档/修订/分块/向量成员/资源与发布聚合摘要前后一致。未代替用户使用当前凭据执行登录 Web 连接测试；刷新后仍需将本机 TLS 显式改为匹配服务端的“不加密”，不宣称这条真实凭据已验证或完整 Agent 检索已验收。

## 120 秒统一截止与阻塞依赖取消（2026-09-20，用户确认）

- 用户确认实施此前待定的数据库/DNS 取消方案，并把单次知识调用上限从 60 秒改为 **120 秒**，仍服从当前 Job attempt 剩余时间、上游截止和父调用预算。代码、工具描述、design/delta/任务及运行手册同步；既有更短 Provider/登录配置不扩大，旧 Job/授权/Publication 不改写。
- MCP 及两个内部 HTTP 入口在首次鉴权前建立 I/O 截止。请求体读取、服务身份、池/锁等待、SQL/fetch、事务结束和 HTTP 使用剩余预算；跨跳只收紧。修复 ONES 正文回放伪造断开的问题，实际断开才触发取消；取消后不提前释放仍工作的 MCP 槽位。
- PostgreSQL 使用请求级服务器超时和驱动轮询，支持时最多 1 秒发送取消；不使用旧 libpq 的无界取消 fallback。异常连接淘汰、正常设置恢复，嵌套事务对已关闭连接不再回滚覆盖原始超时。SQLite 连接池/文件锁/长递归查询/事务结束有隔离回归，普通调用仍使用原连接池及等待策略。
- DNS 保留 OS getaddrinfo 与原 Host/TLS，只有域名解析进入短生命周期标准库子进程，空继承环境、输入只含域名/端口/解析参数，输出有界；不传 URL、JWT、查询、正文或数据库凭据。数值 IP 不建子进程；故障测试证明挂起解析被终止回收，无默认 executor DNS 线程拖延 asyncio.run 收尾。内容池建连使用同一解析，并能随临时池关闭取消。
- 合成故障预算使用约 80–150 ms，覆盖首个 Job/平台/ONES/MCP 鉴权池等待、慢 SQL、文件/数据库锁、过期/嵌套事务、网络滴流、DNS 挂起、PostgreSQL 握手不返回、真实断开和槽位复用；断言读取停止及下一次调用恢复，不等待真实 120 秒。独立 PostgreSQL 容器验证 pg_sleep 取消、后端连接更换、会话设置恢复、锁等待与不误提交；只使用合成数据和回环随机端口，无业务卷。
- 最终知识全量 + Database UoW/测试分类：**751 passed、3 skipped（200.67 秒）**，包括 **7 项独立 PostgreSQL 截止测试**和原 **21 项 PostgreSQL 权限测试**。3 项跳过仍是未配置导入/分块/向量的显式外部集成，未借用正式连接。独立 ONES/身份/审计扩展 **126 passed（9.04 秒）**，与前组文件不同，合计 **877 passed、3 skipped**；最后工具描述及 Host 保留专项 **69 passed（9.04 秒）** 是重复覆盖，不累计。
- 回归中修复 120 秒边界的旧 60 秒测试值，以及池淘汰后后台补建暂被快照计为借出的时序断言；测试先证明新连接能正常执行再验证回收。没有将这些失败归为无关。全仓 Ruff、MyPy **495 source files**、改动文件格式、严格 OpenSpec、Markdown 链接、离线 Compose quiet 与 diff 检查通过。
- 7.3 完成，总进度 **48/54**。本轮没有正式迁移、镜像构建/重启、凭据读取或配置、资源/角色/应用发布、真实 ONES/聊天/Embedding 请求、提交或推送。120 秒改动尚未部署；10.4、11.2–11.6 保持未完成。驱动取消、DNS/临时池回收与失败审计各有至多 1 秒有界收尾，不承诺所有系统调用在 deadline 同一时刻消失，也不把隔离故障通过当真实业务延迟达标。
- 临时容器 `ea-knowledge-deadline-test-20260920` 已停止并自动移除，两个临时数据库随 tmpfs 丢弃（仅可重建的合成数据）；已确认无同名残留容器，未清理正式数据或卷。

## 完整隔离容器链路（2026-09-20，任务 10.4）

- 新增显式 opt-in `backend/tests/test_knowledge_container_acceptance.py` 和独立测试 Compose/驱动。只继承 Docker 所需 PATH/HOME，Compose 使用 `/dev/null` 环境文件、随机测试项目、internal 网络，无宿主端口或业务卷。API/ONES MCP/Knowledge MCP 构建正式 target；pytest 与合成 Provider/Embedding 仅在额外测试镜像。PostgreSQL 18 使用 tmpfs，Qdrant v1.19.1 使用随机项目专属临时卷以验证重启数据保留；不改原离线或在线 Compose。
- 容器检查发现上一轮未部署的 DeadlineConnection 总向父 `_connect_gen` 传 timeout。本机 psycopg 3.3.4 接受此参数，而镜像实际安装 3.3.6 已将 timeout 移入 wait_conn，导致普通建连也失败。修复为仅转发实际驱动 connect 传来的 kwargs，不硬编码版本或放宽截止；新增两种签名回归。镜像使用实际依赖，不以本机成功替代容器验收。
- 单文档合成导入、分块和真实 Qdrant 索引完成；API 使用合成管理员正常登录，通过管理 HTTP 保存草稿、验证、发布，无 ONES 来源确认记录。配置 external 内容连接模式和平台 Secret 引用，指向同一临时 PostgreSQL 的管理员账号，当前读取仍只读；不宣称已验证物理异库部署。
- 生产 Knowledge MCP 使用固定最小权限角色启动，只挂公开 JWKS 与专用 bootstrap，无平台主密钥/私钥。通过真实 MCP initialize/tools/list/目录/检索，经 API 短期服务身份兑换、storage-connection 双身份入口、API 可读性桥、ONES 内部投影和合成 Provider HTTP 返回授权引用；再使用独立 ONES audience 的 Principal 经正式 ONES MCP 详情工具回源。没有 TestClient 或 MockTransport 替代这些运行链路，Job/角色/能力事实仍由合成 fixture 创建，不涉及 Worker/聊天模型。
- 验证 ONES audience 不能调用知识工具；KB 允许但 Provider 403 时不返回命中，Provider 500 时安全失败而非成功空集合；删除合成 KB grant 后旧 Token 被拒绝，恢复后可查；管理 HTTP 停用后拒绝，启用后恢复。API/ONES MCP/Knowledge MCP/Qdrant 重启后重新签发当前有效 Principal 并成功检索和详情回源。停掉全部知识/ONES组件后，独立数据库和未挂知识凭据的 API 普通登录、身份接口可用，知识内部入口不开放。
- 容器总场景 **1 passed（56.81 秒）**，其中专用临时数据库上的 I/O/DNS/握手/SQL/事务子回归 **20 passed**（13 个 I/O 与 7 个 PostgreSQL 用例）。本机知识全量 + UoW/测试分类 **725 passed、32 skipped（190.50 秒）**；32 项为未传 opt-in 的容器入口、21 项独立 PostgreSQL 权限、7 项 PostgreSQL 截止和 3 项外部流水线集成，未借正式连接补齐。额外 ONES/身份/审计扩展 **126 passed（8.26 秒）**。容器子回归与本机测试有重叠，不重复累计。
- 测试夹具的 PostgreSQL 表引用/时间类型、受管文件格式/权限、API 路径/Feature/审计保留配置和客户端生命周期已对齐正式合同后重跑通过；未绕过生产门禁。每次失败均执行隔离清理，不触碰正式容器。Ruff、相关 MyPy、严格 OpenSpec 与 diff 检查通过，最终检查另见本轮交付。
- 10.4 完成，进度 **49/54**；11.2–11.6 仍未完成。未部署这次兼容修复及前一轮 120 秒代码到正式服务，未读取或修改真实凭据、授权、Publication 或数据。真实 ONES 双用户、新 Job/聊天模型、BGE-M3 及人工效果验收均不能由本次合成容器结果代替；没有提交、推送或归档。
