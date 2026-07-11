## 1. Fixture 契约与播种基础

- [x] 1.1 定义 MySQL/SQL Server 共享的 MES fixture manifest，固定六张业务表、字段语义、业务 ID、时间基准、行数和预期异常。
- [x] 1.2 为 MySQL 编写可重复执行的 schema/reader 权限/seed 实现，覆盖正常订单、停滞订单、设备、告警、库存、质检和事件。
- [x] 1.3 为 SQL Server 编写语义等价且可重复执行的 schema/reader 权限/seed 实现，处理 `dbo`、类型和批处理语法差异。
- [x] 1.4 从本次 agent-test-data 测试库中移除 Oracle seed/verify 路径，保留平台 Oracle 能力不变。
- [x] 1.5 定义两套 Redis fixture 和 ACL，分别限制 reader 与 seeder 权限，并写入设备、订单、库存缓存及约定的不一致值。
- [x] 1.6 实现统一 seeder CLI，按数据源报告进度和安全错误，支持已有数据卷幂等恢复且任一数据源失败时返回非零。
- [x] 1.7 为 fixture manifest、方言语句选择、二次播种、Redis namespace 清理、错误传播和日志脱敏增加单元测试。

## 2. Compose 测试基础设施

- [x] 2.1 在 `docker-compose.yml` 的 `agent-test-data` profile 增加 MySQL 8.4、SQL Server 2022 数据库服务。
- [x] 2.2 在同一 profile 增加 `agent-test-redis-mysql`、`agent-test-redis-sqlserver` 两个独立 Redis 7.4 服务及 ACL 配置。
- [x] 2.3 为四个长期服务增加真实连接健康检查、资源合理的有界重试、可配置非默认宿主端口和四个显式命名卷。
- [x] 2.4 增加只包含测试管理凭据和数据库驱动的 seeder/verifier Docker target 与一次性 Compose 服务，等待四个依赖健康后运行。
- [x] 2.5 为 SQL Server 显式配置可覆盖的 `linux/amd64` platform，并为 ARM64 预检与失败提示保留入口。
- [x] 2.6 验证默认 `docker compose config` 不启动测试服务，`agent-test-data` 与 `real-tools` profile 组合可正确渲染全部依赖、变量、卷和健康检查。

## 3. 环境变量与平台拓扑

- [x] 3.1 在 `.env.example` 增加镜像、platform、宿主端口、数据库管理/只读凭据和两套 Redis reader/seeder 凭据，并写明本地用途与 ARM64 限制。
- [x] 3.2 在本地 `.env` 增加对应可运行值，不覆盖现有真实本地配置，也不把值输出到测试日志或提交差异。
- [x] 3.3 在 `backend/config/internal_platform_topology.example.yaml` 增加 `agent_test/mysql`、`agent_test/sqlserver` 两个基地及一一对应的 standalone Redis secret ref。
- [x] 3.4 增加 topology/config 测试，确认两种测试数据库引擎、两个不同 Redis host、SQL Server `dbo` 和全部 secret ref 可解析。
- [x] 3.5 增加安全测试，确认 topology/API 摘要不泄露连接字段，Internal API Platform/Agent Worker 环境不包含测试管理凭据。

## 4. 生命周期命令与安全边界

- [x] 4.1 实现 `scripts/agent_test_data.sh up`：检查变量和主机架构、启动 profile、等待四个服务健康、播种并验证。
- [x] 4.2 实现 `seed`：在已运行服务上恢复固定基线，并逐个输出两个数据库和两个 Redis 的结果。
- [x] 4.3 实现 `verify`：直接检查 schema、行数、哨兵值、异常链、Redis key、只读权限和基地隔离，任何一项失败即返回非零。
- [x] 4.4 扩展 `verify` 的平台层检查，调用现有 topology resolve、schema directory、数据库 query 和 Redis GET/SCAN，覆盖两个基地并验证写请求仍被拒绝。
- [x] 4.5 实现 `reset --yes`：按 allowlist 停止测试服务并删除四个显式命名卷；缺少确认参数时拒绝执行，禁止调用项目级 `down -v`。
- [x] 4.6 为生命周期脚本增加命令解析、ARM64 警告、部分失败汇总和 reset 删除范围的自动化测试。

## 5. 真实运行验证

- [ ] 5.1 在当前 ARM64 Docker 环境拉取并启动 MySQL 和两个 Redis，确认使用原生架构且健康检查通过。
- [ ] 5.2 在当前 ARM64 Docker 环境以 `linux/amd64` 启动 SQL Server，记录实际镜像 digest、启动耗时和健康结果；若失败则在 x86-64 Docker 主机完成验收并记录限制。
- [ ] 5.3 连续执行两次 seed，比较两个数据库表行数、固定业务行和两套 Redis key/值，证明无重复且结果一致。
- [ ] 5.4 使用数据库 reader 与 Redis reader 凭据验证允许读取，并验证数据库写入和 Redis 写命令均被拒绝。
- [ ] 5.5 启动 `real-tools` profile，通过 Internal API Platform 对两个基地执行 resolve、schema directory、方言只读查询和独立 Redis 查询 smoke。
- [ ] 5.6 执行 `reset --yes` 前后记录卷清单，确认主 PostgreSQL/RabbitMQ 及其他数据未被删除，再从空测试卷执行一次完整 `up`。

## 6. 文档与规格校验

- [x] 6.1 更新后端/开发文档，记录资源要求、profile 启动、up/seed/verify/reset、两个基地地址和固定异常场景。
- [x] 6.2 增加后续 Agent 调试示例，要求 Agent 分别查询数据库和对应 Redis，并以证据指出缓存不一致，不向 Agent 暴露连接信息。
- [x] 6.3 运行 seeder/lifecycle/config 相关测试、`docker compose config --quiet` 及 profile 组合配置检查。
- [x] 6.4 运行 `.venv/bin/pytest backend/tests -q`、`.venv/bin/ruff check .` 和 `.venv/bin/mypy backend/app`，修复本变更引入的回归。
- [x] 6.5 运行 `openspec validate add-agent-test-data-environment --strict` 和 `openspec validate --specs`，确保 change 与主规格均通过校验。
