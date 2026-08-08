## ADDED Requirements

### Requirement: Compose 必须默认运行 PostgreSQL 18 和 RabbitMQ 4
系统 SHALL 将 Compose 默认数据库镜像设为 `postgres:18`，将默认消息代理镜像设为 `rabbitmq:4-management`，并 MUST 保持现有服务名、容器内端口及应用连接契约不变。

#### Scenario: 新环境按默认镜像启动
- **WHEN** 操作人未覆盖基础设施镜像变量并执行 Docker Compose 启动
- **THEN** PostgreSQL 以主版本 18 运行，RabbitMQ 以主版本 4 且启用 Management 插件运行

#### Scenario: 部署锁定已验证镜像
- **WHEN** CI 或生产部署通过环境变量提供具体补丁标签或 digest
- **THEN** Compose 使用覆盖后的镜像且服务配置、端口和依赖关系保持一致

### Requirement: 基础设施数据必须使用显式版本隔离命名卷
系统 SHALL 为 PostgreSQL 18 和 RabbitMQ 4 声明显式命名卷；PostgreSQL 18 卷 MUST 挂载到 `/var/lib/postgresql`，且新主版本卷 MUST 不直接复用 PostgreSQL 16 的物理数据目录。

#### Scenario: PostgreSQL 18 初始化持久化数据
- **WHEN** PostgreSQL 18 在空的新命名卷上首次启动
- **THEN** 数据初始化在 `/var/lib/postgresql/18/docker` 下，并在容器重建后保持可用

#### Scenario: RabbitMQ 4 重建容器
- **WHEN** RabbitMQ 4 容器在不删除命名卷的情况下重建
- **THEN** broker 元数据和已确认需要保留的运行状态仍由同一命名卷提供

### Requirement: PostgreSQL 主版本升级必须使用可验证的逻辑迁移
系统 SHALL 提供 PostgreSQL 16 到 18 的备份、恢复和核验流程，MUST 在新 PostgreSQL 18 数据卷中恢复逻辑备份，并 MUST NOT 使用 PostgreSQL 18 直接启动 PostgreSQL 16 物理数据目录。

#### Scenario: 迁移已有 PostgreSQL 数据
- **WHEN** 当前 PostgreSQL 16 包含 Agent Job、平台配置、审计或 secret 数据
- **THEN** 升级流程先生成可恢复的逻辑备份，再恢复到 PostgreSQL 18 新卷，并比较关键表记录数与配置 revision

#### Scenario: 数据恢复失败
- **WHEN** PostgreSQL 18 恢复或迁移后校验失败
- **THEN** 升级流程中止且保留旧运行环境、旧数据卷和逻辑备份，不执行自动清理

### Requirement: RabbitMQ 4 切换前必须防止静默丢消息
系统 SHALL 在创建新的 RabbitMQ 4 broker 前检查 Agent 正常、重试和死信队列的 ready/unacked 状态，并 MUST 在仍有未处理消息时中止默认切换流程。

#### Scenario: 队列已经排空
- **WHEN** API 入口与 worker 已停止，且所有受管 Agent 队列的 ready/unacked 数量均为零
- **THEN** 操作人可以启动使用新命名卷的 RabbitMQ 4，并由应用重新声明队列拓扑

#### Scenario: 仍有未处理消息
- **WHEN** 任一受管 Agent 队列存在 ready 或 unacked 消息
- **THEN** preflight 返回失败并列出相关队列，且不得自动删除、替换或清空旧 broker 数据

### Requirement: 升级必须提供非破坏性的检查与回滚资料
系统 SHALL 提供中文升级文档和可重复执行的 preflight、backup、restore、verify 操作，所有清理旧卷或备份的动作 MUST 与升级主流程分离并由操作人显式执行。

#### Scenario: 执行升级前检查
- **WHEN** 操作人运行 preflight
- **THEN** 系统报告当前镜像版本/digest、数据库状态、RabbitMQ 队列状态及关键迁移前置条件，并在不满足条件时非零退出

#### Scenario: 升级验收前回滚
- **WHEN** PostgreSQL 18、RabbitMQ 4 或应用闭环验证失败
- **THEN** 操作人可依据文档恢复已记录的旧镜像和旧数据环境，且旧卷与备份仍然存在

### Requirement: 升级验收必须覆盖基础设施和应用数据
系统 SHALL 通过 Compose 级验证确认 PostgreSQL 18、RabbitMQ 4、应用 migration/seed 和 Agent Job 闭环均正常，MUST NOT 仅以容器处于运行状态作为完成标准。

#### Scenario: 完成升级 smoke 测试
- **WHEN** 新基础设施和应用服务全部启动
- **THEN** 验证结果包含数据库版本与数据核验、RabbitMQ 版本与队列拓扑、API ready、Agent Job 成功执行以及 retry/dead-letter 路径

