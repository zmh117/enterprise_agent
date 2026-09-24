# ONES 知识库受管同步（默认停用）

本入口把完整枚举、候选修订、分块、本地 Embedding/Qdrant 索引和原子激活串成一轮。缺陷、工单、需求共用来源身份，按三个知识库分别建候选索引；评论与附件不采集。只有内容与平台治理同在一个 PostgreSQL 时允许自动换版。已发布资源必须在绑定中明确列出，管理员草稿、停用、连接或模型变化会阻止激活；没有已发布资源的新库只准备内容和 READY 索引，不自动首次发布或授权。

## 启用前

1. 在目标环境按平台维护流程升级到当前 schema head（包含迁移 146）及匹配的 API、ONES/同步镜像。当前本机没有真实 ONES，本手册不是启用授权。
2. 按[全量采集手册](knowledge-ones-full-collector.md)准备固定 Provider、Team、项目/类型 UUID 与受管只读采集身份。`knowledge/ones-collector.example.json` 中 `resource_ids` 列出允许自动换版的**现有已发布**知识资源 ID；未发布的工单/需求 KB 不填资源 ID。重新 `configure` 会停用绑定并清除旧资源钉住值，需重新显式启用。
3. 确认这些资源采用同平台 `knowledge` 内容库，已发布配置为 KB 范围摘要版本，且没有管理员草稿。外部内容 PostgreSQL 仍可用于在线只读知识资源，但不能被此同步入口自动写入。Qdrant、Embedding、容量路径必须可达；容量不足只暂停候选，不删除旧索引/卷。
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

## 可选每小时容器

只在真实环境单次验收和独立启用授权后加载 `knowledge/sync.compose.yml`。必须同时设置 `KNOWLEDGE_SYNC_ENABLED=true`、固定 `KNOWLEDGE_SYNC_BINDING_CODE`、平台写入用 `KNOWLEDGE_SYNC_DATABASE_DSN`，并保持数据库绑定 `enabled=1`。受管主密钥由现有 Compose Secret 挂载，不在本文件或命令中填明文。同步容器需要访问固定 ONES 目标、PostgreSQL、内网 Embedding/Qdrant，以及只读挂载的 Qdrant 数据卷用于容量门禁。

```sh
# 只校验配置，不显示解析后的 DSN。
docker compose -f docker-compose.yml -f knowledge/compose.yml -f knowledge/sync.compose.yml --profile knowledge --profile knowledge-sync config --quiet
# 下列启动命令仅用于已批准的目标环境；当前本机不得执行。
docker compose -f docker-compose.yml -f knowledge/compose.yml -f knowledge/sync.compose.yml --profile knowledge --profile knowledge-sync up -d --no-deps knowledge-sync
```

绑定 `enabled=0` 或不加载可选 Compose 时不登录 ONES、不推进采集游标，也不要求真实采集 Secret。调度每 3600 秒触发；有活动 run 时优先恢复，同一来源只保留一个写 run，错过多个周期不积压多轮。停用后在下一个分页、分块或向量批次边界停止，不撤销已发布内容；单个在途 HTTP 请求仍受各服务既定超时约束。容器 SIGTERM 同样只停止后续批次，未完成 run 保留以供恢复。不要用 `down -v`、手工清空来源表或删除现有 Qdrant collection 作为回退。

回退顺序：先 `disable` 绑定并停止可选同步容器，保留现有已发布索引和数据卷；检查 active run 的固定错误码，必要时显式 `cancel`。若需要切回上一成功版本，按正常资源验证与发布流程操作，不回退 DDL，不复活已撤销权限。真实 ONES 更新过滤/排序与权威删除合同尚未取得，本版始终全量枚举且不因缺项推断业务删除。
