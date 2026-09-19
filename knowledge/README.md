# 可选知识库部署

知识服务的离线索引组件集中在 `compose.yml`；在线 Knowledge MCP 另加 `mcp.compose.yml`。两者都是根 Compose 的**可选扩展文件**，不是独立项目。暂时不需要知识库的环境只使用根 `docker-compose.yml`，无需构建或下载 Embedding/Qdrant，也无需知识服务凭据。

## 启用方式

所有命令在仓库根目录执行，始终将根 Compose 放在第一个 `-f` 参数。保留原 Compose 项目名（当前本机为 `enterprise_agent`），不要在此目录单独 `docker compose up`，也不要另取 `-p` 名称，否则会切换到另一组模型/向量卷。

启用环境必须在既有部署配置（根 `.env` 或进程环境）中提供 `DATABASE_DSN`，指向主栈同一数据库的容器内地址 `postgres:5432`，不能使用宿主机 `localhost` 或映射端口。不在本目录复制 `.env` 或填写明文凭据；缺失/空值时叠加配置会直接报错。未加载扩展的环境没有此新增配置要求。

```sh
# 仅检查配置，不启动服务；不要输出完整解析配置，以免泄露连接信息。
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml -f knowledge/compose.yml \
  --profile knowledge --profile knowledge-prepare config --quiet

# 构建独立模型镜像与轻量运维镜像。
docker compose -f docker-compose.yml -f knowledge/compose.yml \
  --progress quiet build knowledge-embedding knowledge-ops

# 一次性准备固定模型。已完成的文件仍验证摘要，不重复下载。
docker compose -f docker-compose.yml -f knowledge/compose.yml \
  --profile knowledge-prepare run --rm --no-deps knowledge-model-prepare

# 仅启动两个常驻知识服务，不启动业务全栈或索引任务。
docker compose -f docker-compose.yml -f knowledge/compose.yml \
  --profile knowledge up -d --no-deps knowledge-embedding knowledge-qdrant
```

`knowledge-model-prepare` 和 `knowledge-ops` 都是一次性任务。不要用不指定服务的 `--profile knowledge up` 代替以上命令。基准、迁移门禁、显式提交、断点恢复及查询见[完整运行手册](../docs/runbooks/knowledge-local-vector-index.md)。当前模型锁针对 Linux ARM64，其他架构不能直接照搬。

平台新增迁移后，已存在的 `knowledge-ops` 镜像不会自动更新。运行知识 CLI 前应定向重建该镜像并核验 schema 门禁；不需要重新下载模型或重建索引。更新与知识服务定向重启见[运维镜像更新](../docs/runbooks/knowledge-local-vector-index.md#运维镜像更新与定向重启)。

人工相关性基线使用[本地评测入口](../docs/runbooks/knowledge-retrieval-evaluation.md)。真实问题/标签留在 Git 排除的受限目录；合成、自查询和人工效果分别报告，不把运维检索成功当成 Agent 读取授权。

工具资源 Web 页面和检索资源管理合同见[知识治理管理与排障](../docs/runbooks/knowledge-governance.md)。代码已接线不等于真实资源已发布或 Agent 已通过真实检索验收。

## 在线 Knowledge MCP（独立可选扩展）

仅需要离线索引时继续使用上述两个文件，不加载 `mcp.compose.yml`。需要在线检索时顺序为根文件、`knowledge/compose.yml`、`knowledge/mcp.compose.yml`；仍使用原项目名和已有数据卷。

在线扩展新增 `knowledge-mcp`（9108，仅容器网络）及 API 的知识服务身份桥配置。它不会自动配置来源、角色或应用，也不会代替正式迁移。以下是经批准部署时的步骤；代码验收尚不表示已执行这些生产操作。

1. 核对非终态任务、平台镜像与当前 schema，按平台流程运行正式 Migrator。不要回退/删表。Embedding 固定模型准备和已有索引仍沿用离线流程。
2. 在受管部署配置中提供 `KNOWLEDGE_DATABASE_DSN`：指向同一数据库、同一 `knowledge` schema，用户名必须为 `knowledge_mcp_reader`，**不能复用平台管理 DSN**。角色由下一步显式创建，不在 MCP 启动时自动建表或授权。
3. 创建独立高熵服务凭据的受管文件，以 `KNOWLEDGE_BOOTSTRAP_TOKEN_FILE` 提供绝对路径。不要复用其他 Worker 凭据、提交到 Git、回显文件内容或粘贴到 Web。API 与 MCP 挂载同一文件，入口按既有流程规范化为进程可读的只读副本；服务身份签发必须启用。现有公开 JWKS 也须可供 MCP 读取，不挂载签名私钥。
4. 构建 `knowledge-mcp` 后，由具备 DDL/授权权限的运维身份显式执行独立账号配置。下例的两个 `-e` 只从受限执行环境取值，不在命令行写口令：`DATABASE_DSN` 此次是运维账号，`KNOWLEDGE_DATABASE_PASSWORD` 是独立角色的至少 24 字符高熵口令，必须与在线 DSN 对应。执行完撤去临时运维环境，不把运维账号用于常驻服务。

```sh
# 只校验；禁止输出完整解析配置。
docker compose -f docker-compose.yml -f knowledge/compose.yml \
  -f knowledge/mcp.compose.yml --profile knowledge config --quiet

docker compose -f docker-compose.yml -f knowledge/compose.yml \
  -f knowledge/mcp.compose.yml --progress quiet build knowledge-mcp

# 明确维护操作：会创建/收紧固定数据库角色，不修改业务数据。
docker compose -f docker-compose.yml -f knowledge/compose.yml \
  -f knowledge/mcp.compose.yml --profile knowledge run --rm --no-deps \
  -e DATABASE_DSN -e KNOWLEDGE_DATABASE_PASSWORD knowledge-mcp \
  python -m services.knowledge_mcp_server.provision_database
```

配置入口将角色限制为无角色继承、无超级用户/建库/建角色/复制/RLS 绕过权限；按当前实际查询逐列授予元数据及知识证据读取，只给三张审计表必要的 INSERT/UPDATE，不给业务写入或 DELETE。既有列级授权会收紧，PUBLIC 或其他途径的超额权限导致检查失败，不会自动修改全平台 PUBLIC 权限。本次取消来源确认后读取合同不再包含 source_binding，已部署角色需要显式重跑配置入口收紧旧授权。后续 schema 变更需要重新核对列合同和授予；启动也会检查角色，误配平台账号会拒绝启动。

5. 依平台维护流程更新 API（新凭据桥）、ONES、Runtime/Worker 和 Web 的对应代码版本。确认内部 Embedding/Qdrant、PostgreSQL/schema 已就绪后，使用三个文件定向启动 `knowledge-mcp`；不要用无服务名的 `up` 启动一次性运维任务。API 与 MCP 不互相声明启动依赖，桥未可用时检索明确失败关闭。
6. `/health` 仅验证 schema/审计依赖，不能代替向量、ONES、权限和真实 Job 验收。先完成任务 7.3 的阻塞依赖预算与隔离完整链路测试，再按批准流程在 Web 配置资源、角色应用 KB 范围和新的 Agent/Application Publication。配置流程见[管理手册](../docs/runbooks/knowledge-governance.md#管理流程)，不要求 ONES 地址/Team 来源确认、证明摘要或运行中 Job ID。不得把旧 Job 当成新增知识工具的验收。

停用时先停用知识资源与相关新工具发布，再定向 `stop knowledge-mcp`，保留 PostgreSQL、模型及 Qdrant 卷。API 中的可选凭据移除需受控更新；其他仍使用知识库的应用未退出前不得撤去。不要 `down -v`，不降级 schema，不自动重分块或重编码。

## 数据、网络与运维边界

- 共用平台 PostgreSQL 的 `knowledge` schema，不另建 PostgreSQL。数据库迁移仍属于平台统一 catalog：不用知识服务的环境升级后端时也必须满足对应 schema head，但不会自动导入缺陷或生成向量。
- 扩展只为 PostgreSQL 追加 `knowledge-internal`，保留默认和运行控制网络。Embedding、Qdrant、运维 CLI 仅使用 internal 网络，不发布宿主机端口；准备任务只使用下载网络，不获得数据库配置或平台 Secret。
- 保留 `knowledge-models`、`knowledge-qdrant` 卷键名；同一项目仍使用原有模型和 Qdrant 数据。文件拆分不搬迁或清空任何卷。
- Qdrant 固定为 `v1.19.1` 和已核验的镜像 digest，不使用浮动 latest。已有卷跨次版本升级必须先备份并逐级演练，不能直接换最新镜像跳级启动；见[升级与恢复记录](../docs/runbooks/knowledge-local-vector-index.md#qdrant-版本升级与恢复)。
- 已有 PostgreSQL 若尚未接入知识网络，须在批准的维护流程中补充网络及 `postgres` 别名；不能为此直接重建数据库。新部署由叠加配置管理。当前本机已经接入，拆分不要求重启。
- 部署了知识服务的环境，后续 Compose 运维命令应始终叠加已启用的文件（离线两个，在线三个，即使此次只操作某个业务服务），避免把知识容器误判为 orphan。禁止仅用主文件执行 `--remove-orphans`，不要用全项目 `down -v` 停用知识库。
- 在线 MCP 使用 `knowledge-internal` 与 `agent-runtime-control` 两个内部网络，无宿主机端口或出网网络；仅连接 PostgreSQL、Embedding/Qdrant 和固定 API 桥，不直接连接 ONES Provider。API 追加知识网络以执行资源验证；主文件和离线扩展不因此增加在线 Secret。
- 若只暂停知识服务，用叠加配置定向 `stop knowledge-embedding knowledge-qdrant`，保留卷和数据库网络；正式卸载/删卷另行审批。

配置与隔离合成测试通过不意味着已正式部署或完成业务召回验收；本地资源验证、双用户 ONES、Agent 新 Job 和人工质量评测仍需单独验收。
