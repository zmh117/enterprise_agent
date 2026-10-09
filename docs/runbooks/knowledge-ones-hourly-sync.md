# ONES 知识库受管同步（默认停用）

本入口把首次历史全量或后续最近 7 个创建日的完整枚举、候选修订、分块、本地 Embedding/Qdrant 索引和原子激活串成一轮。缺陷、工单、需求共用来源身份，按三个知识库分别建候选索引；评论与附件不采集。只有内容与平台治理同在一个 PostgreSQL 时允许自动换版。已发布资源必须在绑定中明确列出，管理员草稿、停用、连接或模型变化会阻止激活；没有已发布资源的新库只准备内容和 READY 索引，不自动首次发布或授权。

## 启用前

1. 在目标环境按平台维护流程升级到当前 schema head（包含迁移 146）及匹配的 API、ONES/同步镜像。当前本机没有真实 ONES，本手册不是启用授权。
2. 按[全量采集手册](knowledge-ones-full-collector.md)准备固定 Provider、Team、项目/类型 UUID 与受管只读采集身份。`knowledge/ones-collector.example.json` 中 `resource_ids` 列出允许自动换版的**现有已发布**知识资源 ID；未发布的工单/需求 KB 不填资源 ID。重新 `configure` 会停用绑定并清除旧资源钉住值，需重新显式启用。
3. 确认这些资源采用同平台 `knowledge` 内容库，已发布配置为 KB 范围摘要版本，且没有管理员草稿。外部内容 PostgreSQL 仍可用于在线只读知识资源，但不能被此同步入口自动写入。Qdrant、Embedding、容量路径必须可达；容量不足只暂停候选，不删除旧索引/卷。
   单轮 `once` 和每小时 `daemon` 都必须从 `APP_CONFIG_MASTER_KEY_FILE` 读取与平台相同的只读 Master Key；缺失或无效时返回 `knowledge_sync_master_key_unavailable`，不会开始同步。仅查看 `status` 不要求加载 Key。
4. 先在真实 ONES 目标环境完成一次明确单轮采集与分页/版本/权限验收，再决定是否启用每小时入口。合成 Provider、本地 Embedding/Qdrant 和容器健康均不替代真实验收。

## 单次执行与恢复

`configure`、`enable`、`disable`、`cancel` 仍使用 `app.cli.collect_ones_knowledge`。开启绑定时冻结资源发布修订、连接和 profile；异库内容、未发布/停用资源或未列入绑定的已发布资源会在启用前拒绝。`enable` 后第一次自动到期在 3600 秒后；明确单次执行不需要等待它。

```sh
python -m app.cli.collect_ones_knowledge --mode status --binding-code <binding-code>
python -m app.cli.collect_ones_knowledge --mode enable --binding-code <binding-code> --expected-revision <当前修订> --commit
python -m app.cli.sync_ones_knowledge --mode status --binding-code <binding-code>
python -m app.cli.sync_ones_knowledge --mode once --binding-code <binding-code> --capacity-path /qdrant/storage --commit
```

容量路径须是同步进程可见的 Qdrant 数据卷路径；`once` 只使用已配置的受管 Secret 引用，不接受 Token 或密码 CLI 参数。失败保留同一 run 的候选与阶段，重跑 `once` 先恢复；不会为同一候选反复建 collection。`status` 只输出安全 ID、阶段、数量和错误码。若停在 `INDEXING`，确认容量/依赖后重跑；若停在 `VERIFIED`，仍会重新核对索引、资源与当前内容再激活。配置或资源已改变时必须先排查并显式重新配置，不允许强行跳过 CAS。

无变化轮次只更新来源观察和激活水位，不重新分块、编码或发布；经完整来源确认的类型迁移可以产生空知识库 READY 代际。激活在同平台 PostgreSQL 短事务内一起切换受影响内容、资源发布指针及水位。提交后调用方失联可从 `ACTIVATED` 恢复成功事实；事务前失败继续保留上一可用版本。Knowledge MCP 仍按应用角色知识库授权和当前用户 ONES 可读权限双重检查，单次检索在版本切换时失败并要求重试，最多 120 秒。

### 采集或同步期间重启 PostgreSQL

`collect_ones_knowledge --mode once`、`sync_ones_knowledge --mode once` 和后台 `--mode daemon` 均自动恢复数据库瞬时断连，启动时数据库尚未就绪也会等待。检测失败后按 **5 → 10 → 20 → 40 → 60 秒**退避，随后每次最多等待 60 秒，无总次数上限；数据库连接检测本身有独立超时，不包含在这些等待秒数中。不需要反复手工启动采集或重新配置 binding。

- 每次重试关闭旧连接并重新装配，严格校验 schema、绑定配置和启用状态，重新取得 worker/source 排他锁，恢复原 run 和持久阶段。
- 未完成的创建日会重新枚举，已 staged UUID 不重复拉详情或生成重复候选；仅完整一天才推进日游标。分块/索引继续原候选代际，激活已提交但响应丢失时读取原成功状态，不重复发布。
- 密码/身份、数据库名、权限、TLS 配置、schema 不匹配、配置/资源变化及业务数据校验错误不作为数据库断连循环重试。应处理错误原因后显式重跑；不会回退其他库、绕过校验或删除旧数据。
- 等待期间可用 Ctrl+C 或容器 SIGTERM 停止；恢复后若发现 binding 已停用或原 run 已取消，不继续采集。数据库不可用期间无法读取库内开关，需要立即停止时使用进程/容器停止信号；在途请求仍受现有超时约束。已提交断点保留。

重试日志只输出固定 `knowledge_collection_database_retry_pending` / `knowledge_sync_database_retry_pending` 事件、`knowledge_database_temporarily_unavailable` 错误码、次数和下次等待秒数，不输出底层异常、连接串或业务正文。本能力不改变默认停用和每小时触发设置；更新代码后需重建并重新创建同步容器，单纯 restart 不会装入新代码：

```sh
docker compose -f docker-compose.yml -f knowledge/compose.yml -f knowledge/sync.compose.yml --profile knowledge --profile knowledge-sync build knowledge-sync
docker compose -f docker-compose.yml -f knowledge/compose.yml -f knowledge/sync.compose.yml --profile knowledge --profile knowledge-sync up -d --no-deps --force-recreate knowledge-sync
```

以上仅用于已启用采集的目标环境，本轮不自动启用本机采集或重启业务数据库。

## 可选每小时容器

只在真实环境单次验收和独立启用授权后加载 `knowledge/sync.compose.yml`。必须同时设置 `KNOWLEDGE_SYNC_ENABLED=true`、固定 `KNOWLEDGE_SYNC_BINDING_CODE`、平台写入用 `KNOWLEDGE_SYNC_DATABASE_DSN`，并保持数据库绑定 `enabled=1`。受管主密钥由现有 Compose Secret 挂载，不在本文件或命令中填明文。同步容器需要访问固定 ONES 目标、PostgreSQL、内网 Embedding/Qdrant，以及只读挂载的 Qdrant 数据卷用于容量门禁。

```sh
# 只校验配置，不显示解析后的 DSN。
docker compose -f docker-compose.yml -f knowledge/compose.yml -f knowledge/sync.compose.yml --profile knowledge --profile knowledge-sync config --quiet
# 下列启动命令仅用于已批准的目标环境；当前本机不得执行。
docker compose -f docker-compose.yml -f knowledge/compose.yml -f knowledge/sync.compose.yml --profile knowledge --profile knowledge-sync up -d --no-deps knowledge-sync
```

绑定 `enabled=0` 或不加载可选 Compose 时不登录 ONES、不推进采集游标，也不要求真实采集 Secret。调度每 3600 秒触发；有活动 run 时优先恢复，同一来源只保留一个写 run，错过多个周期不积压多轮。停用后在下一个分页、分块或向量批次边界停止，不撤销已发布内容；单个在途 HTTP 请求仍受各服务既定超时约束。容器 SIGTERM 同样只停止后续批次，未完成 run 保留以供恢复。不要用 `down -v`、手工清空来源表或删除现有 Qdrant collection 作为回退。

回退顺序：先 `disable` 绑定并停止可选同步容器，保留现有已发布索引和数据卷；检查 active run 的固定错误码，必要时显式 `cancel`。若需要切回上一成功版本，按正常资源验证与发布流程操作，不回退 DDL，不复活已撤销权限。真实 ONES 更新时间过滤与权威删除合同尚未取得；本版仅首次全历史枚举，后续每小时按北京时间最近 7 个创建日复核，绝不因缺项推断业务删除。
