# 版本化业务代码知识：部署与使用

本地实现已接通源码准入、固定快照、内部 Job、Runtime 只读挂载、候选核验、快照隔离索引及四个知识 MCP 工具，也包括 SVN 每日采集、历史按需构建和现场版本绑定。已通过合成数据与隔离 PostgreSQL/SVN/Qdrant 验证。2026-11-06 已部署到本地现有服务并开始真实模型提取，但候选仍在核验，知识尚未发布，目标 SVN 尚未验收。不能据此宣布生产知识库已可用。进度和欠账见 `openspec/changes/add-versioned-code-business-knowledge/tasks.md`，实际执行记录见该变更的 `evidence/real-extraction-readiness.md`。

来源固定为同项目分支的 `set_server`（后端）、`set_web/EBR`（工厂端）、`set_web/JTH`（集团端）。当前本地包的 SVN revision 未知。其他前端不纳入。

## 准入本地源码

部署人员先执行只读预检，命令只输出计数、摘要和排除原因，不输出源码正文：

```sh
python -m app.cli.import_code_baseline \
  --source-root /deployment/mes-project
```

准备好已迁移 PostgreSQL 后，显式冻结基线：

```sh
python -m app.cli.import_code_baseline \
  --source-root /deployment/mes-project \
  --snapshot-root /deployment/code-knowledge/sources \
  --local-root-key mes-current --source-code mes-code \
  --base-code mes-business-rules --commit
```

宿主路径只由部署 CLI 接收，不是模型或 Web API 参数。源码原目录保持只读。保存原始字节、UTF-8 阅读表示、编码与两种摘要；编码未知或二进制文件保留明确排除项，不能当作空文件或已分析。内容稳定性、清单变化或容量核验失败会拒绝提交。知识库初始为 `storage_only`，不会自动开放查询或授予权限。

来源卷默认上限 8 GiB、100 个快照，达到边界时拒绝新导入。同一配置、同一来源清单重复导入复用尚未退役的身份。源码默认保留至少 30 天，不自动删除；通过部署 CLI `python -m app.cli.retire_code_source --snapshot-root /deployment/code-knowledge/sources --source-snapshot-id <id>` 预检，添加 `--commit` 才删除字节。未完成构建或未确认停止的 Invocation 会阻止清理。知识修订与证据定位继续保留，但返回 `source_evidence_status=retired`；重新提取需要显式精确导入并分配新来源快照，不复活已到期目录。

## Runtime 目录映射

主 Compose 已映射两个独立目录：

| 目录 | Runtime | Worker |
| --- | --- | --- |
| `CODE_SOURCE_SNAPSHOT_HOST_ROOT` → `/var/lib/code-knowledge/sources` | 只读 | 只读 |
| `code-extraction-artifacts` → `/var/lib/code-knowledge/artifacts` | 写入固定 Invocation 产物 | 只读回收 |

`CODE_SOURCE_SNAPSHOT_HOST_ROOT` 应指向上述 CLI 的 `--snapshot-root`，不能指向会被 `svn update` 修改的工作副本。来源文件允许容器 UID 读取，卷保持只读；SDK 仍逐次限制到当前 Job 的确切快照与获准前缀。普通 Job 无法读取该卷。

默认不启用 Runtime 源码身份。启用前应配置独立 bootstrap 凭据文件，仅让 API Server 和 Runtime 使用；配置 `CODE_RUNTIME_BOOTSTRAP_TOKEN_HOST_FILE` 后，部署时附加 `docker-compose.code-knowledge.yml`。凭据内容不要放进命令、日志或模型输入。新身份只允许调用元数据授权入口，不能调用 File Service，也不增加 Runtime 的数据库权限。

## 提取与回收合同

提取配置必须固定已发布的 Agent/Application、模型连接和 `extract-business-knowledge` Skill，以及已获得该应用业务权限的服务账号。不要自动授予管理员权限。`CodeExtractionJobs.dispatch` 从持久工作单元构造标准 Job，固定内部来源标识，明确 `reply_route=none`，通过标准 Outbox 调度。可选 Compose 覆盖文件启用 `job-dispatch-worker` 的构建 tick；主 Compose 默认关闭。当前独立 tick 负责已登记构建的单元派发、回收、依赖扩展、校验汇总、有界向量写入与条件激活；不阻塞普通 Job Outbox，不负责 SVN 日计划。

入口定位器为六类首期入口生成持久单元；词法定位只是导航提示，不能当作规则提取。每来源最多一个活动构建、一个执行中单元，每构建最多 24 个单元、提取阶段 24 小时，仍受发布应用的 Job/工具预算限制。具体文件扩展请求只能落在已准入和批准的路径内，每个入口最多两轮。构建租约接管不会改变原 Job/Invocation 产物身份，也不会为未知执行结果创建第二个模型任务。

Runtime 为该 Job 提供：

- `inputs/code-contract.txt`：authoring JSON Schema、固定 manifest 和服务器指定的 `source_access.read_root`。
- `read_root/<允许的相对路径>`：固定只读快照，每个文件旁有 `.evidence.txt` 元数据；普通 Job 不获得该根目录权限。
- `outputs/candidate.txt` 与 `outputs/report.md`：候选与报告固定输出。

模型填写语义内容、文件身份和证据行号，将 `excerpt_hash` 留为 `null`。Runtime 根据核验后的源码计算证据哈希和封装摘要，不要求模型计算哈希。Read 每次最多 400 行／64 KiB，Glob/Grep 最多 100 个定位项；单文件 Grep 的 content 模式最多 40 条带行号匹配，并提前检查最坏输出不超过 64 KiB。Write/Edit 只允许 outputs；candidate.txt 必须用 Write 提交完整对象，写入前检查结构、唯一身份、引用和证据，错误返回给当前模型修复；结束回收和 Worker 仍独立复验。所有操作和产物提交均复查当前账号、应用、Job、Invocation、配置及租约。

SDK 的 Grep/Glob 在 PreToolUse 钩子前检查物理路径，因此必须使用合同中的 read_root；虚拟 `source/...` 只兼容 Read。不能依赖虚拟路径改写使原生搜索成功，也不能用放开目录权限解决。候选证据路径仍使用来源相对路径，跨快照、范围外和写入源码均拒绝。

只有 SDK 成功返回后才在清理沙盒前原子保存产物。`CodeArtifactCollector.collect` 需要 Job 成功、确切 Invocation 成功且已经停止执行，再独立检查来源、摘要、证据、关系及覆盖并导入候选。未知结果、失败或迟到结果不得自动变成知识发布。重复回收复用已持久结果。

结构校验与业务核验分开：`machine_valid=true` 不代表业务正确；`business_verified` 初始仍为 false。普通运行审计不记录提取 SDK 消息、源码或原始模型请求响应，只保留身份、运行状态、用量和工具事件元数据。整个源码及候选流程不使用 File Service。

## 索引与版本问答

结构化知识修订是权威来源。检索说明按固定投影生成，向量点 ID 固定到快照、修订和片段，同内容可以复用 Embedding 缓存。缓存点不参与召回。每批写入后保存检查点，核验全部预期点和总数后才能 READY；历史 READY 不自动激活开发快照。

新 Publication 可显式选择 `code-business-query` 及四个知识工具：目录、检索、完整业务详情、版本比较。搜索未指定版本时返回 `VERSION_REQUIRED` 和已就绪的本地基线 ID；未构建 revision 返回 `BUILD_REQUIRED`。只有明确请求最新时使用 `latest_verified`。查询来源不需要 ONES 身份，ONES 的 online/offline 行为保持原部署策略。

搜索只返回定位片段、覆盖和有界证据；详情返回完整根规则与同快照依赖，默认三层、一百节点，分页、循环或未展开项明确标注。compare 只比较两个端点；history 根据完整提交账本核对中间版本。r100→r101→r102 的两次反转可以返回，账本或中间快照缺失时不会猜测精确提交。

启用按需策略后，搜索或比较缺失的精确 SVN 版本可登记持久补建需求，返回 `BUILD_PENDING` 和需求标识。未启用策略、队列满或不可用时明确返回原因；不在问答 Job 内等待模型构建。history 持久保存已检查版本和未决区间；基线以前的区间可独立采集账本，不修改开发采集游标。仅采到日志不等于已证明规则变化，相关版本仍需完成提取及独立核验。每来源最多 20 个待处理版本；历史 READY 不自动改变开发或现场绑定。

这些需求通过现有知识 MCP 服务身份和当前 Job Business Principal 调用固定控制面接口，逐次校验当前权限、发布资源和预算。MCP 数据库角色保持只读，不获得源码、需求或核验记录写权限。

单次 history 最多跨度 10,000 个 revision、检查 50 个相关版本；更长历史需按共同边界拆分区间查询。超限或不完整不会返回“没有变化”的结论。同一 SVN revision 存在多个已就绪处理版本或不同 external 组合时返回版本歧义，不静默选择一个。

## SVN 登记与每日更新

部署人员维护独立 JSON 登记文件；下面都是占位示例，不包含凭据。组件路径相对同一分支根目录。`auth_ref` 仅引用部署认证根目录下的既有目录；部署系统负责配置受限读取身份和认证材料，不通过 Web、模型或命令参数传递密码。

```json
{
  "mes-main": {
    "branch_url": "https://svn.example.invalid/mes/trunk",
    "repository_uuid": "replace-with-verified-repository-uuid",
    "branch_path": "/trunk",
    "auth_ref": "mes-readonly",
    "components": {
      "backend": "set_server",
      "factory_frontend": "set_web/EBR",
      "group_frontend": "set_web/JTH"
    },
    "externals": {}
  }
}
```

有业务 external 时，在 `externals` 内以其分支相对挂载路径为键，登记该外部根的 `branch_url`、`repository_uuid`、`branch_path`、`auth_ref`。只有位于三个组件内且显式允许的 external 可准入；当前采集会固定实际 revision。历史浮动 external 无法证明当时版本时保持不完整，不能用今天 HEAD 补写历史。嵌套 external 未支持自动递归准入，会阻止完整性通过。

先对已登记来源和明确 revision 预检：

```sh
python -m app.cli.register_code_svn \
  --registry /deployment/code-knowledge/sources.json \
  --auth-root /deployment/code-knowledge/svn-auth \
  --snapshot-root /deployment/code-knowledge/sources \
  --source-id <registered-source-id> --registration-key mes-main \
  --revision <verified-revision> --local-snapshot-id <local-source-snapshot-id>
```

核对结果后加 `--commit` 才写入登记。只有同范围文件、原始/表示摘要和排除清单相符才记录 `VERIFIED` 映射；本地来源身份仍保留。无法映射时，明确加 `--establish-origin` 建立新的 SVN 起点，不把本地包伪装成某个 revision。更改登记文件会导致摘要漂移，必须重新预检登记，不能混用旧配置游标。

网络采集单独选择 `docker-compose.code-svn.yml`，与主 Compose 及 Runtime 覆盖文件合并。部署变量：

| 变量 | 内容 |
| --- | --- |
| `CODE_SOURCE_SNAPSHOT_HOST_ROOT` | 已准入快照目录，采集进程可写；Runtime 和 Job Worker 只读 |
| `CODE_SVN_REGISTRY_HOST_FILE` | 上述登记 JSON 文件，只读挂载 |
| `CODE_SVN_AUTH_HOST_ROOT` | 受管认证引用目录，只读挂载 |
| `CODE_RUNTIME_BOOTSTRAP_TOKEN_HOST_FILE` | Runtime 专用凭据文件，只作为 Secret 挂载 |

先由既有 Migrator 升级到当前 schema head（本变更为 154），发布提取应用并授予服务账号所需权限，再配置目录属主/读写权限。采集镜像为现有 `ones-mcp`/`knowledge-sync`，包含 SVN 客户端，临时目录上限 768 MiB；Job Worker 不执行 SVN。默认部署不会启用网络采集或后台提取。

管理页保存独立代码更新计划，默认时间为 `02:00 / Asia/Shanghai`，显式勾选每日采集和按需历史策略。计划绑定已发布提取配置，并通过版本校验拒绝覆盖他人修改。暂停每日计划不会取消已经登记的固定目标任务；取消按需策略也不会删除已授权排队任务。ONES 原有四小时策略不变。

每轮先固定 HEAD，按 100 个 revision 区间保存提交事实及游标，再冻结获准文件。保存 A/M/D/R、复制来源和属性变化，不存提交消息。中途出现新提交留待下轮；在忙时合并后续目标，保留完整账本。无主仓库新提交也重新核对 external。

首期采用保守的完整业务范围重建：工厂工单发布/启动/报工和集团应用启停/授权，每轮合并旧知识身份、旧反向依赖与新入口/引用扫描。暂不按少量 diff 猜测哪些规则可以直接沿用。旧知识未出现在新候选中时阻止激活；只有带核实证据的明确删除并完成业务核验才允许移除。这会增加提取成本，实际耗时与成本需真实环境验收。

## 管理与独立核验

知识管理页新增“代码业务知识”面板。已准入快照、提取应用发布 ID 和服务账号 ID 是启动输入，不接收宿主路径或 Shell。后续执行仍通过现有服务账号授权、冻结 Publication、Runtime 池和 Job 预算。

管理员可分页查看完整候选规则、关系、证据定位与单元状态；独立业务核验需记录外部核验编号并确认全部有效单元。确认绑定处理配置、候选摘要与 Runtime 产物摘要；候选变化使核验失效，模型无法设置业务核验通过。

失败重试保留成功的 Job、产物和向量检查点。未确认停止的 Invocation、失败模型任务或已就绪快照不能通过此入口重复运行；配置改变需明确创建新的构建。完整快照回滚使用预期当前指针校验，已 READY 的历史快照可显式设为开发查询目标。

来源计划区域展示 SVN 已核验/本地未映射、采集起点、固定目标、下次运行及失败原因。管理员可预构建精确版本、恢复失败采集，以及将已就绪 SVN 知识快照绑定到明确现场标识。绑定只表达查询版本，不执行 MES 发布或升级。开发快照更新不会自动改变现场绑定。历史需求和规则区间进度来自持久记录，刷新页面可继续观察。

采集子进程有超时、输出上限和停止信号；整个来源准入最长 30 分钟。失败采集保留目标与游标，由管理入口重试。源码/产物限额、关键 unknown、未停止模型执行或未通过独立核验都不会自动绕过。真实联调前仍需要：已发布提取应用及 Agent、服务账号标识、目标 SVN 登记与认证引用、业务核验负责人和固定验收问题；不要在聊天中提供密码、Token 或模型 Key。
