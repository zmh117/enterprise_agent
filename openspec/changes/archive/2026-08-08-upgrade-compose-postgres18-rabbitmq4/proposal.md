## Why

当前 Docker Compose 仍使用 `postgres:16` 和 `rabbitmq:3-management`，并且两个服务均未显式声明命名数据卷。直接替换主版本镜像会遇到 PostgreSQL 数据目录格式和挂载路径变化、RabbitMQ 升级路径与 feature flags 约束，也无法可靠保留或回滚现有数据，因此需要把版本升级、持久化、迁移和验证作为一个完整变更实施。

## What Changes

- 将 Compose 默认 PostgreSQL 镜像升级为 `postgres:18`，并按 PostgreSQL 18 镜像约定将命名卷挂载到 `/var/lib/postgresql`。
- 将 Compose 默认 RabbitMQ 镜像升级为 `rabbitmq:4-management`，保留 AMQP 与 Management 端口及现有应用连接契约。
- 为 PostgreSQL 和 RabbitMQ 增加显式命名数据卷，避免容器重建时依赖不可控的匿名卷。
- 提供升级前检查、备份、迁移、验证和回滚说明；PostgreSQL 16 数据通过逻辑导出/恢复迁移到新的 PostgreSQL 18 数据卷，不直接复用旧数据目录。
- 根据当前 RabbitMQ 实际版本和 feature flags 状态选择受支持的原地升级，或在确认队列已排空后使用新 RabbitMQ 4 数据卷并重新声明拓扑。
- 增加 Compose 级自动化/文档化验证，覆盖数据库迁移、应用 migration/seed、API ready、Agent Job 发布消费、retry 和 dead-letter。
- **BREAKING**：PostgreSQL 持久化挂载点从 PostgreSQL 17 及以下使用的 `/var/lib/postgresql/data` 语义切换为 PostgreSQL 18 的 `/var/lib/postgresql`；旧主版本数据不能直接作为 PostgreSQL 18 数据目录启动。
- **BREAKING**：RabbitMQ 3 的持久化数据只允许按官方支持路径升级；不满足版本或 feature flags 前置条件时不得直接让 RabbitMQ 4 复用旧数据卷。

## Capabilities

### New Capabilities

- `compose-infrastructure-major-upgrade`: 定义 PostgreSQL 18、RabbitMQ 4 的 Compose 运行契约、显式持久化、升级前置检查、数据迁移、回滚与验收要求。

### Modified Capabilities

- `rabbitmq-agent-job-execution`: 将 Compose 闭环验收扩展为 RabbitMQ 4 兼容性验证，并要求升级后保留任务发布、消费、确认、重试和 dead-letter 语义。

## Impact

- 影响 `docker-compose.yml` 中 PostgreSQL、RabbitMQ 服务和顶层命名卷定义。
- 影响本地开发、Compose 部署及已有匿名卷/数据卷的升级操作流程。
- 需要新增或更新基础设施升级脚本、中文运行文档和 Compose smoke 测试。
- 不改变 `DATABASE_DSN`、`RABBITMQ_URL`、对外端口、HTTP API、数据库业务模型和 Agent Job 消息格式。
- 使用浮动主版本标签符合本次需求；生产部署仍需在部署配置中锁定已验证的补丁版本或镜像 digest。
