# ONES 知识库采集、增量同步、补采与恢复

本入口把首次历史全量、常规创建日复查或明确日期补采，接到逐文档处理流程。缺陷、工单、需求各使用固定 collection；只为新增或变更文档分块、复用或编码向量、更新当前版本并删除该文档旧块。发布表示知识库可用，内容同步不重新发布。评论与附件不采集，受管写入仅使用同平台 PostgreSQL 和固定内网 Qdrant；外部内容连接继续只读。

三类 ONES 工作项（缺陷、工单、Story 及其子任务）先写入 `knowledge` 的候选修订。采集**不**请求评论、附件内容或图片，不下载文件，不单独修改当前知识库收录、Qdrant 索引、资源发布或角色授权。完整同步入口内部复用采集能力，不需要运维先跑一次仅到候选阶段的 CLI 再另跑一次同步。

## 网页运维与日常入口

优先使用“工具资源 → 知识库”或根目录 `knowledge.sh`；首次安装和计划字段见[运维手册](../../knowledge/OPERATIONS.md)。主 Compose 常驻 `knowledge_sync_worker` 轮询已启用计划；保存计划会停用采集；点击“开启自动同步”会立即调度首次全量或恢复未完成任务，完成后按完成时间加 14400 秒（4 小时）安排下一轮。不是每 4 小时拉起一次 daemon 容器。

```sh
./knowledge.sh status
./knowledge.sh sync --binding-code your-plan-code
./knowledge.sh backfill 2026-10-07 2026-10-26 --binding-code your-plan-code
./knowledge.sh logs --operation-id TASK_ID
./knowledge.sh retry --operation-id TASK_ID
```

同步/补采返回持久任务 ID，同来源任务串行排队。失败任务若仍有活动 run，重试原任务；补采不必手动停常驻调度器，也不修改七日创建日窗口。`status/logs` 读取运维投影，不等同于下面底层 CLI 的 `status/health` 输出。

网页调度器对可重试依赖错误总计最多尝试三次，部分失败、次数耗尽或确定性错误进入任务记录等待显式重试。底层 `--mode daemon` 仅作维护 CLI 的另一种调度方式（五分钟恢复循环），不与网页/常驻 worker 并行，也不作为主部署的常规触发方式。下文保留单次 CLI、一次性转换及定向维护步骤。

## 采集身份、来源范围与网络边界

- 仅在能访问真实 ONES 的目标环境运行；本机合成 Provider 测试不是正式 ONES 验收。
- PostgreSQL 必须处于当前 schema head。配置只保存来源范围与 `secret://platform/<code>` 凭据引用；不在 JSON、环境变量或日志里填写 Token。
- 凭据中心该引用解密后的内容是受管采集身份的 JSON 对象，仅有 `token` 与 `user_id` 两项。采集身份与 Knowledge MCP 的当前用户只读身份分离，采集权限不传递给检索用户。
- 执行 `collect_ones_knowledge` 的容器必须像 ONES MCP 一样挂载平台的只读 Master Key，并设置 `APP_CONFIG_MASTER_KEY_FILE` 指向容器内文件；CLI 会从该文件加载 Key，再解析凭据引用。文件缺失或格式、权限不合规时提前返回 `knowledge_collection_master_key_unavailable`，不会连接数据库或尝试 ONES；不得改用明文环境变量。同步入口的 `once` / 维护用 `daemon` 缺失或无效 Key 时返回 `knowledge_sync_master_key_unavailable`。仅查看 `status` 不要求加载 Key。
- 来源主机必须属于 `ONES_MCP_PROVIDER_ALLOWED_HOSTS`。HTTPS 始终可用；HTTP（包括生产环境）须显式设置 `ONES_MCP_PROVIDER_ALLOW_INSECURE_LOCAL=true`，并把目标主机加入允许列表。HTTP 会明文传输采集 Token 与业务数据，只能在可信网络边界内使用。单次 HTTP 请求最长 30 秒、响应最多 2 MiB，禁用代理与重定向。
- 本仓库的 [`ones-collector.example.json`](../../knowledge/ones-collector.example.json) 包含项目特定的 ONES 地址、Team、项目范围与类型 UUID；目标环境仍需提供对应允许列表和凭据中心引用。`resource_ids` 留空，不会自动首次发布知识资源或授予角色权限。
- 配置中的 `first_date` 必须覆盖全部需要收录工作项的创建日期；项目和类型 UUID 必须完整。Story 子任务通过 Story 详情列出的 UUID 单独取 `/info`，不是从父类型的列表推断。

网页可直接新建/配置计划，字段说明见[采集计划字段](../../knowledge/OPERATIONS.md#采集计划字段)。离线维护时，先复制并核对示例 JSON 中的非敏感来源范围。以下命令在后端运行环境执行，`<code>` 和文件路径由操作者明确填写；不要把凭据正文作为 CLI 参数传入。

```bash
python -m app.cli.collect_ones_knowledge --mode configure --binding-code <binding-code> --source-code <source-code> --configuration-file <collector.json> --expected-revision 0 --commit
python -m app.cli.collect_ones_knowledge --mode status --binding-code <binding-code>
python -m app.cli.collect_ones_knowledge --mode enable --binding-code <binding-code> --expected-revision <status返回的修订号> --commit
python -m app.cli.collect_ones_knowledge --mode once --binding-code <binding-code> --commit
python -m app.cli.collect_ones_knowledge --mode disable --binding-code <binding-code> --expected-revision <status返回的修订号> --commit
```

`configure` 新建或修改后始终停用；修订号需按 `status` 的结果进行 CAS。`once` 仅在显式启用后运行，失败可用相同活动 run 重放未完成日期，逐条候选按内容哈希幂等。`status` 只输出安全计数、日期进度和固定错误码；`cancel --run-id <id> --commit` 仅适用于允许取消且无人持有来源锁的 run；增量模式已进入派生处理后必须恢复原 run，不能取消并丢弃已应用步骤。

底层 `disable` 会使后续批次/日期检查因采集停用而停止；网页“暂停自动同步”只暂停后续定时触发，不取消正在运行的任务；已发出的单个请求最多等待既定 30 秒。详情请求最多 16 路并发；仅对限流和暂时不可用做有界重试，身份/范围/内容冲突不重试。每个创建日先完成全部类型、所有页与 Story 子任务核对，才把下一日期与累计数量同事务写入检查点。重启后跳过已完成日期；未完成日期重新枚举，已提交候选按 UUID 幂等复用。完成整轮前不清洗、索引或发布部分结果。

`collect_ones_knowledge --mode once` 结束于 `STAGED` 候选；后续清洗分块、Embedding 及逐文档向量应用使用本手册的 `sync_ones_knowledge --mode once` 或网页/`knowledge.sh` 同步任务。未完成这些阶段前，不能把候选计数当作当前可检索内容。保存配置不会启动采集；启用调度前应核对凭据、索引接管与来源配置，真实 ONES 的过滤、排序、项目范围及版本戳合同仍需在目标环境单次运行验收后才可授权调度。

### 创建日窗口与失败边界

首次运行从 `first_date` 按北京时间创建日逐日完整枚举。首次成功激活后的常规刷新（完成时间加 14400 秒）只复核**当天及此前 6 个自然日创建**的根工作项，并重新读取这些 Story 的子任务。此策略不是“按更新时间增量”：更早创建的根项即使后来更新，也不会被本轮刷新。

重复页、游标无进展、计数漂移、空页、详情 ID/类型/项目冲突、单日单类型达到 1000 项、总量超过 200000、首次全量来源为空、扫描范围内已有根项不可见，均使本轮保持未完成；绝不因缺席推断删除。后续 7 天创建日窗口允许没有新项。更早创建的根项及其子树被明确排除在常规刷新范围外；若需要补录这些更新，使用 `knowledge.sh backfill` 或同步 CLI 的明确创建日期补采，见[按明确创建日期补采](#按明确创建日期补采)。401、403、404、限流、Provider 不可用与响应过大分别记录固定错误码，不回显原始响应。

## 启用前

1. 在目标环境按平台维护流程升级到当前 schema head（包含迁移 150 的复用索引、151 的文档断点、152 的网页运维及 153 的四小时间隔）及匹配的配套服务、API、ONES/同步镜像。迁移版本统一管理，不能只更新同步容器导致其他服务 schema 断言不匹配。真实 ONES 验收按目标环境单独记录，不从仓库文档推断已具备采集权限。
2. 按上文准备固定 Provider、Team、项目/类型 UUID 与受管只读采集身份。`knowledge/ones-collector.example.json` 的来源和三库映射决定采集范围；`resource_ids` 不会自动发布知识资源或授予角色权限。重新 `configure` 会停用绑定并清除旧资源钉住值，需重新显式启用。
3. 确认采集写入目标采用同平台 `knowledge` 内容库；已有内容须先完成下述一次性索引转换。管理员草稿或资源停用不会停止内容采集。外部内容 PostgreSQL 仍可用于在线只读知识资源，但不能被此同步入口自动写入。Qdrant、Embedding、容量路径必须可达；容量不足只暂停候选，不删除旧索引/卷。
4. 先在真实 ONES 目标环境完成一次明确单轮采集与分页/版本/权限验收，再决定是否启用自动同步。合成 Provider、本地 Embedding/Qdrant 和容器健康均不替代真实验收。

## 已有索引的一次性转换

停止旧同步进程并停用绑定。旧活动 run 须先完成或显式取消；每个已有内容的 KB 指定其当前 READY 索引，逐个执行：

```sh
python -m app.cli.adopt_incremental_knowledge --binding-code <binding-code> --index-code <当前索引编码> --actor-id <有效管理员ID>
python -m app.cli.adopt_incremental_knowledge --binding-code <binding-code> --index-code <当前索引编码> --actor-id <有效管理员ID> --commit
```

第一条只读预检；第二条逐点验证 payload、模型维度、稀疏向量和数据库账本，添加检索可见标记，再在短事务中登记增量模式和新的资源配置修订。预检要求与在线 keep_ids 分块和当前 Embedding profile 一致；旧模板或模型不同须先显式重建，不能伪装为兼容。保留 collection、点 ID、向量数值、文档及资源启停状态；已有草稿也保留为草稿。转换不调用 Embedding、不自动开启采集或扩大授权。期间目标库查询可能暂时失败，应在维护窗口操作；中断后用相同参数重跑。所有非归档资源的当前发布/草稿须指向该索引及同平台默认连接，否则拒绝转换。空的新 KB 在首次文档处理时自动建立固定集合，首次发布仍由管理员操作。

转换完成后更新匹配的 API、Knowledge MCP 和同步镜像，再启用绑定。若使用独立 `knowledge_mcp_reader` 账号，按既有 `services.knowledge_mcp_server.provision_database` 维护流程刷新列权限，新增读取列为 `knowledge.vector_index.incremental`。`knowledge_sync_migration_required` 表示仍有旧活动 run 或未转换的已有内容库，不能靠删除向量或重启绕过。

## 单次执行与恢复

`configure`、`enable`、`disable`、`cancel` 仍使用 `app.cli.collect_ones_knowledge`。绑定开关控制采集，资源发布/停用控制检索，两者独立；固定索引的模型、分块和来源身份必须匹配。CLI 的 `enable` 和网页“开启自动同步”都将首次到期时间设为当前时刻。明确单次执行不需要等待。

```sh
python -m app.cli.collect_ones_knowledge --mode status --binding-code <binding-code>
python -m app.cli.collect_ones_knowledge --mode enable --binding-code <binding-code> --expected-revision <当前修订> --commit
python -m app.cli.sync_ones_knowledge --mode status --binding-code <binding-code>
python -m app.cli.sync_ones_knowledge --mode once --binding-code <binding-code> --capacity-path /qdrant/storage --commit
```

容量路径须是同步进程可见的 Qdrant 数据卷路径；`once` 只使用已配置的受管 Secret 引用，不接受 Token 或密码 CLI 参数。每篇文档保留 `PENDING → APPLIED → DONE` 断点：准备块/隐藏向量、应用当前版本、开放新块并清理旧块。重启跳过 DONE，未完成步骤按稳定点 ID 恢复。`status` 仅输出安全 ID、阶段、计数和错误码；新增 `documents.total/completed/failed` 和 `content_status`。部分失败返回 PARTIAL，单次命令非零退出；维护用 `daemon` 每五分钟重试原 run，网页/常驻 worker 按上文规则记录任务并重试；其他成功文档已可检索。未解决的失败仍占用该来源活动 run，排查后继续，不累积多轮。

无变化轮次只记录来源观察和完成水位，不分块、编码、写向量或发布。文档跨库移动只影响该文档在两库的点，空库保留原集合。现有 run 阶段字段保留，`ACTIVATED` 现在表示本轮全部文档处理完成，不代表发布动作。向量与数据库没有跨存储事务：单篇在开放新点前允许短暂缺失，旧修订经当前版本校验被排除；隐藏点不占用检索候选。Knowledge MCP 保留当前 KB 授权和个人 ONES 权限校验及最多 360 秒/Job 剩余预算；[主规格差异](knowledge-governance.md#实现与主规格差异)仍单独保留。

### 按明确创建日期补采

仅在已完成首次全量的来源上使用 `--mode once --from-date ... --through-date ...`，两参数必须同时给出。范围是北京时间的**创建日闭区间**，不得早于绑定 `first_date`、晚于执行当天或逆序；这不是更新时间补扫。范围冻结到 run 的 manifest，状态显示 `mode=backfill`。普通每 4 小时七日创建日策略、绑定配置、凭据和授权不变，不需要先重新 configure/enable。

先通过既有 `status` 确认活动 run。如果旧补采仍有进展，优先完成原 run，不取消重建。旧整代 run 必须在升级前完成，或停止旧写者后显式取消再转换；新入口对旧 run 返回 `knowledge_sync_migration_required`，不混用两种合同。新版 backfill 必须使用相同日期恢复；维护用 `daemon` 或另一个范围接续它会返回 `knowledge_collection_range_changed`。

日常补采优先提交 `./knowledge.sh backfill` 或网页任务，由常驻 `knowledge_sync_worker` 与运维队列串行执行，不必停用绑定。仅在明确维护窗口、且需手工跑同步 CLI 时，先停止常驻同步进程（不 disable 绑定，否则 once 也会被拒绝），再用根 `docker-compose.yml` 单次执行：

```sh
docker compose -f docker-compose.yml \
  stop knowledge-sync

docker compose -f docker-compose.yml \
  run --rm --no-deps knowledge-sync \
  python -m app.cli.sync_ones_knowledge --mode once --binding-code your-binding-code \
  --from-date 2026-10-07 --through-date 2026-10-26 \
  --capacity-path /qdrant/storage --commit
```

中断后原样重跑第二条命令，从原阶段/日断点恢复；不能修改日期、删除候选或绕过配置校验。确认该 run 为 `ACTIVATED` 后，再恢复常驻同步进程：

```sh
docker compose -f docker-compose.yml \
  up -d --no-deps --no-build knowledge-sync
```

增量同步不冻结全库成员，不创建新代集合，不复制未变更文档的点，也不做全库向量核验。按文档及最多 32 点一批检查和写入；相同文本 hash 优先复用已有向量。创建日枚举仍须覆盖所选窗口，耗时不能只看新增条数。全库核验仅用于显式维护，不承诺补采在固定分钟数完成。

### 停采检测与进度

`status` 新增 `health`，活动摘要新增 `progress` 和 `updated_at`。派生阶段每十五秒节流记录当前文档的 `reused/encoded/verified`，每篇完成更新持久断点和时间；总文档完成数见 `documents`，不能将单篇计数当全库计数。`health` 模式只读 PostgreSQL/schema，不加载 Master Key、不访问 ONES 或执行采集/激活：

```sh
python -m app.cli.sync_ones_knowledge --mode health --binding-code your-binding-code
```

停用不告警；首次绑定有两个同步周期宽限。已启用后最近成功激活或活动进度超过两个周期未更新，或最新运行失败时，health 返回非零，并以固定 `knowledge_sync_success_stale` / `knowledge_sync_progress_stale` / `knowledge_sync_run_failed` 标明原因。长时间首次全量或补采超过该阈值也可能被标为陈旧，应结合进度判断，健康检查不会取消正在执行的补采。

主 Compose 的受管同步进程（`knowledge-sync` → `app.cli.knowledge_sync_worker`）采用 `unless-stopped`，每二十秒检查心跳，三次失败标记 unhealthy。监控仍须核对计划最近成功和运行进度；心跳正常不证明采集成功，不自动发送钉钉或邮件告警。

### 采集或同步期间重启 PostgreSQL

`collect_ones_knowledge --mode once`、`sync_ones_knowledge --mode once` 和维护用 `--mode daemon` 均自动恢复数据库瞬时断连，启动时数据库尚未就绪也会等待。检测失败后按 **5 → 10 → 20 → 40 → 60 秒**退避，随后每次最多等待 60 秒，无总次数上限；数据库连接检测本身有独立超时，不包含在这些等待秒数中。不需要反复手工启动采集或重新配置 binding。

- 每次重试关闭旧连接并重新装配，严格校验 schema、绑定配置和启用状态，重新取得 worker/source 排他锁，恢复原 run 和持久阶段。
- 未完成的创建日会重新枚举，已 staged UUID 不重复拉详情或生成重复候选；仅完整一天才推进日游标。分块/索引恢复原文档步骤；提交完成但响应丢失时读取原成功事实，不重复编码已验证点。
- 密码/身份、数据库名、权限、TLS 配置、schema 不匹配、配置/资源变化及业务数据校验错误不作为数据库断连循环重试。应处理错误原因后显式重跑；不会回退其他库、绕过校验或删除旧数据。
- 等待期间可用 Ctrl+C 或容器 SIGTERM 停止；恢复后若发现 binding 已停用或原 run 已取消，不继续采集。数据库不可用期间无法读取库内开关，需要立即停止时使用进程/容器停止信号；在途请求仍受现有超时约束。已提交断点保留。

重试日志只输出固定 `knowledge_collection_database_retry_pending` / `knowledge_sync_database_retry_pending` 事件、`knowledge_database_temporarily_unavailable` 错误码、次数和下次等待秒数，不输出底层异常、连接串或业务正文。本能力不改变计划开关和每 4 小时触发设置；更新代码后需重建并应用新镜像，单纯 restart 不会装入新代码。日常使用 `./knowledge.sh build` 后 `./knowledge.sh up`（经 `knowledge-ops-controller`）；定向维护也只使用主文件：

```sh
docker compose -f docker-compose.yml build knowledge-sync
docker compose -f docker-compose.yml up -d --no-deps --force-recreate knowledge-sync
```

知识运维入口不自动重启主程序 PostgreSQL；数据库维护仍按主程序流程执行。

## 主部署的受管调度器

`knowledge-sync` 默认随根 `docker-compose.yml` 启动，运行常驻 `knowledge_sync_worker`，使用平台数据库、受管 Master Key 和共享状态卷。运维任务经 `knowledge-ops-controller` 与 `knowledge.sh` / 网页提交。仅已启用的计划才执行采集；启动容器不改变 `enabled` 或 `schedule_enabled`，不创建新计划。不再配置单绑定 `KNOWLEDGE_SYNC_BINDING_CODE`、独立 `KNOWLEDGE_SYNC_DATABASE_DSN`，也不再叠加 `mcp.compose.yml` / `sync.compose.yml` 等独立 Compose。

回退/维护先停止同步进程并保留已发布索引与数据卷，核对活动 run 的错误码后按固定范围恢复。已开始派生处理的 run 不直接取消；日期补采优先使用持久队列。手动 once 仅在调度器已停止的明确维护窗口执行，不能并行运行维护用 `daemon` 或 cron。

## 同时间戳内容变化的处理和日志

受管在线增量同步按内容判变：来源时间戳相同但内容不同，直接采用本次采集 B 创建本地修订；该文档派生完成后 B 成为当前版本，A 留作历史。不伪造或增加 `server_update_stamp`，也不为这一差异再次请求 ONES。更旧时间戳仍按 stale 保留当前内容；内容相同只更新观察状态，不再分块或写向量。此规则不改变离线文件导入的冲突校验。

语义摘要包含标题、正文、类型、业务属性、显示名称及工作项关联，排除归一化版本和采集完整性等运行元数据；仅对明确无序的产品 ID 和关联集合规范化顺序。若 ONES 在相同时间戳下交替返回不同内容，将按实际采集到的内容创建修订，可通过下面的日志定位。

`collect_ones_knowledge` 与 `sync_ones_knowledge` 输出 JSON 事件 `knowledge_source_same_stamp_revised`：

- `run_id`、`source_id`、`document_id`、`external_id`：定位运行与单据。
- `old_stamp`、`new_stamp`：保留原始来源时间戳；该事件中两者相同。
- `old_semantic_hash`、`new_semantic_hash`、`old_kind`、`new_kind`：说明内容或分类变化，不输出业务值。
- `old_revision_id`、`new_revision_id`：定位保留的旧修订与本次修订。
- `phase=STAGED`：页面事务已提交，候选已保存，尚不表示当前版本生效。
- `phase=DONE`：该文档当前版本已应用、新向量已开放且旧向量已清理。
- `outcome=revised`、`reason=same_source_stamp_content_changed`：固定处理结果与原因。
- `event_id`：同一运行、单据和阶段的稳定事件 ID；日志重放可据此去重。

日志不包含标题、正文、业务字段值、凭据或底层异常文本。日志与数据库不做跨系统原子提交，进程在提交后、输出前退出可能缺失事件，恢复状态以数据库持久断点为准。业务格式、枚举、数据库或配置错误仍按既有规则处理，本改动不宣称隔离全部采集错误。

此补充不增加 schema migration。已经迁移到 151 并使用增量模式的环境需部署匹配代码后恢复原活动 run；仅 restart 旧镜像不能获得新规则。尚未转换增量模式的环境仍先按本手册完成转换。
