## Why

当前仓库缺少可由 Docker Compose 一键启动、可重复恢复且覆盖 MySQL、SQL Server、Redis 的真实测试数据环境，导致 Agent 的多方言数据库查询、Schema 预览和数据库与缓存联合诊断只能依赖外部系统或 mock 数据。需要补齐一套隔离的本地测试拓扑和确定性异常数据，作为后续 Agent 调试与回归验证的稳定基线。Oracle 平台能力保留，但本次因测试镜像下载不可用，不纳入本地测试库。

## What Changes

- 在 Docker Compose 中增加 `agent-test-data` profile，提供 MySQL、SQL Server 两个数据库服务，并为两个数据库基地分别提供独立 Redis 服务。
- 为每个服务增加健康检查、独立持久化卷和明确的端口/凭据配置；测试数据服务不进入默认 Compose 启动集合。
- 增加可重复执行的测试数据初始化与校验流程，在两个数据库中建立同构 MES 表结构及确定性正常/异常数据，并向各自 Redis 写入对应缓存、状态和故意不一致的数据。
- 增加明确的启动、重新播种、验证和彻底重置入口，使已有数据卷不会导致初始化脚本被静默跳过。
- 在 `.env`、`.env.example` 和 `backend/config/internal_platform_topology.example.yaml` 中增加 `agent_test` 环境及两个测试基地配置；拓扑只保存 secret ref，不内联凭据。
- 为 ARM64 开发机明确镜像架构策略：MySQL、Redis 使用可用的原生多架构镜像；SQL Server 使用 `linux/amd64` 测试配置并在启动前明确其模拟运行限制。

## Capabilities

### New Capabilities

- `agent-test-data-environment`: 定义本地多数据库与独立 Redis 测试拓扑、确定性 MES 测试数据、幂等播种、健康验证和重置生命周期。

### Modified Capabilities

无。现有拓扑解析、多方言只读网关和基地级 Redis 路由契约保持不变，本变更提供符合这些契约的本地测试实例与配置。

## Impact

- **Compose**：`docker-compose.yml` 新增 4 个数据服务、播种/验证服务、profile、健康检查和命名卷。
- **配置**：`.env`、`.env.example`、`backend/config/internal_platform_topology.example.yaml` 增加本地测试基地的数据库与 Redis secret ref。
- **测试数据**：新增 MySQL、SQL Server 方言脚本或等价播种代码，以及两套 Redis fixture。
- **开发脚本与文档**：新增启动、播种、验证、重置命令和 Agent 调试示例。
- **资源**：完整环境会增加本地内存、磁盘与首次拉取时间，尤其是 SQL Server；默认 profile 隔离避免影响现有开发环境。
- **API/安全**：不新增生产 API，不改变 Agent 工具请求契约，不放宽只读网关；写权限仅存在于显式运行的测试数据播种路径。
