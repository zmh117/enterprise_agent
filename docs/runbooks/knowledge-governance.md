# 知识治理管理与排障

本页描述当前资源管理、角色应用 KB 范围、Job 与平台知识库授权、目录检索与文档重排。采集、服务启停和任务进度见[知识库网页运维](../../knowledge/OPERATIONS.md)。服务启动与内容同步不会自动授权；普通内容更新不重新发布知识资源。本文的代码合同与日期化验收证据分别表述，不把容器健康当作真实用户检索验收。

## 实现与主规格差异

本次 `enable-offline-knowledge-retrieval` 已将主规格明确统一为 **360 秒**上限，并与当前 Job 剩余时间、上游截止取较小值。`KNOWLEDGE_ACCESS_MODE` 默认 online，检索须同时通过平台 KB 授权与本人 ONES 当前可读性；显式 offline 才仅按 KB 授权读取，不要求 ONES。两种模式均返回入库片段，线上故障不自动降级；配置方法见[部署说明](../../knowledge/README.md#在线与离线内容检索配置)。结果携带来源更新时间与入库时间，不表示来源最新状态。

Runtime 为知识 MCP 显式设置逐服务 `timeout`，避免 SDK 默认 60 秒首响应截止提前取消有效长检索。Job 总截止、取消和调用内 Principal 续期继续生效。部署与真实验收结果见当前 change 的 evidence，不能从代码合同推断已通过。

## 数据库和部署边界

知识库故障命中后的 ONES 核验：Agent 对用于结论的相关工单读取 `ones_get_work_item_detail` 和 `ones_list_work_item_messages`，再阅读消息结果文件。消息工具仅接受 `work_item_uuid`，内部依据 [ONES 官方消息协议](https://docs.ones.cn/project/open-api-doc/project/message.html) 使用 count/max 自动读取历史页，最多 1000 条、50 页、90 秒及 8 MiB 规范化结果；短页不表示结束，以 has_next 为准。

消息摘要中的 `messages_complete` 表示是否读到末页，`text_truncated_count` 表示被截断的正文条数，`complete` 同时考虑两者；`total_known=false` 时 total 只是已收集数。即便 complete=true，也不能证明模型已读完文件或附件。详情的 description_truncated/related_items_truncated 分别标记描述及关联摘要截断。回复应说明已核验工单、评论时间范围及未读部分；权限/服务失败时保留历史线索并说明最新来源未核验。

该变更使用 Prompt v19 并改变消息工具输入合同，无数据库迁移；需要同步构建 API、Worker/Dispatcher、所有使用冻结工具合同的 MCP 和两个 Runtime，更新 Skill 后发布 Agent 与对应应用，再检查 Prompt MATCH。更新容器不会替换已有 Job 的冻结合同。offline 仅表示知识库可离线检索，后续 ONES 核验仍需要本人身份与工具授权。

2026-09-20 新增内容连接拆分：平台保留逻辑 KB、授权/发布、Job 和审计；内容 PostgreSQL 的 `knowledge` schema 与 Qdrant 可在 Web 配置。migration 140 增加仅含连接配置/凭据引用的字段并解除平台本地索引外键；旧发布原 hash 和数据保持不变。独立内容库不要求平台身份/Job/迁移账本，也不会自动建立或搬迁。部署及账号要求见[内容存储配置](../../knowledge/README.md#web-配置独立内容存储)。本机已部署平台侧、Web 和在线 Knowledge MCP；真实外部内容库接入仍待验收。用户确认内容账号可以具备管理/写权限，现有外部读取连接仍强制只读事务；配套代码已部署，不代表新增内容编辑能力。

本机已于同日定向更新 API、ONES MCP 和 Web 至 `knowledge-content-admin-20260920`，账号策略已生效；当时 schema 为 140，资源 revision=6 与发布指针未改。刷新 Web 后可使用管理员用户名，但本机未启用 PostgreSQL TLS 时仍须显式选择“不加密（仅受信内网）”。未代用户测试所选真实凭据、保存草稿或发布。

治理表通过平台前向迁移 `137_expand_knowledge_retrieval_governance.sql` 加入现有数据库的 `knowledge` schema；角色 KB 关系 `rbac_role_application_knowledge_base` 留在现有 RBAC 所属的 public schema，以外键引用逻辑 KB。不新建数据库，也不改变现有 source/knowledge_base 的离线存储状态、文档、分块或向量身份。迁移不创建真实来源绑定、发布或角色授权。`138_expand_knowledge_source_confirmation.sql` 新增 CONFIRMED 状态，保留所有旧绑定及引用，不把 PENDING 自动升级；其含义是历史导入声明，不是 Provider 权限证明。`139_relax_knowledge_resource_source_binding.sql` 允许新资源版本不关联来源绑定，保留全部历史和外键；旧资源版本必须重新保存、验证、发布，不能复用旧验证或直接改 hash。

API/Worker/ONES 镜像更新须满足正式 Migrator 和平台 schema readiness 门禁。2026-09-20 经用户批准，本机已从 139 升级至 140、更新相关服务和 Web、恢复 Embedding/Qdrant；后续部署 `knowledge-online-20260920` 无新迁移，已启用在线 MCP、独立读取角色和受管服务身份，更新 API/ONES/Agent Worker/Runtime。5000 文档、8309 分块/向量点及已有知识资源 revision=6 的发布记录保持不变；未保存草稿、发布或修改业务授权。上述为 2026-09-20 的历史快照；后续维护按[当前部署入口](../../knowledge/README.md)执行，不复用历史 head、容器名或账号假设。仅此部署证据不能替代真实 Agent 检索验收。不要在未升级 schema 时只替换后端，也不要在新库上直接回滚到只认识旧 schema 的镜像。停用知识检索时保留表、文档、索引和向量卷，不执行降级删表或重编码。

维护后若仅恢复一个已存在的入口容器，使用经确认目标的 `docker start`；本机 Compose 的 `start <service>` 会连带启动依赖，可能重跑旧 Migrator 和初始化容器。服务更新使用已构建镜像定向 `up --no-deps --no-build`，正式迁移单独运行 `run --rm --no-deps migrator python -m app.cli.migrate`，不以全栈 bootstrap 替代。

资源技术验证需要 API 访问内部 Embedding/Qdrant。主 Compose 默认把 API、PostgreSQL、ONES MCP 接入知识内容网络，并为 API/Knowledge MCP 挂载各自所需的服务身份材料。定向更新 API 也只使用主文件。

## 管理流程

入口位于 `/api/platform/knowledge`，仅开启 Web 管理的后端注册。读操作要求 `platform_config/read`，写操作及主动读取内容目录要求登录 Cookie、现有 CSRF/Origin 校验和 `platform_config/manage`。管理员可提交受管连接配置及 Secret 引用，不提交 JWT、密码/Key 明文、环境 placement 或技术核验结果。

1. `GET /sources`、`GET /catalog` 查看已入库数据集和索引。来源只代表本地导入记录，不要求确认 ONES 地址、实例或 Team，不需要 ONES 密码/Token、证明摘要、Job 或导入确认 CLI。
2. 默认 `POST /resources` 提交 `knowledge_base_id`、`code`、`name`；自定义连接先通过 `POST /content-catalog` 读取目录，创建时同时提交 `storage` 和 `index_id` 形成初始草稿。一个 KB 最多一个启用资源，创建不等于发布。
3. `PUT /resources/{id}/draft` 提交 `expected_revision`、`index_id` 及可选 `storage`（空值/省略表示原部署连接）。服务端核对所选内容库、KB、来源与索引配置，冻结存储、模型和分块等配置事实；当前增量发布不冻结全库成员、文档数或内容摘要；不接收来源绑定，不自动创建来源确认记录。
4. `POST /resources/{id}/verify` 只检查内容 PostgreSQL 必要元数据可读、所选 KB/READY 索引归属和 profile、Embedding `/profile` 与 Qdrant 所选集合配置兼容连接；不扫描文档/成员/分块、不重算全库 hash、不统计向量点数。读取已有草稿/索引配置摘要只是核对引用，不重新计算语料。服务停止时验证仍失败；连接成功不代表本轮数据已同步完成。
5. 验证通过后 `POST /resources/{id}/publish`，均携带最新 revision。发布仅复核索引配置、管理权限、验证所属草稿及并发修订，不再全量扫描。验证/发布总 I/O 最长 30 秒，探针不自动重试；超时返回 HTTP 503 和 `knowledge_verification_timeout` 中文 JSON，不等待网关 504。仅失败证据收尾至多另用 1 秒，不接受迟到成功。发布不自动赋予角色权限；实际检索需要当前用户与业务应用的知识库权限；默认在线模式还需本人 ONES 逐项可读权限。

此简化仅针对管理验证/发布；显式全量建索引仍有完整性检查，日常同步按变化文档处理；运行时的数据一致性和双重授权仍保留。同步 INDEXING 仍可与连接检查竞争 I/O，但管理请求的工作量不再随文档/分块数量增加。

历史来源确认 CLI/API 只为兼容留存，不再是新资源保存/发布或运行读取的前提。不得为解决按钮不可用而自动确认真实批次或绑定 Mock Team；撤销历史来源确认不影响新规则资源，应通过停用资源或撤销角色 KB 授权停止检索。

管理 API 投影来源/资源/索引 ID、状态、版本、摘要和受管连接配置，不返回业务正文或凭据明文。外部 I/O 不占用平台事务，结束后复核管理授权、配置与索引引用；并发修改不能覆盖旧结果。连接变更需要新草稿/验证/发布，旧发布不受未发布编辑影响。

Web 入口为“工具资源 → 知识库”，与原数据库/Redis/Loki 页签并列，选择该页签后才加载知识目录。它复用上述 API：

- 列表和详情分别显示存储、导入来源、索引就绪及发布状态；新建资源只关联所选内容库中已入库 KB，可配置 PostgreSQL/Qdrant 连接并选择凭据中心引用，资源表单不提供正文上传、OCR 或明文密码；同页另有运维面板管理 ONES 采集计划、服务和补采。
- 草稿只选择当前 KB 的 READY 索引；来源只读展示导入记录，不受历史确认状态控制；后台仍核验本地数据、索引和管理权限。保存/验证/发布依次使用返回的新 revision，发布、停用、恢复和归档需要明确确认。
- 原“来源确认与核验”区域与手工摘要、Job ID 输入已删除。详情仅展示来源，不提供来源写入操作；无需另走导入侧确认流程；历史来源 API 保留但不控制新规则资源，原始文本和向量不变。
- 读写能力沿用 `platform.read/manage`，只读用户不可修改；前端隐藏不代替服务端管理鉴权。401、403、服务异常和 revision 冲突分开显示固定中文信息，不直接展示原始异常。
- 并发冲突不自动重试或丢弃本地输入；显式“重新载入最新配置（替换本地输入）”才更新编辑基线。角色侧仍只是按应用选择允许 KB，不复制资源配置或增加拒绝选项。

## 角色与应用的知识库允许范围

知识资源只在工具资源侧配置；角色页面沿用“角色 → 业务应用与数据范围 → 每个应用”的授权结构，只选择逻辑 KB，不重复编辑来源、索引或连接。角色 A 同时关联 app1、app2，只有 app1 勾选 KB，则该角色用户仅在 app1 获得 KB 授权，app2 不继承。

- 不新增 deny/effect 或显式拒绝选项。未选择表示该角色应用记录不授予；另一角色在同一应用下的完整允许可以生效。单条记录必须同时允许所需 Tool 和 KB，不能跨角色拼接。
- 角色业务授权 `PUT /api/admin/authorization/roles/{id}/business-access` 的每个 application 可提交 `knowledge_base_ids`；`knowledge_current_all=true` 在保存事务中展开操作者当时可授予的明确 ID，不存通配符，未来新增不自动加入。省略 KB 字段表示空集合，集成客户端须同步升级，避免全量保存时意外撤销已有 KB 授权。
- 与原业务分区共用 `expected_revision`、二次确认、委派上限和原子保存。冲突返回 `revision_conflict`，Web 保留本地选择。撤销勾选后保存即移除当前记录的 KB 允许；平台管理员只管理配置，不能绕过业务读取范围。
- Web 显示已选择 ID 与撤权提示；当前不可授予的旧 ID 保留展示并允许显式移除，不静默丢弃。授权预览可选择当前应用、Tool、KB，只验证当前 RBAC，不证明发布资源、RUNNING Job 或 ONES 可读性。
- 新 Job 的既有 authorization hash 纳入 KB 集合、角色/成员修订；授权变更不重写旧 Job 快照。知识 Tool 冻结不依赖环境范围；旧 Job 的 KB 集合与当前完整允许记录取交集，后来新增 KB grant 不扩权旧 Job。平台管理权限不进入此集合。

## Job 授权与保留的 ONES 内部入口

知识 Job 关卡要求本人启用 human 用户、RUNNING 业务应用 Job、匹配的 Session/Agent/Application Publication、发布内容完整性、精确知识工具快照及当前知识库范围。目录与检索共同使用逐记录 Tool/KB 允许投影；返回前比较当前授权摘要，变更后放弃结果。直接 Agent 携带知识能力时在创建 Job 前拒绝。知识 Principal 签发必须显式接入此关卡，未配置时失败关闭。

离线目录和搜索不调用下述在线可读性链路；其受限内部入口独立保留，不能成为离线内容查询前置条件。

`ones-mcp` 内部 `POST /internal/knowledge/work-item-readability` 使用该 Job 的完整 scope ONES Principal，不注册为模型工具。请求只含 `knowledge_base_id`、`resource_revision_id`、`index_id` 和最多 50 个唯一 `chunk_ids`；无 actor、Team、Provider 地址、操作或任意工作项 UUID。服务端按当前发布资源、来源、索引成员和当前文档版本解析 ONES UUID，同一文档的多个块只检查一次。

- 资源只读解析器仅依赖本地数据/索引，不需要 ONES 地址、Team、管理权限或 JWT 签发器；ONES 内部入口仍校验部署实例与本人身份。复用现有详情 Operation、本人唯一 ONES 身份、默认 Team 和一次 401 刷新，返回前重验授权、身份、资源与候选。
- Host/Origin、唯一 Bearer、8 KiB 请求体、严格 JSON 字段及每实例最多 4 个在途批次均独立覆盖此入口。调用内 360 秒预算缩短 Provider/登录超时与刷新锁等待，接收调用方截止时间并服从 Job 剩余预算，过期结果丢弃；首次鉴权与阻塞数据库也进入预算。来源管理核验入口仍使用独立的 4 KiB 限额。
- 明确的 Provider 403/404 返回此候选不可读，不附 UUID、标题或正文；其他 Provider/凭据/解析/预算故障使整个批次失败，不返回部分允许项。允许结果不跨调用缓存。
- 成功只返回已核验引用与编号，正文只在详情解析的内存中短暂存在；响应和该投影的操作审计均不保存正文或 Token。不得把此入口当作来源管理核验、全库权限证明或通用 ONES 代理。

## 平台双身份桥

`POST /api/internal/knowledge/work-item-readability` 只接受固定 API 内部 Host，无浏览器 Origin、Cookie 或 URL 参数。`Authorization: Bearer` 使用独立知识服务短期身份，`X-Knowledge-Principal: Bearer` 使用原用户的 Knowledge Principal；两者必须同时有效。请求仍只包含上述 KB/资源版本/索引/块引用字段，8 KiB 上限，两端共用候选成员校验。

- 服务身份固定 `sub/azp=knowledge-mcp`、`aud=knowledge-readability-bridge`，完整 scope 集合为 `internal:knowledge:work-item:readability`、`internal:knowledge:storage:connection`、`internal:knowledge:principal:refresh`，对应可读性检查、内容连接和在途身份续期三个固定内部操作。它不授予业务权限，不与文件 Worker 或其他 Business Principal 互通。
- 主 Compose 默认读取 `$HOME/.config/enterprise-agent/knowledge-bootstrap-token`，由现有密钥初始化脚本幂等生成；宿主机可在根 `.env` 或部署环境中用 `KNOWLEDGE_BOOTSTRAP_TOKEN_FILE` 指定其他文件。完整主部署的自定义路径使用宿主机绝对路径，供执行器在相同路径访问；未设置或为空保留原默认；必须是预先存在的非空普通文件，不能填写目录或 Token 内容，不能复用其他服务凭据。API/MCP 同时挂载同一来源，容器内变量仍固定为 `/run/secrets/knowledge_bootstrap_token`，并要求原 `SERVICE_PRINCIPAL_ENABLED` 开启。根目录凭据文件已 Git 忽略，不进入现有 Docker 构建上下文；其他自定义位置须自行保护。文件权限沿用现有 Secret 合同，改路径不自动生成、迁移或轮换凭据。知识服务按现有短期兑换机制获取不超过 300 秒的服务 Token，不持有签名私钥。
- API 在签发前复核完整 Knowledge scope、RUNNING Job、角色应用/KB/详情权限、当前发布资源、来源和候选成员，再按原完整 scope 签发 ONES Principal，仅调用固定 `http://ones-mcp:9104/internal/knowledge/work-item-readability`。该可读性入口无环境代理、重定向、通用 HTTP/MCP 代调用或 Token 交换响应。
- `POST /api/internal/knowledge/principal/refresh` 只接受空 JSON 对象和上述双身份，不接受 Job、用户、Server、scope 覆盖。仅能在旧 Knowledge Principal 到期前调用；复核当前任务、用户、发布、冻结完整权限和当前授权后签发，新票据除 JTI/时间外保持绑定不变，每张仍最多 300 秒。Knowledge MCP 每次工具调用独立管理内存票据，在距到期 60 秒时续期；单次续期 I/O 最多 5 秒、无重试，原调用 360 秒/Job 预算不重置。后续鉴权、内容连接和可读性请求使用最新票据。续期拒绝或非法响应会取消原请求并返回 `knowledge_principal_refresh_failed`，正常结束、断开或取消均停止续期线程。服务身份 scope/hash 改变，API 与 Knowledge MCP 必须协调升级并重新获取服务身份，不能混跑旧签发端。
- 平台按持久化文档 ID/版本/UUID 严格校验最多 64 KiB 的引用响应，重验两种 Principal、当前授权、身份/默认 Team/凭据 ACTIVE 状态以及资源/候选；查询中撤权、身份解绑或候选变化均丢弃结果。仅检查凭据状态，不读取或解密 ONES 凭据。401 刷新仍由原 ONES 链路负责。
- 审计仅记录安全状态、Job/用户/KB/资源版本，不记录请求头、业务正文、被拒绝数量、Provider 原响应或任何 Token；响应禁止缓存。Bridge 不可用/依赖故障不能解释为没有相关缺陷。

知识 bootstrap 是主部署必需材料，由初始化脚本幂等生成，API 与 Knowledge MCP 挂载同一源文件。缺失时部署应失败，不得降级为未认证请求。生产 Manifest 注册两个知识工具，旧 Job 仍受冻结合同与当前授权限制。

## 目录与检索核心

用户可以直接说“查知识库 mes_story，批记录打印一直转圈最后失败”。这里的 `mes_story` 是工具资源页面的资源编码；`story` 是显示名称，知识库 UUID 是内部 ID。Agent 使用 `knowledge_search(resource_code="mes_story", query="批记录打印一直转圈最后失败")`，无需让用户抄 UUID。也支持已有 `knowledge_base_id`，两者只能提供一个；返回的规范 ID 可用于后续工具。

编码精确匹配且仍需当前应用、角色及知识库授权；未知或未授权编码统一拒绝，不回退其他库。目录 `code` 与资源页面一致。未明确编码时再通过目录选择，名称歧义须澄清。代码知识库仍必须提供环境和 SVN 数字版本，ONES 资料查询不要求这些参数。

资源编码工具合同为 `knowledge-search-contract/v8-resource-code`；当前 Prompt v19 已同时包含后续 ONES 详情与评论核验流程。部署后需按正常流程发布新 Agent，并更新业务应用的 Agent 引用、发布和激活；保留原工具选择、角色授权和执行策略。无需重新发布知识资源或重建索引。

目录只返回冻结与当前知识库授权交集内、已发布且本地数据/索引兼容的 KB；不读取本人 ONES 绑定。固定每页 50 项，按稳定 KB ID 续页。cursor 绑定 Job、用户、应用、发布、快照、授权及可见资源，300 秒有效。进程重启或篡改导致 invalid；平台授权或资源变化导致 stale，均须从首页重查。

检索只接受一个明确 KB、1–2000 字 query 和 1–20 的 top_k（默认 10）。最多召回 200 个点，校验当前成员/版本和点身份，按文档取前 50 篇进行 Cross-Encoder 重排。默认 online 对命中逐批核验本人 ONES 当前可读性，需要详情工具选择与授权；仅显式 offline 不请求 ONES；现有知识库 grant 不变，后来增加的库不会自动扩展旧 Job。

结果包含完整标题、原来源编号、状态、来源项目、`source_updated_at`、`ingested_at` 和至多三个带位置/hash 的 `evidence.text`，每片段最多 1200 字符，工具总响应最多 512 KiB。`ingested_at` 是当前修订入库时间，不冒充最近采集时间。返回实际 `access_mode`，固定 `content_mode=ingested_snapshot`、`content_scope=matched_chunks`：片段可用于回答，但不是完整文档或来源最新事实。排名使用 `rank`，`retrieval_score` 不是概率；在线实时核验只代表当前读取权限；需要最新正文时另用已授权 ONES 详情工具。离线模式取得的快照不依赖 ONES 在线状态。

- 内容只通过所选已发布连接读取；返回前重验平台授权、发布资源、当前收录、文档修订、索引及片段 hash。任一变化整体失败，不泄露跨库或被撤销的内容。
- 召回/重排上限使 top_k 不满时标记 `partial=true`；零命中、部分结果与依赖失败分开。全量返回 top_k 不代表扫描全库。
- 最多 360 秒与当前 attempt 剩余时间共同约束。客户端、数据库和内部 HTTP 共用截止与取消，重试/终态改变后结果失效；在线检索不额外重试，不回退其他模型或存储。
- 成功安全审计只存授权后 KB/资源版本/索引、返回计数、partial 及排名配置；失败只存错误码。查询原文、标题、片段、原始异常及认证材料不进入普通审计/日志。受控 Runtime 记录沿用既有访问与保留规则。

## 模型边界：本地 Embedding，沿用已配置聊天模型

在线 MCP 向量化使用独立 `knowledge-embedding-online`，后台分块/索引/小时同步使用原 `knowledge-embedding`，共享只读固定模型而不共享推理锁。部署/升级和额外内存预算见[Embedding 隔离](../../knowledge/README.md#在线后台-embedding-隔离与升级)。模型繁忙、超时和不可用分别返回 `knowledge_embedding_busy`、`knowledge_embedding_read_timeout`、`knowledge_embedding_unavailable`，不是 PostgreSQL 故障；原始异常不进入响应/审计，不回退后台实例，总预算仍最多 360 秒，并受 Job 剩余时间限制；文档重排使用独立 `knowledge-reranker`，重排失败返回错误，不静默退回原排序。

用户已接受授权后的检索结果、ONES 正文和历史上下文进入 Agent 既有聊天模型（包括外部模型）。本地 Embedding 只保证向量化不外发，不表示聊天分析阶段也不外发。检索、索引仍使用部署固定的内部 Embedding，失败不回退外部向量服务。

不再配置 INTERNAL_MODEL_POLICY_FILE，不再输出 internal_model_deployment 或新增 model_data_boundary；旧的强制内网认可与执行拒绝已撤去。不为此增加 Runtime 协议字段或 Session/摘要/产物继承。保留模型连接白名单、Publication 固定 revision/config hash、既有别名映射和 Runtime 签名；Runtime 仍无权读取 Job、Session、Publication、RBAC 等业务表。历史 Publication 不自动改写。

Agent Envelope 与 Application 子集选择任一知识工具时，必须同时选择 knowledge_list_bases 和 knowledge_search；离线模式不要求 ONES 详情工具，在线模式必须另行选择并授予本人详情能力，桥会在执行时核验；知识工具缺项在发布前拒绝，不自动补工具或授权。Worker 在模型解析和历史摘要前复核当前知识工具及 KB 授权，具体命中继续当前成员和修订验证。外部聊天获准不代表扩大知识读取范围。通用日志/外部遥测不增加 query、向量或业务正文；受控运行记录遵守原有访问/保留合同。

代码合同和合成测试不代替真实新 Job 验收；部署状态与验收结果单独记录。

## 正式工具合同与固定 Runtime 路由

两个知识工具现由共享的纯合同模块定义输入/输出 Schema 和中文说明，正式进入 Tool 目录、Agent Envelope、Application 子集及角色工具目录；不再依赖测试动态注入。Manifest 固定 `read` / `none`，不借用环境资源类型。授权凭证使用独立 `knowledge-mcp` audience 和 `mcp:knowledge-mcp:<tool>:invoke` 完整 scope，不能复用 ONES audience 的凭证。

Runtime 的部署默认地址为 `http://knowledge-mcp:9108/mcp`，可选 `KNOWLEDGE_MCP_SERVER_URL` 仍受固定服务主机/回环地址策略校验，不可由 Job 或 Tool 参数改写。只有冻结了该 Server 的新 Job 才会建立此路由；未启用知识组件的既有 Job 不会连接它，也不会要求 Knowledge Principal。Runtime 不增加知识业务模块、数据库权限、Qdrant/Embedding 客户端或新的协议字段。

工具说明与使用知识工具时的系统提示一致：明确资源编码时直接检索，否则分页发现获准 KB，选库后读取入库内容片段并标明快照范围。不猜 KB/Team；命中片段不代表完整文档；零命中、部分结果和服务异常分别说明；名称、命中及业务正文只作为不可信数据。

**代码注册不是服务已可用。** 实际发布前核对部署版本、模型就绪及当前平台知识库授权的新 Job 链路。目录与 `knowledge_search` v4 模式 Schema 已变化，必须按正常流程发布新 Agent、更新应用引用并发布激活；否则新 Job 会被 `mcp_tool_schema_drift` 拒绝。旧 Publication 和 Job Snapshot 不原地改写；知识内容日常同步不要求这项重新发布。

## 独立 Knowledge MCP 服务

代码位于 [`services/knowledge_mcp_server`](../../services/knowledge_mcp_server/)，与 ONES、钉钉 MCP 同级；不新建单数 `service` 目录。入口为 `services.knowledge_mcp_server.app`，提供固定端口 9108 的 `/mcp`（无状态 Streamable HTTP、JSON 响应）和 `/health`。使用与其他 MCP 一致的 `mcp==2.0.0` 可选依赖组 `knowledge-mcp`，由 `backend/Dockerfile` 的同名 target 打包，非 root、只读根目录、仅受限 tmpfs。部署文件及步骤见[知识部署入口](../../knowledge/README.md)。

- `app.py` 处理严格 HTTP/JSON、固定工具发现/调用和断开通知；32 KiB 请求、512 KiB 工具结果上限，拒绝重复关键头、Origin、Cookie、URL 参数、非固定 Host 和过期 deadline，响应不缓存。
- `auth.py` 复用独立 Knowledge audience、完整 scope 和当前 Job 关卡，核对持久化 Job/用户/应用发布/Agent 发布及 attempt、correlation；不读取 ONES 凭据或签发 Token。
- `tools.py` 调用既有 `KnowledgeDirectory` / `KnowledgeSearch`，不复制向量检索、角色权限或知识授权规则。MCP 根审计请求只存工具名，响应仅存安全版本/计数；返回既有审计关联 ID，不存 query、cursor、库名、命中 UUID 或正文。
- `execution.py` 固定 4 个真实在途线程槽位，调用等待有截止时间。客户端断开/超时后设置取消信号，嵌套检索预算继续检查；未退出的线程不释放槽位，无额外无界工作队列。
- `bootstrap.py` 狭窄装配，只接公开 JWKS、平台数据库、固定 Embedding、受管内容连接、独立服务短期身份和固定平台桥。不调用平台全量 Container/load_settings，不加载主密钥、签名私钥、模型 Key 或 ONES 凭据仓储。Compose 直接复用既有 `DATABASE_DSN`，公开 JWKS 与知识 bootstrap 文件沿用受管挂载。内容凭据由固定内部连接入口经过双身份与当前 KB/发布核验后仅在调用内存提供，不能传入任意 Secret 引用；ONES 目标仍归现有 ONES 服务。
- 启动不再要求固定数据库角色，也不拒绝平台管理员账号；服务具有所选账号的数据库权限。`database_policy.py` 和独立账号配置 CLI 保留为运维可选工具，不自动创建账号或修改权限。实际工具查询和审计写入范围仍由应用实现限定，用户、Job、KB、发布和当前成员/修订校验继续执行。审计 readiness 使用无清理模式，保留/清理由平台承担；PostgreSQL/schema 就绪校验仍须通过。

`/health` 只检查数据库 schema 与审计依赖，不证明 Qdrant/Embedding/ONES 或业务资源可用。主部署默认包含全部知识服务与身份配置。独立 PostgreSQL tmpfs 容器验证了账号最小权限及拒绝矩阵；镜像 COPY 白名单测试只是独立导入，尚不能代替实际完整服务构建/启动、容器重启或真实 ONES 验收。

## Knowledge 代码分层

| 层 | 职责 |
| --- | --- |
| domain | 规范化、分块、稳定身份与点 payload、领域输入规则、Tool 依赖；无数据库/文件/HTTP I/O |
| application | 导入、分块、索引、评测和来源/资源/目录/检索用例，通过实际所需端口访问依赖 |
| infrastructure | SQL/锁/事务、受限文件、固定 Embedding profile、HTTP/身份适配及静态装配 |
| api | HTTP 参数、登录/CSRF、用例调用与安全响应，不写 SQL 或构造客户端 |

CLI、bootstrap、ONES 和 Embedding 镜像均使用新分层路径，不保留平铺兼容层。分层测试保护依赖方向，原行为测试继续覆盖回滚、断点、幂等和权限。没有新通用 CRUD 框架、事件总线或插件层。

源记录、修订、分块、向量点 ID、内容 hash、Embedding profile/锁文件和点 payload 不变；无需重导入、重分块或重编码。评测的实现 code_hash 因代码变化更新，这是预期的追溯信息，不是语料或索引身份变化。

## 停用与失败处理

| 安全错误或状态 | 处理方式 |
| --- | --- |
| `knowledge_revision_conflict` | 重新读取当前 revision，确认差异后重试，不自动覆盖 |
| `knowledge_storage_config_invalid` | 检查 PostgreSQL/Qdrant 配置与凭据引用格式，不填写明文密码或带凭据 URL |
| `knowledge_storage_readonly_unavailable` | 检查读取连接是否成功启用只读事务；内容账号允许管理员/读写权限，不要求为此更换账号；平台治理账号仍遵守最小权限合同 |
| `knowledge_storage_credentials_unavailable` | 在凭据中心检查引用是否存在、启用及可解密，不导出凭据 |
| `knowledge_storage_unavailable` | 检查所选内容库、网络、TLS 与内容表兼容性，不回退其他数据库 |
| `knowledge_verifier_unavailable` | 检查受信 ONES 部署配置；不要输入临时 URL 或改用共享凭据 |
| `knowledge_verification_failed` | 核对来源、索引与依赖服务；只查安全审计，不导出 Token/响应正文 |
| `knowledge_source_changed` | 本地数据或回源工作项归属变化，核对数据后重新保存、验证和发布；不要求地址/Team 来源确认 |
| `knowledge_resource_unavailable` | 检查发布/启停状态及本地数据；旧版本须重新保存验证发布；不切换未发布或旧索引作为 fallback |
| `knowledge_resource_changed` | 本次固定版本失效，放弃结果并重新发起查询 |
| `knowledge_bridge_unavailable` | 知识组件未装配；检查主 Compose 的知识认证配置与 MCP 接线，不临时绕过双身份桥 |
| `knowledge_bridge_identity_invalid` | 核对独立服务身份、当前 Knowledge Principal 和 Job/角色授权；不导出或复用历史 Token |
| `knowledge_readability_failed` | 在线 ONES 可读性入口错误；仅显式 offline 不调用此入口。在线错误应核对当前身份、详情授权及 ONES 服务；不可自动降级 |
| `knowledge_readability_busy` | 已达固定在途上限，稍后重试，不扩大候选数量 |
| `knowledge_cursor_invalid` / `knowledge_cursor_stale` | 从第一页重新发现；不要复用其他 Job、实例或旧权限下的游标 |
| `knowledge_source_identity_invalid` | 在线 ONES 可读性入口错误，核验本人身份与受信实例；不作为离线知识读取前置条件 |
| `knowledge_search_busy` | 已有 4 个检索在途，稍后重试，不扩大服务内无界队列 |
| `knowledge_search_budget_exhausted` | 本次检索或当前 Job attempt 预算已耗尽；本次结果作废，不继续扩大候选 |
| `knowledge_search_dependency_failed` | 检查内部 Embedding/Qdrant 和安全审计；不能解释为零命中或改走外部服务 |

`POST /resources/{id}/status` 提交 `expected_revision` 和 `status`（enabled/disabled/archived）；归档不可重新启用。停用再启用会递增状态版本，旧在途调用仍失效。编辑未发布草稿不会改变正在使用的发布版本。

`POST /source-bindings/{id}/revoke` 只接受空 JSON 对象，幂等撤销历史绑定；新规则资源不依赖它，撤销不删除历史证据或现有索引。停止新资源读取应停用资源或撤销 KB 授权，不能由运行请求自动重新发布。

完整部署与回退继续遵守[知识部署说明](../../knowledge/README.md)和[本地索引运行手册](knowledge-local-vector-index.md)。合成/Mock 通过仅证明代码合同；真实 ONES、正式 PostgreSQL/服务部署、本地 Embedding 和已配置聊天模型的真实新 Job 须分别验收。

## 隔离容器验收

在仓库根目录显式执行：

```bash
KNOWLEDGE_CONTAINER_ACCEPTANCE=1 .venv/bin/pytest -q --tb=short backend/tests/test_knowledge_container_acceptance.py
```

该入口使用[独立测试 Compose](../../backend/tests/support/knowledge_container/compose.yml)，不叠加主部署、不读取其 `.env`，不挂 Docker socket、业务卷或业务输入，也不暴露宿主机端口。镜像构建需要依赖下载能力；运行时只有独立 internal 网络。测试生成专用密钥，创建临时 PostgreSQL 与项目隔离的 Qdrant 测试卷；结束或断言失败时清理测试容器、网络、卷和密钥。专用 `enterprise-agent-knowledge-acceptance-*` 镜像保留以便重跑；异常强制终止后应先按本次 `knowledge-acceptance-<随机 ID>` 确认目标，不能清理正式项目。

API、ONES MCP、Knowledge MCP 使用正式 Dockerfile target 与启动入口；仅测试驱动镜像增加 pytest/合成夹具。验证真实 HTTP 下的管理登录、草稿/验证/发布、服务身份兑换、已发布内容连接凭据桥、独立 Principal、离线内容检索、独立 ONES 详情调用、online 模式过滤 403 并在 5xx 失败，offline 模式 403/5xx 不阻断入库快照、KB 撤权/恢复、资源停用/启用及容器重启后读取。关闭知识组件后，以独立空知识库数据库及未配置知识凭据的 API 验证普通登录与身份接口。

测试同时在镜像所装 psycopg 版本下执行数据库/DNS/握手/事务截止回归。驱动适配只转发实际 `connect()` 传入的参数，兼容 3.3.4 的生成器 timeout 与 3.3.6 的外层 wait_conn timeout，不扩大调用方原截止或普通调用权限；当前代码的整体上限为 360 秒，当前可配置合同见本页开头。

证据边界：测试采用合成 ONES HTTP 服务、确定性 Embedding/重排引擎和单文档语料；外部内容连接模式指向同一个临时 PostgreSQL 数据库。通过不证明真实用户 ONES 权限、物理异库网络/TLS、真实 BGE-M3 质量、聊天模型或完整消息投递链路。正式上线、双真实用户和人工相关性评测仍须单独验收。
