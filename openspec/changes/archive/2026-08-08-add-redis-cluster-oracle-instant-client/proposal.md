## Why

生产环境中部分基地已部署 Redis Cluster，且仍有旧版 Oracle（如 11g/12c）需通过 Instant Client thick 模式接入；当前 Internal API Platform 仅支持单节点 Redis 与 oracledb thin 模式，无法覆盖这些真实拓扑，阻塞排障工具落地。

## What Changes

- Redis 连接模型扩展为支持 **单节点** 与 **Cluster** 两种模式；Cluster 下按 startup nodes 建连，车间 key 前缀与只读策略保持不变。
- Oracle 连接支持 **thick 模式**（Instant Client），以兼容旧版 Oracle 服务端；必要时按版本选择限行语法（`FETCH FIRST` vs `ROWNUM`）。
- `internal-api-platform` Docker 镜像 **打入 Oracle Instant Client**，启动时初始化 thick client，使容器内可直连旧版 Oracle。
- 拓扑配置（YAML / DB registry）增加 Redis 模式与 Oracle 连接相关字段；单节点 / thin 行为保持向后兼容（非 BREAKING）。

## Capabilities

### New Capabilities

- `oracle-instant-client-runtime`：Internal API Platform 镜像与运行时对 Oracle Instant Client（thick mode）的打包、初始化与旧版 Oracle 兼容连接能力。

### Modified Capabilities

- `base-scoped-redis-loki`：基地级 Redis 支持 Cluster 模式连接，同时保留单节点；车间 key 前缀与只读约束不变。
- `multi-dialect-database-gateway`：Oracle 执行路径支持 thick/Instant Client，并对旧版 Oracle 的限行与连接参数做兼容。
- `internal-platform-topology`：拓扑/绑定模型增加 Redis 模式（standalone/cluster）及 Oracle thick 相关连接配置字段。

## Impact

- **代码**：`RealRedisGateway`、`OracleExecutor`、`RedisConnection` / 拓扑加载（YAML + platform_config snapshot）、SQL 方言限行（Oracle）。
- **镜像**：`backend/Dockerfile` 的 `internal-api-platform` stage 安装 Instant Client 与 `LD_LIBRARY_PATH`；镜像体积增大。
- **依赖**：继续使用 `redis>=5`（Cluster API）、`oracledb` thick；可能需系统库（libaio 等）。
- **配置**：topology YAML / DB `config_json` 新增字段；现有单节点 Redis 与未声明 thick 的 Oracle 配置无需改动即可继续工作。
- **API 契约**：对外 HTTP 工具接口（`/tools/redis/*`、`/tools/database/query`）路径与请求体不变；变更集中在平台侧连接与镜像。
