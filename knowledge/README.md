# 可选知识库部署

知识服务集中在 `compose.yml`，它是根 Compose 的**可选扩展文件**，不是独立项目。暂时不需要知识库的环境只使用根 `docker-compose.yml`，无需构建或下载 Embedding/Qdrant。

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

## 数据、网络与运维边界

- 共用平台 PostgreSQL 的 `knowledge` schema，不另建 PostgreSQL。数据库迁移仍属于平台统一 catalog：不用知识服务的环境升级后端时也必须满足对应 schema head，但不会自动导入缺陷或生成向量。
- 扩展只为 PostgreSQL 追加 `knowledge-internal`，保留默认和运行控制网络。Embedding、Qdrant、运维 CLI 仅使用 internal 网络，不发布宿主机端口；准备任务只使用下载网络，不获得数据库配置或平台 Secret。
- 保留 `knowledge-models`、`knowledge-qdrant` 卷键名；同一项目仍使用原有模型和 Qdrant 数据。文件拆分不搬迁或清空任何卷。
- 已有 PostgreSQL 若尚未接入知识网络，须在批准的维护流程中补充网络及 `postgres` 别名；不能为此直接重建数据库。新部署由叠加配置管理。当前本机已经接入，拆分不要求重启。
- 部署了知识服务的环境，后续 Compose 运维命令应始终叠加两个文件（即使此次只操作某个业务服务），避免把知识容器误判为 orphan。禁止仅用主文件执行 `--remove-orphans`，不要用全项目 `down -v` 停用知识库。
- 若只暂停知识服务，用叠加配置定向 `stop knowledge-embedding knowledge-qdrant`，保留卷和数据库网络；正式卸载/删卷另行审批。

本次拆分只调整部署文件，不意味着已经完成正式迁移、全量索引或业务召回验收；也没有开放 Web/MCP/角色授权。
