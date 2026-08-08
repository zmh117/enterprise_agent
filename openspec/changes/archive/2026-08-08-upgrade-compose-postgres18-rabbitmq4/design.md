## Context

当前 `docker-compose.yml` 使用 `postgres:16` 与 `rabbitmq:3-management`，两个服务都依赖镜像隐式创建的匿名卷。PostgreSQL 18 官方镜像把默认 `PGDATA` 改为 `/var/lib/postgresql/18/docker`，并要求将持久化卷挂载到 `/var/lib/postgresql`；PostgreSQL 主版本之间也不能直接复用物理数据目录。RabbitMQ 4 只支持从满足前置条件的 3.13.x 直接升级，且升级前必须启用稳定 feature flags。

本项目的 Agent Job 先持久化到 PostgreSQL，RabbitMQ 消息只携带任务标识并用于异步调度。因此本地 Compose 环境可以在确保队列无待处理消息后重建 RabbitMQ，而 PostgreSQL 数据必须完整迁移和核验。

## Goals / Non-Goals

**Goals:**

- Compose 默认运行 PostgreSQL 18 和 RabbitMQ 4 Management。
- 用显式、版本隔离的命名卷持久化两个基础设施服务。
- 提供不会静默丢数据的升级前检查、备份、迁移、验收和回滚流程。
- 保持 API、worker、端口、连接环境变量及 RabbitMQ 队列语义不变。
- 新装环境和从当前 Compose 环境升级都能使用同一套中文文档完成验证。

**Non-Goals:**

- 不设计生产多节点 PostgreSQL 的零停机升级或逻辑复制切换。
- 不设计 RabbitMQ 集群的滚动升级、跨集群 federation/shovel 迁移。
- 不修改业务数据库表、Agent Job 消息格式或 RabbitMQ 队列类型。
- 不自动删除旧匿名卷、旧备份或执行不可逆清理。

## Decisions

### 1. 使用需求指定的主版本标签，并允许环境变量覆盖

Compose 默认值使用 `${POSTGRES_IMAGE:-postgres:18}` 与 `${RABBITMQ_IMAGE:-rabbitmq:4-management}`。这样满足默认升级目标，也允许 CI 或生产部署锁定已验证补丁版本/digest。直接硬编码补丁版本更可重复，但不符合用户明确要求的默认标签；仅使用浮动标签又难以回滚，因此采用“默认主版本标签 + 可覆盖”的方式。

### 2. PostgreSQL 18 使用独立命名卷和逻辑迁移

新增版本隔离的命名卷，例如 `postgres18-data`，挂载到 `/var/lib/postgresql`，不复用 PostgreSQL 16 的匿名卷或 `/var/lib/postgresql/data`。升级工具先用 PostgreSQL 18 客户端对仍在运行的 PostgreSQL 16 执行逻辑导出，再初始化 PostgreSQL 18 新卷并恢复。

选择 dump/restore 而不是 `pg_upgrade --link`，原因是当前 Compose 没有显式旧卷、数据规模定位为本地/MVP、逻辑迁移更易验证和回滚。备份产物放在被 `.gitignore` 排除的本地目录，脚本不得打印密码或把备份提交到仓库。

### 3. RabbitMQ 采用“排空后新建 RabbitMQ 4 broker”作为 Compose 默认迁移路径

升级前检查 `agent.job.queue`、`agent.job.retry.queue`、`agent.job.dead.queue` 的 ready/unacked 数量及当前连接。只有操作人明确停止入口和 worker，并确认需要保留的消息已经处理、任务状态已落库后，才允许切换到新的 `rabbitmq4-data` 卷。RabbitMQ 4 启动后由现有 publisher/consumer 幂等声明 exchange、queue、binding 和 DLQ 拓扑。

此路径不依赖旧 broker 是否恰好为 3.13 或 feature flags 是否完备，适合当前单节点本地 Compose。若未来生产环境要求原地保留 broker 数据，必须另建 change，按实际 3.x 版本逐级升级至 3.13、启用全部稳定 feature flags，再升级到 4.x。

### 4. 升级脚本必须默认只读检查，破坏性步骤需显式确认

提供可重复执行的 preflight/backup/restore/verify 命令或脚本。preflight 检查镜像实际版本、数据库可连接性、备份目录、磁盘空间、RabbitMQ 队列深度和 feature flags，并在不满足前置条件时非零退出。脚本不得自动删除卷；清理旧卷只作为验收完成后的人工可选步骤记录。

### 5. 验收同时覆盖数据完整性和业务闭环

PostgreSQL 验收至少比较迁移前后的核心表清单、记录数和配置 revision，并运行应用 migration/seed 幂等检查。RabbitMQ 验收检查 broker 版本与健康状态、队列拓扑，再提交 Agent Job 验证 publish、consume、ack、retry 和 dead-letter。只验证容器 `Up` 不视为升级完成。

## Risks / Trade-offs

- [浮动标签在未来可能解析到不同补丁版本] → Compose 支持镜像变量覆盖，验证文档记录实际 image digest，生产部署锁定补丁版本或 digest。
- [旧 PostgreSQL 数据仍在匿名卷中，定位困难] → 迁移从当前仍在运行的 PostgreSQL 16 服务进行逻辑导出，不通过猜测卷名直接操作数据目录。
- [PostgreSQL dump/restore 在大数据量下停机较长] → 当前范围限定本地/MVP；生产大数据量升级另行设计 `pg_upgrade` 或逻辑复制。
- [RabbitMQ 新建 broker 会丢弃未消费消息] → preflight 在任何 ready/unacked 消息存在时中止，要求先停止入口并排空；任务事实状态由 PostgreSQL核验。
- [RabbitMQ 4 客户端或队列参数不兼容] → Compose smoke 测试覆盖 topology declaration、publish/consume、retry/DLQ，并在删除旧 broker 数据前保留回滚路径。
- [恢复失败导致新数据库不可用] → 新旧数据卷隔离，保留逻辑备份和旧容器/卷；失败时恢复旧镜像启动路径。

## Migration Plan

1. 记录当前镜像版本/digest、容器和卷信息，执行数据库连接、磁盘空间及 RabbitMQ 队列 preflight。
2. 停止 API 入口，等待 worker 完成在途任务；确认三个 Agent 队列均无 ready/unacked 消息后停止 worker。
3. 对 PostgreSQL 16 执行带校验信息的逻辑备份，记录核心表数量、关键记录数和配置 revision。
4. 更新 Compose 镜像和命名卷定义，启动新的 PostgreSQL 18，恢复逻辑备份并运行幂等 migration/seed。
5. 启动使用新命名卷的 RabbitMQ 4，确认版本、Management API、健康检查及队列拓扑声明成功。
6. 启动 api-server 与 agent-worker，执行 ready 检查和 Agent Job 成功、retry、dead-letter smoke 测试。
7. 比较迁移前后 PostgreSQL 校验信息，记录实际镜像 digest。验收完成前保留旧卷和备份。

回滚时停止新服务，将 Compose 镜像覆盖回已记录的 PostgreSQL 16/RabbitMQ 3 版本并重新挂接旧运行环境；PostgreSQL 18 产生的新写入不会自动反向同步，因而升级窗口内必须控制写入，回滚前需要评估是否存在需导回的新增业务数据。

## Open Questions

- 实施时需要从运行环境确认当前 `rabbitmq:3-management` 实际解析版本；该信息只影响运维记录，不改变本地默认采用新 broker 的决策。
- 若现有 PostgreSQL 数据量已经不适合逻辑迁移，应在 apply 前单独评估并拆分生产级 PostgreSQL 升级 change。
