## Context

现有 Compose 仅提供平台自身的 PostgreSQL、RabbitMQ 和按 profile 启动的 Internal API Platform，没有供真实查询使用的 MySQL、SQL Server 与 Redis 测试实例。当前 topology 示例已经能表达 MySQL、SQL Server、Oracle 以及基地级 standalone/cluster Redis，数据库执行器和 schema inspector 也已覆盖三种方言；本次本地测试库只覆盖 MySQL 和 SQL Server，Oracle 平台能力保留但不纳入测试 profile。

本地开发机为 ARM64。MySQL、Redis 存在多架构镜像；SQL Server Linux 容器仍以 x86-64 为受支持平台，因此 ARM64 上只能把 `linux/amd64` 模拟作为开发测试路径，且必须通过实际健康检查决定是否可用，不能把 Compose 配置可渲染当作运行成功。

测试环境的主要使用者是后续调试 Agent 的开发者。关键约束是：环境必须可重复、异常必须确定、两个 Redis 必须互相隔离、生产只读边界不得因测试播种而放宽。

## Goals / Non-Goals

**Goals:**

- 通过一个显式 Compose profile 启动两个数据库和两个一一对应的 Redis。
- 提供语义同构、可由 Agent 查询和关联的 MES 数据，并包含确定性异常与缓存不一致。
- 让启动、播种、验证和重置均可重复执行、可观察且有明确失败状态。
- 使用 topology secret ref 将两个测试基地接入现有 Internal API Platform。
- 将播种管理权限与平台只读运行凭据分离。
- 在 ARM64 上原生运行可用服务，并诚实暴露 SQL Server 模拟运行限制。

**Non-Goals:**

- 不为生产环境提供数据库或 Redis。
- 不测试 Redis Cluster、Sentinel、TLS 或跨基地共享 Redis；两个 Redis 均为 standalone。
- 不在本次本地测试 profile 中启动 Oracle 测试库；Oracle 只读网关能力不在本变更中删除。
- 不模拟完整 MES 业务流程或大规模性能数据。
- 不增加 Agent 写数据库/Redis 的工具，不改变只读策略。
- 不把测试凭据写入 topology YAML、OpenSpec 或日志。
- 不承诺 ARM64 上的 SQL Server 模拟运行属于 Microsoft 支持配置。

## Decisions

### 1. 使用单一 `agent-test-data` profile，服务按基地明确命名

Compose 增加以下长期服务：

| 基地 | 数据库服务 | Redis 服务 | 数据卷 |
|---|---|---|---|
| `agent_test/mysql` | `agent-test-mysql` | `agent-test-redis-mysql` | 数据库卷与 Redis 卷各一个 |
| `agent_test/sqlserver` | `agent-test-sqlserver` | `agent-test-redis-sqlserver` | 数据库卷与 Redis 卷各一个 |

所有服务都放入 `agent-test-data` profile。数据库宿主端口采用可配置的非默认端口，容器内 topology 始终使用 Compose DNS 服务名与标准端口。每个服务有真实连接健康检查，播种服务通过 `depends_on: condition: service_healthy` 等待。

**替代方案：** 两个基地共享一个 Redis 并使用 key 前缀隔离。否决，因为用户明确要求每个基地使用一个 Redis，且独立实例更适合验证资源绑定是否串线。

**替代方案：** 把测试数据库加入默认 Compose。否决，因为 SQL Server 资源消耗大，会拖慢普通 API/worker 开发。

### 2. 镜像按稳定主版本配置，允许通过 env 覆盖

默认镜像系列：

- MySQL：`mysql:8.4`
- Redis：`redis:7.4`
- SQL Server：`mcr.microsoft.com/mssql/server:2022-latest`

镜像名由 `AGENT_TEST_*_IMAGE` 环境变量覆盖，便于后续锁定补丁版本或镜像 digest。SQL Server 在 Compose 中显式声明 `${AGENT_TEST_SQLSERVER_PLATFORM:-linux/amd64}`。启动脚本读取 `uname -m`/Docker server architecture，在 ARM64 上打印明确警告；验收仍要求 SQL Server 实际健康和可查询。

**替代方案：** 使用浮动 `latest`。否决，因为数据库升级可能改变 DDL、认证和驱动兼容性。

**替代方案：** 在 ARM64 上把 SQL Server 替换为兼容协议数据库。否决，因为这无法验证真实 SQL Server 方言、system catalog 和驱动行为。若模拟失败，应切换到 x86-64 Docker 主机，而不是伪装通过。

### 3. topology 使用一个测试环境、两个无车间基地

在示例 topology 中增加：

- `environment=agent_test`
- `base=mysql`，engine `mysql`，Redis host `agent-test-redis-mysql`
- `base=sqlserver`，engine `sqlserver`，schema `dbo`，Redis host `agent-test-redis-sqlserver`

首版不增加 workshop，避免把表前缀策略混入多方言与缓存联合诊断的基础数据。两个基地的数据库/Redis host、用户和密码全部通过 `secret://agent_test/<base>/...` 解析。`.env.example` 给出本地占位值，`.env` 放本地实际值；Compose 通过显式 allowlist 环境变量把只读 secret ref 对应变量传给 Internal API Platform。

**替代方案：** 复用 `sanjiu`、`xt`、`mmk` 等业务环境代码。否决，因为本地 fixture 不应冒充真实基地，也不应覆盖现有生产样例连接信息。

### 4. 使用统一业务模型和固定异常场景

两种数据库建立语义一致的六张表：

1. `production_order`：订单号、产品、计划/完成数量、状态、计划/实际时间、更新时间。
2. `equipment`：设备编码、名称、状态、心跳时间、当前订单、更新时间。
3. `equipment_alarm`：告警 ID、设备、等级、告警码、消息、发生/清除时间。
4. `material_inventory`：物料、批次、在库量、预留量、更新时间。
5. `quality_inspection`：检验 ID、订单、结果、缺陷码、检验时间。
6. `production_event`：事件 ID、订单、设备、事件类型、事件值、发生时间。

各方言保留自己的 DDL 类型和标识符规则，但表名、字段语义、业务 ID 和 fixture 时间戳一致。基线至少包含：

- 正常已完成订单，证明环境不是只有异常数据。
- 固定停滞订单 `PO-STUCK-001`，完成量长期不变。
- 关联设备 `EQ-MIX-01` 心跳过期，数据库状态为 `OFFLINE`。
- 未清除 `CRITICAL` 告警 `TEMP_HIGH`。
- 物料 `MAT-001` 的可用量低于订单需求。
- 对应质量检验和生产事件，形成可追踪时间线。

每个基地的 Redis 写入固定 namespace 下的设备状态、订单进度和库存缓存，并故意让 `EQ-MIX-01` 显示 `ONLINE`、订单进度高于数据库完成比例、库存可用量高于数据库计算值。fixture 文档列出预期差异，Agent 的正确输出必须基于查询证据而不是隐藏知识。

**替代方案：** 每种数据库使用不同业务数据。否决，因为无法区分 Agent 失败来自方言差异还是数据差异。

### 5. 播种采用独立管理路径，运行时仍使用只读凭据

增加专用 `agent-test-data-seeder` 一次性服务和对应 CLI 脚本。seeder 镜像包含 `pymysql`、`pymssql`、`redis` 驱动以及 fixture 文件，但不进入 API/worker 的运行路径。

数据库为每个基地创建：

- schema owner/管理用户：仅提供给 seeder。
- reader 用户：只授予业务表 `SELECT` 和 schema inspector 所需最小元数据权限，提供给 topology。

Redis 使用 ACL：

- 默认 reader 用户只允许 `PING`、`GET`、有界扫描所需命令和 fixture key pattern。
- `seeder` 用户允许在该实例的 fixture namespace 内创建、更新和删除测试 key。

播种流程对每个数据库使用事务与固定主键：建立缺失结构、按依赖顺序删除旧 fixture 行、插入固定行、提交后校验数量与哨兵值。Redis 只清理自己的 fixture namespace 后重建 key，不依赖 `FLUSHALL`。连续运行得到相同结果，且任何数据源失败时整体命令返回非零。

**替代方案：** 仅挂载各镜像的首次启动 init 目录。否决，因为 MySQL 等镜像在已有数据卷上会跳过初始化，不能满足重播种和恢复基线需求。

**替代方案：** 让 Internal API Platform 执行写入。否决，因为这会破坏生产只读边界并混淆测试管理与 Agent 能力。

### 6. 提供 `up`、`seed`、`verify`、`reset` 四个明确生命周期命令

新增受版本控制的入口，例如 `scripts/agent_test_data.sh`：

- `up`：检查架构与必需变量，启动四个长期服务，等待健康，执行 seed，再执行 verify。
- `seed`：在现有健康服务上幂等恢复 fixture。
- `verify`：直接验证四个数据源，并通过 `real-tools` profile 的 Internal API Platform 验证 topology resolve、schema directory、只读数据库查询和两个 Redis 路由。
- `reset --yes`：停止测试数据服务并仅删除四个显式命名的测试卷；无 `--yes` 时拒绝执行。

验证输出逐个列出数据源，不允许部分成功被汇总为成功。reset 不使用会连带删除主 PostgreSQL 卷的无界 `docker compose down -v`。

**替代方案：** 只在 README 中列出多条手工命令。否决，因为容易漏掉某一数据源、误删项目卷，也不适合作为后续 Agent 回归的稳定入口。

### 7. 将直接数据验证与 Agent 路径验证分层

第一层由 seeder/verifier 使用管理或 reader 客户端确认容器、Schema、行数、Redis key 和预期异常。第二层通过 Internal API Platform 的现有 HTTP 工具验证：

- 两个 base 都可 resolve。
- 两种 schema directory 都能看到六张表。
- 两种数据库的只读查询可执行且写语句仍被拒绝。
- 每个 base 的 Redis GET/SCAN 只到对应实例。
- 响应与日志不泄露连接信息。

这样可以在失败时区分基础设施/fixture 问题与平台路由/策略问题。

## Risks / Trade-offs

- **[ARM64 SQL Server 不受官方支持]** `linux/amd64` 模拟可能启动慢或失败 → 启动前警告、延长但限制健康检查时间、完整验证不跳过；失败时要求 x86-64 Docker 主机。
- **[SQL Server 资源消耗大]** 启动可能占用较多内存和磁盘 → profile 默认关闭，文档声明建议资源，镜像和数据卷独立。
- **[浮动主版本 tag 漂移]** `8.4`、`7.4`、`23`、`2022-latest` 仍可能接收补丁 → 允许 env 覆盖，首次实现验证后在示例中记录已验证 tag/digest。
- **[跨方言 DDL 差异]** 自增、布尔、时间和大文本类型不同 → fixture 层定义业务语义契约，各方言独立 DDL，验证统一字段和值而不是原始类型文本。
- **[播种中途失败产生部分基线]** 无法跨四类存储做分布式事务 → 每个数据源内部事务化、整体返回非零、重复 seed 可恢复，并以 verify 作为可用门槛。
- **[测试管理凭据泄露]** Compose 和脚本可能无意传递管理密码 → 管理变量只注入 seeder/数据库容器，topology 只引用 reader 凭据，日志统一脱敏。
- **[重置误删现有数据]** 项目已有 PostgreSQL/RabbitMQ → 四个测试卷显式命名，reset 要求 `--yes` 且按 allowlist 删除，禁止使用项目级 `down -v`。
- **[Redis ACL 与网关命令不一致]** cluster-aware 或扫描实现可能需要额外命令 → 先用实际 gateway 集成测试确定最小命令集，仍不授予写命令给 reader。

## Migration Plan

1. 增加 fixture、seeder/verifier 和它们的单元测试，先在进程级验证幂等与失败传播。
2. 增加 `.env.example`、本地 `.env` 变量和 topology `agent_test` 配置，验证 secret ref 可解析且无明文凭据。
3. 增加四个 Compose 服务、健康检查、命名卷及 seeder 服务，运行 `docker compose config`。
4. 在 ARM64 当前主机实际执行 `up`、二次 `seed`、`verify`，确认 SQL Server 模拟、MySQL 和两套 Redis 均可用。
5. 启动 `real-tools` 与 Agent 运行路径，执行两个基地的 schema、数据库、Redis 工具 smoke。
6. 执行 `reset --yes`，确认仅删除测试卷；重新 `up` 验证可从空环境恢复。

回滚时删除 `agent-test-data` profile 服务、测试脚本、fixture、配置项和四个测试命名卷。生产数据库迁移和现有 API 均不受影响。

## Open Questions

- 实施时应记录当前主机实际验证通过的 SQL Server 镜像 digest；若 QEMU/Rosetta 无法健康启动，需要改用 x86-64 Docker 主机完成完整验收。
- Redis reader ACL 的最小命令集合需要依据现有 `GET`/`SCAN` 实现的实际命令轨迹确认，不能仅按文档猜测。
