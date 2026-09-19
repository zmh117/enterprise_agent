# 知识治理管理与排障

本页描述 `enable-governed-knowledge-retrieval` 已实现的来源、资源 Web 管理、角色应用 KB 允许范围、Job/ONES 内部投影、平台双身份桥与目录/检索应用服务，以及正式工具合同、固定 Runtime 路由、独立 MCP 服务入口与可选部署配置，不代表 Agent 检索已经开放。整条链路的阻塞 I/O deadline、完整隔离容器和真实验收仍须完成。仅部署 Embedding/Qdrant 不会自动发布资源或赋予业务权限。

## 数据库和部署边界

治理表通过平台前向迁移 `137_expand_knowledge_retrieval_governance.sql` 加入现有数据库的 `knowledge` schema；角色 KB 关系 `rbac_role_application_knowledge_base` 留在现有 RBAC 所属的 public schema，以外键引用逻辑 KB。不新建数据库，也不改变现有 source/knowledge_base 的离线存储状态、文档、分块或向量身份。迁移不创建真实来源绑定、发布或角色授权。`138_expand_knowledge_source_confirmation.sql` 新增 CONFIRMED 状态，保留所有旧绑定及引用，不把 PENDING 自动升级；其含义是导入来源已明确确认，不是 Provider 已完成抽样核验。

API/Worker/ONES 镜像更新仍须经过正式 Migrator 和平台 schema readiness 门禁；本轮没有执行正式迁移或服务重启。不要在未升级 schema 时只替换后端，也不要在新库上直接回滚到只认识旧 schema 的镜像。停用知识检索时保留表、文档、索引和向量卷，不执行降级删表或重编码。

## 管理流程

入口位于 `/api/platform/knowledge`，仅开启 Web 管理的后端注册。读操作要求 `platform_config/read`，写操作要求登录 Cookie、现有 CSRF/Origin 校验和 `platform_config/manage`。客户端不提交 JWT、连接地址、凭据、环境 placement 或技术核验结果。

1. 导入方明确整批数据的 ONES 实例和原生 Team。导入后使用下述受限 CLI 做一次来源确认；不需要证明文件摘要或正在运行的 Job，不调用 ONES，不自动发布。原 source/KB 的离线存储状态不变。
2. `GET /sources`、`GET /catalog` 查看来源与数据集元数据；Web 只读继承数据集的唯一有效 CONFIRMED 或历史 VERIFIED 来源。缺失、撤销或多义时不能保存草稿，不允许手选其他数据集的来源。
3. `POST /resources` 提交 `knowledge_base_id`、`code`、`name`；一个 KB 最多一个启用资源，创建不等于发布。
4. `PUT /resources/{id}/draft` 提交 `expected_revision`、继承的 `binding_id`、明确选择的 `index_id`；服务端仍检查完整成员归属。验证与发布分别通过 `POST /resources/{id}/verify` 和 `POST /resources/{id}/publish`，均需最新修订。索引、Embedding profile、Qdrant 配置/点数及返回前并发复核不变。

受限导入后入口（示例均为占位符，替换为已确认的非敏感 ID；不在本次自动执行）：

```bash
python -m app.cli.confirm_knowledge_source \
  --source-id SOURCE_ID --actor-id ADMIN_USER_ID \
  --instance-code INSTANCE_CODE --team-id TEAM_ID --expected-revision 0
```

默认仅预检；确认整批归属后，显式追加 `--confirm-source --commit` 才写入。CLI 使用当前数据库配置，要求 schema 为最新且操作人具有当前平台管理权限，实例必须匹配固定部署；不签发 JWT、不读取 ONES 凭据或打印业务正文。首次 revision 为 0，换源需填写当前修订，立即撤销旧绑定，依赖旧绑定的资源须重新配置验证发布。未知来源不能猜测填写；已有 5,000 条离线批次仍待真实确认。在线采集尚未实现，后续应复用导入侧确认用例，不把来源配置放回资源页面。

旧 `POST /source-bindings` 与 `/{id}/verify` 仅保留已有管理客户端兼容，不是新 Web 流程的前置条件；原 JWT、本人 RUNNING Job 和技术核验约束不放宽。历史 VERIFIED 证据不重写。来源确认不是数据读取授权，运行时仍执行 KB＋当前用户 ONES 逐项检查。

管理 API 只投影来源/资源/索引 ID、状态、版本与摘要，不返回业务正文或任意连接配置。来源核验和资源验证在外部 I/O 期间不持有数据库事务，结束后复核管理授权、配置和来源；并发修改不能覆盖旧结果。

Web 入口为“工具资源 → 知识库”，与原数据库/Redis/Loki 页签并列，选择该页签后才加载知识目录。它复用上述 API：

- 列表和详情分别显示存储、来源核验、索引就绪及发布状态；新建资源只关联已入库 KB，不提供正文上传、OCR、自动采集、任意地址或凭据配置。
- 草稿只选择当前 KB 的 READY 索引；来源只读继承唯一有效绑定，不自动选择第一候选；后台仍核验完整来源、索引和权限。保存/验证/发布依次使用返回的新 revision，发布、停用、恢复和归档需要明确确认。
- 原“来源确认与核验”区域与手工摘要、Job ID 输入已删除。详情仅展示来源，不提供来源写入操作；来源建立、换版归导入流程，撤销 API 保留，撤销不删除文本或向量。
- 读写能力沿用 `platform.read/manage`，只读用户不可修改；前端隐藏不代替服务端管理鉴权。401、403、服务异常和 revision 冲突分开显示固定中文信息，不直接展示原始异常。
- 并发冲突不自动重试或丢弃本地输入；显式“重新载入最新配置（替换本地输入）”才更新编辑基线。角色侧仍只是按应用选择允许 KB，不复制资源配置或增加拒绝选项。

## 角色与应用的知识库允许范围

知识资源只在工具资源侧配置；角色页面沿用“角色 → 业务应用与数据范围 → 每个应用”的授权结构，只选择逻辑 KB，不重复编辑来源、索引或连接。角色 A 同时关联 app1、app2，只有 app1 勾选 KB，则该角色用户仅在 app1 获得 KB 授权，app2 不继承。

- 不新增 deny/effect 或显式拒绝选项。未选择表示该角色应用记录不授予；另一角色在同一应用下的完整允许可以生效。单条记录必须同时允许所需 Tool 和 KB，不能跨角色拼接。
- 角色业务授权 `PUT /api/admin/authorization/roles/{id}/business-access` 的每个 application 可提交 `knowledge_base_ids`；`knowledge_current_all=true` 在保存事务中展开操作者当时可授予的明确 ID，不存通配符，未来新增不自动加入。省略 KB 字段表示空集合，集成客户端须同步升级，避免全量保存时意外撤销已有 KB 授权。
- 与原业务分区共用 `expected_revision`、二次确认、委派上限和原子保存。冲突返回 `revision_conflict`，Web 保留本地选择。撤销勾选后保存即移除当前记录的 KB 允许；平台管理员只管理配置，不能绕过业务读取范围。
- Web 显示已选择 ID 与撤权提示；当前不可授予的旧 ID 保留展示并允许显式移除，不静默丢弃。授权预览可选择当前应用、Tool、KB，只验证当前 RBAC，不证明发布资源、RUNNING Job 或 ONES 可读性。
- 新 Job 的既有 authorization hash 纳入 KB 集合、角色/成员修订；授权变更不重写旧 Job 快照。知识 Tool 冻结不依赖环境范围；旧 Job 的 KB 集合与当前完整允许记录取交集，后来新增 KB grant 不扩权旧 Job。平台管理权限不进入此集合。

## Job 与 ONES 内部可读性关卡

知识 Job 关卡要求本人启用 human 用户、RUNNING 业务应用 Job、匹配的 Session/Agent/Application Publication、发布内容完整性、精确工具快照以及当前详情 Tool grant。目录与检索共同使用逐记录 Tool/KB 允许投影；返回前比较当前授权摘要，变更后放弃结果。直接 Agent 携带知识能力时在创建 Job 前拒绝。知识 Principal 签发必须显式接入此关卡，未配置时失败关闭。

`ones-mcp` 内部 `POST /internal/knowledge/work-item-readability` 使用该 Job 的完整 scope ONES Principal，不注册为模型工具。请求只含 `knowledge_base_id`、`resource_revision_id`、`index_id` 和最多 50 个唯一 `chunk_ids`；无 actor、Team、Provider 地址、操作或任意工作项 UUID。服务端按当前发布资源、来源、索引成员和当前文档版本解析 ONES UUID，同一文档的多个块只检查一次。

- 仅持有固定目标配置和公共验签能力；资源只读解析器不需要管理权限或 JWT 签发器。复用现有详情 Operation、本人唯一 ONES 身份、默认 Team 和一次 401 刷新，返回前重验授权、身份、资源与候选。
- Host/Origin、唯一 Bearer、8 KiB 请求体、严格 JSON 字段及每实例最多 4 个在途批次均独立覆盖此入口。调用内 60 秒预算缩短 Provider/登录超时与刷新锁等待，接收调用方截止时间并服从 Job 剩余预算，过期结果丢弃；数据库阻塞等完整墙钟验收仍属任务 7.3。来源管理核验入口仍使用独立的 4 KiB 限额。
- 明确的 Provider 403/404 返回此候选不可读，不附 UUID、标题或正文；其他 Provider/凭据/解析/预算故障使整个批次失败，不返回部分允许项。允许结果不跨调用缓存。
- 成功只返回已核验引用与编号，正文只在详情解析的内存中短暂存在；响应和该投影的操作审计均不保存正文或 Token。不得把此入口当作来源管理核验、全库权限证明或通用 ONES 代理。

## 平台双身份桥

`POST /api/internal/knowledge/work-item-readability` 只接受固定 API 内部 Host，无浏览器 Origin、Cookie 或 URL 参数。`Authorization: Bearer` 使用独立知识服务短期身份，`X-Knowledge-Principal: Bearer` 使用原用户的 Knowledge Principal；两者必须同时有效。请求仍只包含上述 KB/资源版本/索引/块引用字段，8 KiB 上限，两端共用候选成员校验。

- 服务身份固定 `sub/azp=knowledge-mcp`、`aud=knowledge-readability-bridge` 和 scope `internal:knowledge:work-item:readability`。它不授予业务权限，不与文件 Worker 或其他 Business Principal 互通。
- 可选 `KNOWLEDGE_BOOTSTRAP_TOKEN_FILE` 供现有身份签发器按独立受管文件读取；仅启用知识组件时配置，并要求原 `SERVICE_PRINCIPAL_ENABLED` 开启。文件权限沿用现有 Secret 合同，内容不得与其他服务相同。知识服务按现有短期兑换机制获取不超过 300 秒的服务 Token，不持有签名私钥。
- API 在签发前复核完整 Knowledge scope、RUNNING Job、角色应用/KB/详情权限、当前发布资源、来源和候选成员，再按原完整 scope 签发 ONES Principal，仅调用固定 `http://ones-mcp:9104/internal/knowledge/work-item-readability`。无环境代理、重定向、通用 HTTP/MCP 代调用或 Token 交换响应。
- 平台按持久化文档 ID/版本/UUID 严格校验最多 64 KiB 的引用响应，重验两种 Principal、当前授权、身份/默认 Team/凭据 ACTIVE 状态以及资源/候选；查询中撤权、身份解绑或候选变化均丢弃结果。仅检查凭据状态，不读取或解密 ONES 凭据。401 刷新仍由原 ONES 链路负责。
- 审计仅记录安全状态、Job/用户/KB/资源版本，不记录请求头、业务正文、被拒绝数量、Provider 原响应或任何 Token；响应禁止缓存。Bridge 不可用/依赖故障不能解释为没有相关缺陷。

当前未配置此可选凭据时平台桥返回不可用，不新增主部署的必需 Secret。在线配置现由 `knowledge/mcp.compose.yml` 显式启用；正式部署仍需批准。生产 Manifest 已注册两个知识工具，但没有冻结这两项的旧 Job 仍无法通过关卡；后续须完成部署与验收，再开放 Agent 知识检索。

## 目录与检索核心（已接服务代码，尚未部署）

目录仅返回冻结与当前授权交集内、资源已发布、来源匹配本人 ONES 实例与默认 Team 的 KB，包含 ID、编码、管理名称和可用状态，不返回文档数量或样本。固定每页 50 项，按稳定 KB ID 续页。cursor 绑定 Job/用户/应用/发布/快照/授权、可见资源与本人来源，300 秒有效。进程重启、另一实例或篡改导致 invalid；授权或可见资源变化导致 stale，均须从首页重查。游标不可当作授权票据，也不承诺跨副本连续分页。

检索仅接受一个 KB、1–2000 字符的 query、1–20 的 top_k（默认 10）。固定一次读取最多 200 个候选点，回 PostgreSQL 校验当前版本/收录和点身份，按文档去重后逐批通过双身份桥检查本人可读性，最多 50 个工作项、每实例最多 4 个并行检索。输出只包含允许引用和每文档至多 3 个证据位置，不输出缓存标题/正文/附件 URL、向量或拒绝计数。Agent 后续仍需经现有 ONES 详情工具读取当前内容。

- 明确 403/404 仅过滤该项；Provider/凭据/解析失败使整次检索失败，即使先前已有允许项也不返回部分成功。
- 候选上限或预留返回复核时间使 top_k 不满时，返回已确认可读引用及 `partial=true`、通用 `bounded_search`；不能据此宣称全库无数据。硬预算已经耗尽则报错并丢弃结果。
- 已实现的调用内预算取 60 秒与当前 Job attempt 剩余时间的较小值，以 `locked_at` 和执行策略识别当前 claim；重试/终态改变后结果失效。在线 Embedding/Qdrant 不额外重试，离线构建仍保留原超时与重试。
- 内部 `X-Knowledge-Deadline-Ms`（UTC 毫秒）已从搜索传播到平台/ONES；接收方再次取本地 60 秒与当前 Job attempt 剩余预算的较小值。Header 不增加权限，重复/格式错误/过期拒绝；未提供时仍有本地 Job 限额。部署需同步各服务时钟。服务身份缓存命中、刷新锁、兑换、ONES 登录和 Provider 使用同一剩余预算，超时不标记正常 ONES 凭据失效。
- 生产知识 HTTP 已有可取消网络协程的整次请求 timeout，覆盖连接/响应及持续滴流，不只是 socket 空闲超时；不继承代理、不跟随重定向、请求 identity 编码并拒绝压缩响应。目标验证、本人身份、详情解析及一次 401 刷新仍归原客户端，普通 ONES 与离线索引调用保持旧传输合同。本机临时 HTTP 服务测试证明慢响应会中止连接，不代表真实 Provider/部署验收。
- **任务 7.3 仍未完成**：MCP/ASGI 已接入口预算、客户端断开通知、嵌套预算取消和有界工作线程；数据库连接池/SQL 等待尚无统一截止控制，同步入口中 DNS 解析及事件循环清理也未取得故障注入证据。取消等待不等于强制终止阻塞线程；迟到线程实际结束前继续占用槽位。不得把网络慢响应专项通过当作整条链路 60 秒墙钟保证。返回前仍会检查预算并丢弃迟到结果。
- 成功审计仅有授权后的 KB/资源版本/索引、返回数量和 partial；失败仅安全错误码及已认证 Job/用户。无 query、原始异常、业务正文、被拒绝身份/数量或 Token。返回前重验当前授权、身份、来源、发布资源与证据；撤权后不返回旧结果。

## 模型边界：本地 Embedding，沿用已配置聊天模型

用户已接受授权后的检索结果、ONES 正文和历史上下文进入 Agent 既有聊天模型（包括外部模型）。本地 Embedding 只保证向量化不外发，不表示聊天分析阶段也不外发。检索、索引仍使用部署固定的内部 Embedding，失败不回退外部向量服务。

不再配置 INTERNAL_MODEL_POLICY_FILE，不再输出 internal_model_deployment 或新增 model_data_boundary；旧的强制内网认可与执行拒绝已撤去。不为此增加 Runtime 协议字段或 Session/摘要/产物继承。保留模型连接白名单、Publication 固定 revision/config hash、既有别名映射和 Runtime 签名；Runtime 仍无权读取 Job、Session、Publication、RBAC 等业务表。历史 Publication 不自动改写。

Agent Envelope 与 Application 子集选择任一知识工具时，必须成套选择 knowledge_list_bases、knowledge_search 和 ones_get_work_item_detail；缺项在发布前拒绝，不自动补工具或授权。Worker 在模型解析和历史摘要前复核当前知识工具/详情授权，具体命中继续双权限验证。外部聊天获准不代表扩大知识读取范围。通用日志/外部遥测不增加 query、向量或业务正文；受控运行记录遵守原有访问/保留合同。

该调整不是生产 Knowledge MCP 已开放的证明：完整服务预算、部署运行与真实新 Job 仍按未完成任务验收。本次不调用真实聊天模型或发送业务内容。

## 正式工具合同与固定 Runtime 路由

两个知识工具现由共享的纯合同模块定义输入/输出 Schema 和中文说明，正式进入 Tool 目录、Agent Envelope、Application 子集及角色工具目录；不再依赖测试动态注入。Manifest 固定 `read` / `none`，不借用环境资源类型。授权凭证使用独立 `knowledge-mcp` audience 和 `mcp:knowledge-mcp:<tool>:invoke` 完整 scope，不能复用 ONES audience 的凭证。

Runtime 的部署默认地址为 `http://knowledge-mcp:9108/mcp`，可选 `KNOWLEDGE_MCP_SERVER_URL` 仍受固定服务主机/回环地址策略校验，不可由 Job 或 Tool 参数改写。只有冻结了该 Server 的新 Job 才会建立此路由；未启用知识组件的既有 Job 不会连接它，也不会要求 Knowledge Principal。Runtime 不增加知识业务模块、数据库权限、Qdrant/Embedding 客户端或新的协议字段。

工具说明与使用知识工具时的系统提示一致：先分页发现获准 KB，明确选库后检索引用，需要正文再经 ONES 详情回源。不猜 KB/Team；目录可见不代表全文可读；零命中、部分结果和服务异常分别说明；名称、命中及业务正文只作为不可信数据。

**代码注册不是服务已可用。** MCP/ASGI 入口与安全 MCP 审计已有合成测试，可选 Compose 和最小数据库权限已有代码及隔离验证；阻塞依赖的统一截止/取消验收仍归任务 7.3，完整隔离容器归任务 10.4。完成这些步骤和相应验收前，不应发布真实知识应用。本次不会修改旧 Publication、Job Snapshot 或角色授权。

## 独立 Knowledge MCP 服务

代码位于 [`services/knowledge_mcp_server`](../../services/knowledge_mcp_server/)，与 ONES、钉钉 MCP 同级；不新建单数 `service` 目录。入口为 `services.knowledge_mcp_server.app`，提供固定端口 9108 的 `/mcp`（无状态 Streamable HTTP、JSON 响应）和 `/health`。使用与其他 MCP 一致的 `mcp==2.0.0` 可选依赖组 `knowledge-mcp`，由 `backend/Dockerfile` 的同名 target 打包，非 root、只读根目录、仅受限 tmpfs。部署文件及步骤见[可选知识部署](../../knowledge/README.md#在线-knowledge-mcp独立可选扩展)。

- `app.py` 处理严格 HTTP/JSON、固定工具发现/调用和断开通知；32 KiB 请求、256 KiB 工具结果上限，拒绝重复关键头、Origin、Cookie、URL 参数、非固定 Host 和过期 deadline，响应不缓存。
- `auth.py` 复用独立 Knowledge audience、完整 scope 和当前 Job 关卡，核对持久化 Job/用户/应用发布/Agent 发布及 attempt、correlation；不读取 ONES 凭据或签发 Token。
- `tools.py` 调用既有 `KnowledgeDirectory` / `KnowledgeSearch`，不复制向量检索、角色权限或 ONES 可读性规则。MCP 根审计请求只存工具名，响应仅存安全版本/计数；返回既有审计关联 ID，不存 query、cursor、库名、命中 UUID 或正文。
- `execution.py` 固定 4 个真实在途线程槽位，调用等待有截止时间。客户端断开/超时后设置取消信号，嵌套检索预算继续检查；未退出的线程不释放槽位，无额外无界工作队列。
- `bootstrap.py` 狭窄装配，只接公开 JWKS、数据库、固定 Embedding/Qdrant、独立服务短期身份和固定平台桥。不调用平台全量 Container/load_settings，不加载主密钥、签名私钥、模型 Key 或 ONES 凭据仓储。所需配置为 `DATABASE_DSN`（Compose 从独立 `KNOWLEDGE_DATABASE_DSN` 注入）、`PRINCIPAL_JWKS_FILE`、`KNOWLEDGE_BOOTSTRAP_TOKEN_FILE`、`ONES_IDENTITY_INSTANCE_CODE`、`ONES_MCP_PROVIDER_BASE_URL`；后两项只用于受信来源匹配，不让知识服务直连 Provider。
- `database_policy.py` 按当前查询授予固定角色 `knowledge_mcp_reader` 明确列的 SELECT，只允许三张审计表必要写入；原始 Job/会话正文、完整 ONES 凭据、原始文档修订和业务写入均拒绝。独立 CLI 由运维显式配置角色，启动只校验，不自动提权。审计 readiness 使用无清理模式，仅要求关联字段读取及 INSERT/UPDATE，保留/清理由平台承担。

`/health` 只检查数据库 schema 与审计依赖，不证明 Qdrant/Embedding/ONES 或业务资源可用。服务未启用时主部署没有新增必需配置。独立 PostgreSQL tmpfs 容器验证了账号最小权限及拒绝矩阵；镜像 COPY 白名单测试只是独立导入，尚不能代替实际完整服务构建/启动、容器重启或真实 ONES 验收。

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
| `knowledge_verifier_unavailable` | 检查受信 ONES 部署配置；不要输入临时 URL 或改用共享凭据 |
| `knowledge_verification_failed` | 核对来源、索引与依赖服务；只查安全审计，不导出 Token/响应正文 |
| `knowledge_source_changed` | 完整离线批次或绑定目标已变化，需要在导入流程重新确认；不能沿用旧证明 |
| `knowledge_resource_unavailable` | 检查发布/启停状态和来源绑定；不切换未发布或旧索引作为 fallback |
| `knowledge_resource_changed` | 本次固定版本失效，放弃结果并重新发起查询 |
| `knowledge_bridge_unavailable` | 知识组件未装配；先完成可选部署与 MCP 接线，不临时绕过双身份桥 |
| `knowledge_bridge_identity_invalid` | 核对独立服务身份、当前 Knowledge Principal 和 Job/角色授权；不导出或复用历史 Token |
| `knowledge_readability_failed` | 检查当前授权、来源、ONES 身份和依赖服务；整批失败，不降级为零命中 |
| `knowledge_readability_busy` | 已达固定在途上限，稍后重试，不扩大候选数量 |
| `knowledge_cursor_invalid` / `knowledge_cursor_stale` | 从第一页重新发现；不要复用其他 Job、实例或旧权限下的游标 |
| `knowledge_source_identity_invalid` | 核验本人 ONES 身份、受信实例和默认 Team，不猜测其他 Team |
| `knowledge_search_busy` | 已有 4 个检索在途，稍后重试，不扩大服务内无界队列 |
| `knowledge_search_budget_exhausted` | 本次检索或当前 Job attempt 预算已耗尽；本次结果作废，不继续扩大候选 |
| `knowledge_search_dependency_failed` | 检查内部 Embedding/Qdrant 和安全审计；不能解释为零命中或改走外部服务 |

`POST /resources/{id}/status` 提交 `expected_revision` 和 `status`（enabled/disabled/archived）；归档不可重新启用。停用再启用会递增状态版本，旧在途调用仍失效。编辑未发布草稿不会改变正在使用的发布版本。

`POST /source-bindings/{id}/revoke` 只接受空 JSON 对象，幂等撤销绑定；所有引用该绑定的检索随后拒绝。撤销不删除历史证据或现有索引。来源换版和重新发布必须显式进行，不能由运行请求自动修复。

完整部署与回退继续遵守[可选知识部署说明](../../knowledge/README.md)和[本地索引运行手册](knowledge-local-vector-index.md)。合成/Mock 通过仅证明代码合同；真实 ONES、正式 PostgreSQL/服务部署、本地 Embedding 和已配置聊天模型的真实新 Job 须分别验收。
