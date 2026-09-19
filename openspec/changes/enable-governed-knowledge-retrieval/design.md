## Context

本设计对应 [proposal.md](proposal.md)，是在已有本地文本与向量索引之上增加受治理读取，不是重建存储流水线。已确认的实现前提是 5000 个文档、8309 个块完成本地索引验收；这不证明业务召回率、来源归属或用户读取权限。当前 canonical 尚未同步两个前置知识 change，实施前须重新核对基线和代码。

当前 `knowledge` 模块提供导入、分块、索引和运维检索；`knowledge.source` 的离线身份、知识库的 `storage_only` 状态参与重放校验。Qdrant 点保存内部文档/块和 profile/hash，不含 ONES 权限。RBAC 已有业务授权、精确 Tool Snapshot 和当前权限复核，但没有知识库范围。模型已有部署白名单内的 Anthropic-compatible 网关路径，不等于已部署不向外部转发的聊天模型。

当前决策：命中同时满足角色知识库授权和本人当前 ONES 可读权限；Embedding 保持本地/内网，授权后的检索引用和 ONES 正文允许交给 Agent 既有聊天模型。

## Goals / Non-Goals

**目标：**

- 先建立可复现的人工相关性评测，再提供两个固定只读 MCP 工具及 Web 资源/角色配置。
- 让 Agent 获得经授权的 ONES 工作项引用，再经现有 ONES MCP 本人身份读取当前详情。
- 保持现有导入、分块、索引身份与重放能力；本地数据不一致或运行时权限不明时失败关闭。
- 区分代码与合成验收、真实来源/模型验收和真实业务效果，不用文档勾选替代运行证据。

**非目标：**

在线采集、增量索引、附件/OCR、工单/需求导入、运维内容解析、混合召回与重排、通用向量后端、任意数据连接配置、跨 Team 自动切换、通用服务委派框架。本轮允许管理多个明确知识库身份，但首个可发布的内容类型是 ONES 工作项；不能把尚无正文权限合同的运维知识库标成可用。

## Decisions

### 1. 资源配置只依赖本地数据与索引，不要求 ONES 来源确认

2026-09-19 用户再次确认：保存、验证和发布不再要求提供或确认 ONES 地址/实例/Team。来源身份由已入库文档派生，仅代表本地导入记录，不声明外部来源已获确认。配置验证只检查本地数据完整性、KB 成员、READY 索引/profile/hash、内部 Embedding 和 Qdrant 兼容性及点数。

继续使用同一 PostgreSQL 的 knowledge schema。检索资源版本通过配置 hash 固定本地 source ID、文档修订/UUID/项目/内容摘要、索引和 profile；新版本 binding_id 为空，不生成占位或伪造的来源确认。每个资源仍对应一个 KB，首版成员须属于一个明确本地来源；不接收浏览器自报来源 ID 或连接参数。

新增迁移 139 仅放宽 retrieval_revision.binding_id 的非空约束，保留来源绑定、旧资源/验证/发布和外键。旧配置的 hash 与证据不改写，旧版本需管理员重新保存草稿、验证并发布后才按新规则读取；不自动复用旧验证。source 的 offline_unverified、KB 的 storage_only、document/revision/chunk/point ID 和现有内容/profile/hash 保持原导入重放合同。

历史来源确认 CLI/API 留存兼容，不再是新资源流程或运行时的前提；撤销旧来源确认不影响新规则资源，停用检索应使用资源状态或撤销 KB 授权。真正的数据成员、修订或项目变化仍使配置失效。运行时的 ONES 地址由既有部署固定，Team 来自本人唯一启用身份，逐项调用当前本人详情合同；缺失/失效身份或不可读候选仍失败关闭，不用共享账号，不返回离线正文。

### 2. 知识库是独立业务范围，沿用现有 RBAC 和资源生命周期

角色业务授权新增明确的 `knowledge_base_id` 范围关系，归属现有角色业务访问记录及其 revision。应用访问、工具与知识库范围必须在同一条允许的角色访问记录中满足，不能把角色 A 的 Tool 与角色 B 的知识库拼接。成员/角色停用、委派上限、预览和原子保存沿用现有机制。知识库只配置允许列表，不新增显式拒绝字段、规则或优先级；未配置表示此角色在此应用中不授予该 KB，不否决其他有效角色在同一应用内的完整允许记录。一个角色关联 app1、app2 时，app1 已授予的 KB 不可在未获授权的 app2 中使用。此为用户 2026-09-19 明确决定，对 canonical 通用“显式拒绝”措辞的知识库范围例外通过本 change 的 identity-access delta 表达，不扩大为其他领域改造。首版仅允许具有有效业务应用及其 Publication 的 Job 使用知识工具；直接 Agent 在任何候选或模型访问前拒绝，即使拥有项目 use grant 或其他应用的 KB grant 也不能替代。不得新增直接 Agent ACL 或虚构应用 ID；Agent Publication 仍可作为业务应用复用的能力定义，不等于允许直接执行。

角色授予逻辑知识库身份，不授予物理 Resource Revision、Qdrant collection 或 environment/placement。选择“当前全部知识库”在保存时展开明确 ID，不包含未来新增知识库。授权变更进入现有 authorization hash 和实时复核，不另建旁路 ACL。

Web 在“工具资源”增加知识库类型入口，表单选择已存在 KB 及兼容 READY 索引，来源名称仅从已入库数据只读展示，不要求 ONES 地址、Team 或来源确认，统一执行 DRAFT → VERIFIED → PUBLISHED、停用/归档；不要求虚构环境，不接收任意 PostgreSQL/Qdrant/Embedding URL 或凭据。首版复用部署固定连接，页面只显示安全状态和关联 ID。角色页面只在各业务应用下引用明确 KB ID，通过勾选/取消勾选管理允许范围，不创建、复制或编辑知识资源配置。

调用时解析该知识库当前唯一启用的 Published Revision，并在单次调用中固定资源/本地数据/索引版本，审计记录实际版本；返回前重验授权、来源和发布状态。若本次期间版本变化则拒绝并要求重试，不拼接新旧结果。新的调用可采用显式发布的新版本，不冻结全部知识资源到 Agent Publication，也不自动切换到未发布或旧索引作为 fallback。Tool 的精确 Job Snapshot 规则保持不变。

**取舍：** 不复用数据库环境授权，也不要求每次索引发布都重新发布 Agent。资源版本一致性归单次调用，工具能力一致性归 Publication/Job，避免混淆两个生命周期。

### 3. 固定两个只读工具，首版返回引用而非缓存正文

代码固定注册 `knowledge-mcp`，使用独立 audience 的 Business Principal JWT 和标准 Streamable HTTP。接入现有 Manifest、Tool 目录、Agent/Application 发布子集、Runtime 固定 Server policy、精确 Snapshot 与当前授权复核，不接受模型覆盖执行地址或认证方式。

按用户要求，服务代码统一位于 `services/knowledge_mcp_server/`，与 ONES、钉钉 MCP 同级，不新增单数 service 目录。该目录仅拥有 MCP/ASGI 传输、身份上下文适配、有界执行、安全 MCP 审计和狭窄依赖装配；目录、召回、权限与引用校验继续复用 knowledge 四层模块。启动不构造平台全量 Container，不加载平台主密钥、签名私钥、模型 Key 或 ONES 凭据仓储。

入口固定 32 KiB 请求与 256 KiB 工具结果；4 个真实在途工作槽位覆盖目录、检索及健康探测，不增加无界排队。ASGI 观察断开并传递取消信号，嵌套预算继承取消与截止，超时线程实际退出前不释放槽位。MCP 根审计只存工具名、安全版本/计数/错误码与既有审计关联 ID，不保存 query、cursor、命中 UUID 或正文。该实现不等于阻塞数据库/DNS 的物理取消已完成；任务 7.3 保留这部分验收。

在线部署使用 `backend/Dockerfile` 的独立 knowledge-mcp target 和可选 `knowledge/mcp.compose.yml`，在根文件与离线 `knowledge/compose.yml` 之后叠加。保留原模型/向量卷、项目名和仅离线环境的无新增凭据合同。MCP 不发布宿主机端口，仅接两个内部网络；API 在离线扩展中即追加知识网络，用于发布前的固定依赖验证，无需先配置在线 MCP 凭据。服务仅挂载公开 JWKS 和自己的 bootstrap，不挂载平台主密钥、签名私钥或 ONES 凭据；知识 MCP 不再需要 ONES 实例/地址配置，实际 ONES 目标与本人身份校验归平台桥和 ones-mcp。

数据库仍共用原库，单独使用固定角色 `knowledge_mcp_reader`。显式运维 CLI 按当前调用的明确列授予 SELECT，只给 audit_event、agent_tool_call、mcp_operation_audit 必要审计写入，无业务写入/DELETE；启动检查角色、成员关系、schema 与表/列权限，拒绝管理员 DSN 或超额授权。列合同变化必须重审，不借表级 SELECT 自动扩权，不在启动时创建角色或变更平台 PUBLIC 权限。隔离 PostgreSQL 权限验证和镜像 COPY 导入验证不替代任务 10.4 的完整容器运行验收。

| Tool | 输入 | 输出边界 |
| --- | --- | --- |
| `knowledge_list_bases` | 可选不透明 cursor；每页默认且最多 50 项 | 当前获授权、本地数据/索引兼容、已发布可检索 KB 的 id/code/管理名称及安全状态；无文档数量、样本或业务标题 |
| `knowledge_search` | 一个明确 knowledge_base_id、query（1–2000 字符）、top_k（默认 10，1–20） | 按文档去重的已授权 ONES 引用、有限证据位置、资源/索引版本及有界 partial 状态 |

知识库目录自身和检索 Tool 都必须在当前 Job 获准。目录采用稳定 ID 的 keyset cursor，绑定 Job/用户/应用/Tool Snapshot/授权摘要/当前可见资源摘要；51 项可续页，授权或资源变化使 cursor stale，不静默截断。目录表示可尝试检索的知识库，不证明用户能读库内全部文档；不以探测一个缺陷来推断全库权限。

首版目录实例以进程内临时 Fernet 密钥保护 cursor，300 秒到期，不新建共享密钥、游标表或长期授权票据。服务重启或请求落到另一实例时旧 cursor 返回 invalid，调用者从第一页重新发现；首版部署不得将其描述为跨副本连续分页。每一页重新求值完整可见集合及本人来源，返回前再次比较，页外资源变更同样使旧游标失效。

检索复用现有 dense query 内核，先限制明确授权的 KB 和发布索引，再以 PostgreSQL 当前收录/版本复核候选；按文档去重后进行 ONES 可读性检查。Qdrant 最多读取 200 个候选点，不允许客户端控制 collection、filter、candidate_limit、任意项目/Team 或原始查询表达式。分批扩候选须对 point/document 去重并有严格上限，不修改现有点 payload。

在线编排固定一次读取最多 200 点，再从同一去重池按每批最多 10 个文档补足可读项，不通过重复扩大 top-N 累计读取超过上限。当前版本/收录、点身份和证据聚合与离线 CLI 共用纯验证函数；离线 CLI 原有查询策略及默认重试保持不变。每个上游阶段及返回前重新核验当前授权、身份、固定资源与运行预算；失败不缓存可读结果，不把 Provider 故障降级为不可读。

单次最多检查 50 个不同 ONES 工作项、并发最多 4；全调用 deadline 不超过 60 秒且服从 Job 剩余预算，单个 Provider 请求沿用较小超时。401 刷新仍遵守既有一次刷新合同，不增加第二条重试循环。限额由代码定义并贯穿服务、schema 描述、测试与安全诊断，不能伪装成全量查询。若只因固定候选/时间预算不足而未补足 top_k，返回已确认可读的命中及 `partial=true`、通用 `bounded_search` 原因；不提供被拒绝的 ID、数量、分数或项目分布。

内部 HTTP 以 `X-Knowledge-Deadline-Ms` 传递 UTC 毫秒截止时间，各跳取传入值、本地 60 秒、当前 Job attempt 剩余预算的最小值，再转成本地单调时钟。该 Header 只能收紧预算，不授予权限，不进入模型 Tool 参数或 JWT scope；重复/非法/过期值拒绝，缺省仍受本地 Job 限制。部署需保持各服务时钟同步；调用方自身仍独立执行剩余预算。身份刷新锁等待、兑换、ONES 登录及 Provider 请求使用同一调用内预算；超时不使正常 ONES 凭据失效。知识调用的生产 HTTP 使用可取消网络协程和整次请求 timeout，禁止代理、重定向及压缩响应，原客户端继续拥有目标校验、认证、业务解析和唯一一次 401 刷新。

每个命中只返回已验证的 task UUID、经验证的工作项编号（可用时）、本地 source_id 引用、document/revision/index/块引用、有限分数与证据位置（每文档最多 3 条）。不返回离线标题、摘要、正文、附件地址、查询向量或内部连接信息。公开结果中的引用只证明此次允许定位，不是长期授权票据。

**取舍：** 不先返回缓存摘要再让 ONES 拒绝；暂不引入混合召回或重排。纯引用降低旧版本/字段权限泄漏风险，代价是回答需要后续详情查询，首版延迟应按完整链路评测。

### 4. 通过固定只读桥复用 ONES 本人权限，不建立第二套 ONES 客户端

当前没有可直接假设存在的 ONES 批量权限 API。新增的是内部有界可读性编排，不是第三个模型工具，不假设 HTTP 200、项目列表可见或本地 grant 等于工作项可读。

```text
Runtime → knowledge-mcp：独立 Knowledge Principal + 检索请求
  → PostgreSQL / 本地 Embedding / Qdrant：受限候选与当前版本核对
  → 平台固定可读性桥：固定服务身份 + 原 Knowledge Principal + 候选引用
    → 平台核对同一 RUNNING Job、当前 KB/Tool grant 与来源；从库内解析 UUID
    → 平台签发并仅在内存使用该 Job 的 ONES Principal
    → ones-mcp 内部只读投影入口：验证 ONES Principal 和详情 Tool 合同
      → 复用本人身份、Credential、默认 Team、固定详情 Operation
      → 只返回可读 UUID/项目归属核验结果，不返回正文
  → knowledge-mcp：返回前复核当前授权，投影允许的引用
Runtime → ones-mcp：Agent 用现有详情工具读取当前正文，再由 Agent 已配置的聊天模型回答
```

平台桥仅支持 `knowledge_search` 的候选可读性检查，候选输入为本次 KB/索引内的内部引用；平台重新解析和验证成员关系，不接受任意 URL、actor、Team、server、scope、operation 或 Provider 凭据。它需要固定 `knowledge-mcp` 服务身份及有效 Knowledge Principal 两重证明；服务身份只授权访问此内部操作，不能赋予用户业务权限。服务凭据沿用受管文件/短期 Service Principal 机制，只有启用知识服务才配置，不能让未部署知识组件的环境必须配置新 Secret。

平台固定入口为 `/api/internal/knowledge/work-item-readability`：`Authorization` 承载短期 Service Principal（固定 `sub/azp=knowledge-mcp`、`aud=knowledge-readability-bridge`、唯一 scope `internal:knowledge:work-item:readability`），`X-Knowledge-Principal` 承载原 Knowledge Business Principal。可选 `KNOWLEDGE_BOOTSTRAP_TOKEN_FILE` 只在启用知识组件时配置，沿用现有受管文件约束、凭据隔离和不超过 300 秒 TTL；未配置不装配平台桥。请求两端共用严格候选合同，8 KiB body 足够容纳最多 50 个合法长 ID；平台只接收最多 64 KiB 的固定响应投影，不跟随重定向、不读取代理环境配置、不缓存允许结果。

平台仍按既有完整 scope 合同签发 ONES Principal，不放宽现有“scope 恰好等于该 Server 冻结且获授权完整集合”规则；该 Token 不返回 knowledge-mcp、不暴露模型或日志。平台桥只调用固定的内部可读性入口，不能调用 ONES mutation 或成为通用 MCP 代理。ONES 内部入口使用自己的 audience、当前详情 Tool Snapshot 与本人 Credential；只读投影复用既有详情查询/解析/刷新代码，禁止复制另一套登录和 Provider Client。新增内部入口单独纳入认证、中间件、请求大小、限流和审计测试，不假设 `/mcp` 中间件自动保护其他路径。

发布 ONES 知识检索前，Agent/Application 有效工具子集必须同时包含 `knowledge_search` 和 `ones_get_work_item_detail`；运行时再次检查当前 grant。知识库列表不代替此校验。ONES 目标沿用固定部署，Team 取当前唯一启用 ONES 身份的默认 Team，不再与知识资源预填来源比较，不让模型切换 Team。每个可读投影必须解析并核对 UUID、Team 上下文和导入的 source_project_id；工作项迁移项目或身份不一致时过滤，不把旧文本直接暴露。

明确拒绝/不存在的工作项不返回；凭据失效、超时、限流、Provider 5xx、格式错误不能当作“没有相关缺陷”。这类依赖故障使调用返回稳定中文安全错误且不附候选内容；预算截断与上游故障分别测试。正向可读性事实仅在一次调用内去重使用，不跨调用缓存；回源详情再次走本人当前权限，撤权后不以缓存文本兜底。

**取舍：** 增加一个严格固定的内部桥，而不转交跨 audience Token、不向知识服务分发签名私钥或 ONES 凭据、不新增任意代调用框架。内部桥多一次跳转，但保留现有 JWT 精确校验和 ONES 认证边界。

### 5. 本地向量化与既有聊天模型分开管理

2026-09-19 用户明确接受授权后的检索结果和 ONES 正文进入现有聊天模型，包括外部模型。该决策取代早期“全文链路不外发”的要求；Embedding 继续固定本地/内网。不能把 Embedding 本地等同于聊天阶段不外发，也不能因聊天获准就扩大数据读取权限。

撤去为旧要求新增的 INTERNAL_MODEL_POLICY_FILE、部署认可状态、internal_only Publication/运行门禁和 SDK 特殊覆盖，不实现 Session/摘要/产物标记继承，也不为此扩展 Runtime 协议。保留既有模型连接、冻结版本、规范化别名映射、Anthropic-compatible 合同、Runtime 请求签名和最小数据库权限；Runtime 不新增读取 Job/Session/RBAC 的能力。历史 Publication 不重写，新增发布不再写入旧数据边界标记。

保留知识检索必须同时发布 ONES 详情 Tool 的依赖。目录和检索工具成套选择，Agent Envelope 与 Application 子集在发布前校验三者，和既有 Job 门禁对齐；不自动补选或授权，避免允许发布后才因缺失必需工具而启动失败。Worker 在解析模型/历史摘要前复核当前知识工具和详情授权，检索返回前仍执行完整 KB + 本人 ONES 双重校验。允许外部聊天不是授权旁路。通用诊断只记录安全 ID、版本、耗时和错误码，不增加业务 query/向量/正文/凭据；受控运行记录保持原访问与保留合同。

**取舍：** 复用已有可用模型链路，不另建模型认可制度或跨会话数据标记系统。真实 Agent 验收仍需证明现有模型能完成授权后的引用回源与分析，但不再以“不向外部模型转发”作为门槛。

### 6. 人工评测先出基线，再比较治理后的端到端效果

建立受保护的本地评测集和可重放 runner。样本包含 query_id、query、KB/source identity、人工标注的相关 task/document ID、是否无答案、问法分类及标注来源；不由模型或相似度阈值生成“正确答案”。真实文本/完整标签留在受限目录，排除 Git 和通用日志；仓库只放合成样本、schema 与脱敏汇总。

首批目标约 50 条，覆盖口语改写、错误码/业务术语、长描述要点、跨项目近似项、无答案；权限专项另覆盖两位可读范围不同用户、撤权、来源不匹配及 Provider 异常。原文自查询只作为管线探针，不混入业务效果指标。集合必须有人工确认和固定版本；离线评测不宣称用户可读性；端到端可读性仍须真实 ONES 验收。

记录评测集 hash、KB/来源/索引/profile/语料版本、检索参数、代码版本和运行环境。文档级 Recall@10 = top10 命中的人工相关文档数 / 该问题全部已标注相关文档数；MRR@10 以首个相关命中的倒数排序计算，未命中记零。无答案问题单列误报率，不混进相关集为空的召回率分母。人工标签不穷尽时标为“标注集内召回”，不能声称绝对召回率。

分别报告离线 dense 基线与真实用户双权限后的端到端结果；后者相关集合按该用户当前可读文档计算，并记录不含业务内容的授权观察版本/时间。报告 p50/p95、失败分类和有界截断率，端到端延迟含权限检查及必要详情访问，纯检索耗时单列。先报告实测基线再由用户确认质量/时延准入目标，不编造已达标阈值；不能通过放宽权限换取更高 Recall。

**取舍：** 不在首版堆检索算法；先区分分块/Embedding/候选上限问题、权限过滤、来源不一致和 Provider 故障，避免盲调 top_k 或把授权错误当算法问题。

### 7. Knowledge 四层分离且保持已有数据合同

- api：HTTP 参数、身份/CSRF、调用与安全响应，不写 SQL、不实例化网络客户端。
- application：导入/分块/索引/评测与来源/资源/目录/检索用例；事务时机、授权复核、预算和错误语义留在用例，依赖 ports 中当前实际使用的仓储及 Embedding/Qdrant/身份/可读性端口。
- domain：规范化、分块、输入不变量、稳定文档/向量点身份、payload、评测合同与 Tool 依赖；不依赖 API、应用编排、数据库、HTTP 或文件系统。
- infrastructure：具体 SQL/锁/事务、受限文件读取、固定 Embedding profile、HTTP 与跨模块身份适配器；静态 composition 装配真实依赖，CLI 和 bootstrap 显式接线。

不保留旧平铺文件作为兼容转发层；仓库内调用者、测试和镜像 COPY 同步迁移。没有通用 CRUD 基类、插件注册表、事件总线或新数据层。镜像仍按组件白名单打包，Embedding 不因此包含后端业务模块。

稳定 ID 算法、清洗/分块 hash、Embedding profile/锁文件、point payload、checkpoint/事务回滚、CLI 输出/重放语义保持不变；评测实现 code_hash 随实际代码变化如实更新。仅改变代码组织，不触发迁移、重导入、分块或编码。以架构依赖测试和原有行为回归共同验收，不能用目录存在代替分层。

## Risks / Trade-offs

- [离线批次来源未核实] → 不再索取外部来源确认；发布验证本地批次/索引一致性，运行时逐项 ONES 校验 UUID/项目与可读性且仅返回引用；不更改历史 source 身份来掩盖缺口。
- [逐工作项 ONES 校验增加延迟和限流风险] → 去重、最多 50 个工作项/4 并发/60 秒总 deadline，真实测量后再提出独立优化；不跨调用缓存允许结果。
- [授权后过滤使 top_k 不满] → 有界扩候选、保留 partial；不宣称全库穷尽，不返回被过滤数量帮助探测。
- [ONES 项目/字段权限或工作项归属变化] → 当前本人详情可读性和身份核对，首版不返回离线正文；详情读取时再次验证。
- [误把本地 Embedding 当全文不外发] → 明确聊天阶段可外发授权内容；索引/查询向量化仍仅走内部服务，不增加日志或遥测正文。
- [并行迁移和前置规范同步漂移] → apply 前核对 catalog/head、重新验证 delta；只新增迁移，知识内容和索引零重键，存量 Job 不自动扩 Tool。
- [技术验证被误记成上线] → evidence 分层记录合成、容器、真实 ONES、已配置聊天模型和人工评测；缺任一门槛不勾对应任务。

## Migration Plan

1. 先确认本设计和任务；本提案不执行迁移、发布或业务请求。核对前置知识 change 的同步结果并按当前 canonical 重验 delta，归档按用户选择单独处理。
2. 实现本地评测格式/runner 与合成样本，核对现有索引读取不变；人工标注可以并行准备，不能伪造以完成任务。
3. 添加来源绑定、检索资源/版本和角色 KB 范围的前向迁移，更新当前双引擎 schema catalog、注释及约束测试；不修改历史 migration，不改写已有文档/分块/向量。新增数据默认未核验、未发布、无角色授权。
4. 实现权限桥、固定 MCP 合同、既有模型复用与知识工具依赖、Web 配置与完整合成回归。新测试登记 `backend/tests/test_suite_tiers.toml`；知识组件继续位于可选 knowledge Compose，未启用环境不必启动 Qdrant/Embedding/knowledge-mcp 或配置其凭据。
5. 用户批准正式部署后，先检查非终态任务、迁移器/服务镜像与 schema 兼容，再走正式 Migrator，验证 readiness；单独启用知识服务。知识资源、角色授权、Agent/Application 新 Publication 都需显式配置，不沿用旧 Job 验证新增能力。
6. 在验证本地资源并确认既有聊天模型配置后，用测试用户和新 Job 验证完整双权限链、详情回源、撤权、服务重启、异常与模型版本冻结，再运行人工评测并确认准入目标。
7. 回退时停用知识检索资源/新工具发布与可选服务，保留迁移及原始/向量数据，恢复兼容的 Publication；不得删除索引或回滚历史 DDL。会话和运行记录沿用现有访问/保留合同，不引入知识专用内网标记。

## Open Questions

以下是实施或真实验收所需输入，不是可默认放宽的设计选项：

- **已解决**：用户不再要求强制内网聊天，因此不实施为 internal_only 升级 Runtime 协议的建议；签名请求和 Runtime 最小数据库权限保持不变。

- **已解决**：用户取消配置阶段 ONES 地址/Team 来源确认；本地资源技术验证与运行时 KB＋本人 ONES 双重校验保留。
- 现有已配置聊天模型的真实知识 Job 链路何时验收？本次仅作本地合成验证，不真实发送业务正文。
- 谁完成首批约 50 条人工标注及复核？取得基线后，用户接受的 Recall@10、MRR@10 和端到端 p95 目标是什么？未确定前不标记效果达标。
- 已完成的清洗分块/向量索引 change 是否同步并归档，归档哪些对象？本 change 不代替用户的归档选择，也不包含分页 change。
