# PostgreSQL 18 / RabbitMQ 4 Compose 升级手册

本文适用于本仓库的单节点本地 Docker Compose 环境。目标版本为：

- PostgreSQL：`postgres:18`
- RabbitMQ：`rabbitmq:4-management`

生产环境应通过 `.env` 的 `POSTGRES_IMAGE`、`RABBITMQ_IMAGE` 锁定经过验证的补丁版本或镜像 digest，不要依赖浮动标签直接发布。

## 1. 重要变化

PostgreSQL 18 官方镜像默认数据目录为：

```text
/var/lib/postgresql/18/docker
```

Compose 必须把命名卷挂载到 `/var/lib/postgresql`。PostgreSQL 16 的物理数据目录不能直接交给 PostgreSQL 18 启动，本仓库采用逻辑 `pg_dump` / `pg_restore` 迁移。

RabbitMQ 4 的本地迁移采用“排空 Agent 队列后创建新 broker”的方式。脚本不会 purge 队列，不会删除卷。如果 normal、retry、dead 任一队列存在 ready/unacked 消息，切换保护会失败。

## 2. 工具说明

统一入口：

```bash
scripts/compose_infra_upgrade.sh --help
```

生成的数据库备份默认位于：

```text
.local/compose-infra-upgrade/<UTC timestamp>/
```

该目录已加入 `.gitignore`，包含：

```text
enterprise_agent.dump   PostgreSQL custom-format 数据库备份
globals.sql             角色定义参考备份，不包含角色密码
before-metrics.tsv      迁移前关键表记录数和配置 revision
metadata.txt            旧镜像、挂载卷、版本和文件校验信息
after-metrics.tsv       恢复后指标
```

备份中包含业务数据和加密后的 platform secret，仍应按敏感数据管理，不要上传代码仓库。

## 3. 全新环境

没有需要保留的旧数据时：

```bash
docker compose config --quiet
docker compose up -d postgres rabbitmq
docker compose build api-server agent-worker
docker compose up -d api-server agent-worker
docker compose ps
```

检查版本和运行状态：

```bash
docker compose exec -T postgres \
  psql -X -A -t -U enterprise_agent -d enterprise_agent -c 'show server_version;'

docker compose exec -T postgres \
  psql -X -A -t -U enterprise_agent -d enterprise_agent -c 'show data_directory;'

docker compose exec -T rabbitmq rabbitmq-diagnostics -q server_version
docker compose exec -T rabbitmq rabbitmq-diagnostics -q ping
curl --noproxy '*' -fsS http://127.0.0.1:8000/api/ready
```

预期 PostgreSQL 为 `18.x`，数据目录以 `/var/lib/postgresql/18/` 开头，RabbitMQ 为 `4.x`。

## 4. 已有 PostgreSQL 16 / RabbitMQ 3 环境

### 4.1 禁止直接启动新镜像

升级前不要先执行 `docker compose up`。当前代码的 Compose 已指向新镜像和新命名卷，提前启动会创建空的 PostgreSQL 18，旧匿名卷仍然存在但不会自动迁移。

先确保旧 PostgreSQL 16 和 RabbitMQ 3 容器仍在运行，然后记录检查信息：

```bash
scripts/compose_infra_upgrade.sh preflight
```

输出会包含旧容器实际镜像 ID/digest、匿名卷名称、数据库版本、RabbitMQ 版本、feature flags 和三个 Agent 队列状态。保存这份输出。

### 4.2 停止入口并排空 RabbitMQ

先停止所有会创建新任务的入口：

```bash
docker compose stop api-server dingtalk-stream-ingress
```

让 `agent-worker` 继续运行，直到 normal/retry 队列处理完成。然后停止 worker 并再次检查：

```bash
docker compose stop agent-worker
scripts/compose_infra_upgrade.sh preflight --require-empty-rabbitmq
```

如果 dead queue 非空，先通过 PostgreSQL job/audit 数据和 RabbitMQ Management UI 对账。需要保留 broker 内消息时不要继续本流程，应设计 RabbitMQ 3.13 feature flags + 4.x 原地升级或 blue/green 消息迁移。

### 4.3 备份 PostgreSQL 16

保持旧 PostgreSQL 运行：

```bash
scripts/compose_infra_upgrade.sh backup-postgres
```

命令最后会输出 `BACKUP_DIR`。确认目录中的三个主要文件非空，并把目录复制到独立安全位置：

```bash
ls -lh .local/compose-infra-upgrade/<timestamp>/
```

不要使用文件系统复制 PostgreSQL 16 数据目录代替逻辑备份。

### 4.4 保留旧容器并启动新基础设施

先记录旧容器名称和挂载卷：

```bash
docker compose ps -q postgres rabbitmq
docker inspect "$(docker compose ps -q postgres)" --format '{{json .Mounts}}'
docker inspect "$(docker compose ps -q rabbitmq)" --format '{{json .Mounts}}'
```

停止旧基础设施，然后让 Compose 用版本隔离命名卷创建 PostgreSQL 18 和 RabbitMQ 4：

```bash
docker compose stop postgres rabbitmq
docker compose up -d postgres rabbitmq
docker compose ps
```

不得执行 `docker compose down -v`，也不得删除 preflight 记录的旧匿名卷。

### 4.5 恢复 PostgreSQL 18

确保应用镜像已构建，因为恢复命令需要用 api-server 镜像运行 migration/seed：

```bash
docker compose build api-server agent-worker
scripts/compose_infra_upgrade.sh restore-postgres18 \
  .local/compose-infra-upgrade/<timestamp>
```

恢复命令只接受 PostgreSQL 18，并检查 `data_directory`。它会重建目标 `enterprise_agent` 数据库，不会删除 PostgreSQL 命名卷、旧卷或备份。

### 4.6 启动应用并验收

```bash
docker compose up -d api-server agent-worker

scripts/compose_infra_upgrade.sh verify \
  .local/compose-infra-upgrade/<timestamp>

SMOKE_BUILD=false scripts/smoke_rabbitmq4.sh
```

`smoke_rabbitmq4.sh` 使用当前已配置的 Agent runtime 提交问题，不创建、覆盖或切换 platform secret/runtime config。若当前启用真实 Claude/DeepSeek，该步骤会发生一次真实模型调用。

验收必须同时满足：

1. PostgreSQL 是 18.x，`data_directory` 正确。
2. 迁移前后关键表记录数一致，配置 revision 不回退；migration/seed 造成的 revision 前进会被明确报告。
3. RabbitMQ 是 4.x，Management 和健康检查正常。
4. Agent Job 能通过真实 API 发布、被 worker 消费并变为 `SUCCEEDED`。
5. 临时 RabbitMQ smoke queues 验证 job/retry/dead 消息持久化和 ack。

## 5. 回滚

验收完成前必须保留：

- PostgreSQL 16 和 RabbitMQ 3 的旧卷信息。
- PostgreSQL 逻辑备份目录。
- 旧镜像名称、image ID 和 digest。
- 升级期间的写入控制记录。

回滚原则：

1. 立即停止 `api-server`、`dingtalk-stream-ingress` 和 `agent-worker`，阻止新写入。
2. 停止 PostgreSQL 18 和 RabbitMQ 4。
3. 使用 preflight/metadata 记录的旧镜像和旧卷重新启动旧基础设施。
4. 启动应用前检查旧 PostgreSQL 数据和 RabbitMQ 队列。
5. 如果 PostgreSQL 18 已产生新业务写入，必须先评估并导出这些增量；脚本不会自动反向同步到 PostgreSQL 16。

旧环境无法直接恢复时，可以启动一个独立 PostgreSQL 16 容器挂载旧卷进行核验。挂载目标必须是 PostgreSQL 16 的 `/var/lib/postgresql/data`，并使用记录下来的完全一致镜像版本。

## 6. 验收后清理

旧卷和备份的删除不属于升级主流程。至少完成一次重启后 smoke、确认备份可读并经过人工批准后，再根据 preflight 记录逐个执行明确的 `docker volume rm <exact-volume-name>`。

禁止使用：

```bash
docker compose down -v
docker volume prune
```

这些命令可能删除与本次升级无关的数据。

## 7. 常见问题

### PostgreSQL 提示数据目录版本不兼容

说明 PostgreSQL 18 误挂载了旧物理目录。停止容器，恢复 `/var/lib/postgresql` 的新命名卷配置，再执行逻辑恢复。

### PostgreSQL 18 启动了但数据库为空

新命名卷初始化成功不等于迁移完成。找到升级前生成的 `enterprise_agent.dump`，执行 `restore-postgres18`。

### RabbitMQ 切换保护一直失败

检查：

```bash
docker compose exec -T rabbitmq rabbitmqctl -q list_queues \
  name messages_ready messages_unacknowledged consumers
```

先停止入口，让 worker 消费 normal/retry 队列。dead queue 必须人工对账，脚本不会自动清空。

### API ready 正常但任务没有完成

依次检查：

```bash
docker compose logs --tail=200 agent-worker
docker compose exec -T rabbitmq rabbitmqctl -q list_queues \
  name messages_ready messages_unacknowledged consumers
curl --noproxy '*' -fsS http://127.0.0.1:8000/api/ready
```

确认 worker 连接的是 `amqp://guest:guest@rabbitmq:5672/`，API 与 worker 使用同一个 PostgreSQL 18。
