## 1. 领域模型与配置

- [x] 1.1 扩展 `RedisConnection`：增加 `mode`（standalone/cluster）、`nodes`；cluster 时明确 `db` 语义（忽略或校验非 0）
- [x] 1.2 扩展 Oracle 相关绑定字段：`oracle_client_mode`、`oracle_compat`、`use_sid`、可选 `connect_descriptor`
- [x] 1.3 更新 YAML topology 加载与示例配置，覆盖 cluster Redis 与 legacy Oracle 样例
- [x] 1.4 更新 platform_config snapshot / importer / validation，使 DB registry 与 YAML 字段一致

## 2. Redis Cluster 网关

- [x] 2.1 改造 `RealRedisGateway._connect`：按 mode 选择 `redis.Redis` 或 `redis.RedisCluster`
- [x] 2.2 确保 GET / 有界 SCAN 在 cluster 下仍强制车间 key 前缀策略
- [x] 2.3 补充单元测试：mode 选择、缺 nodes 校验失败、前缀策略在 cluster 绑定下仍生效

## 3. Oracle thick 与旧版兼容

- [x] 3.1 实现进程级 Instant Client 初始化（有库则 init，失败可观测；`thick` 强制失败不静默回退）
- [x] 3.2 改造 `OracleExecutor`：支持 thin/thick/auto、SID vs service name、connect_descriptor
- [x] 3.3 方言限行：`oracle_compat=legacy` 使用 ROWNUM 改写，默认 modern 保持 FETCH FIRST
- [x] 3.4 补充单元测试：DSN/SID、ROWNUM vs FETCH FIRST、thick 不可用时的错误分类

## 4. Docker Instant Client

- [x] 4.1 在 `internal-api-platform` Dockerfile stage 安装依赖库与 Oracle Instant Client，配置 `LD_LIBRARY_PATH` / lib dir
- [x] 4.2 确认 api-server / agent-worker 镜像不引入 Instant Client
- [x] 4.3 更新构建/运维文档：Instant Client 版本、许可注意、本地无 client 时的 thin 开发路径

## 5. 验证与收尾

- [x] 5.1 跑现有 internal_api_platform / platform_config 相关单测，修复回归
- [x] 5.2（可选）增加 `RUN_REDIS_CLUSTER_INTEGRATION` / `RUN_ORACLE_THICK_INTEGRATION` 门控集成测试骨架
- [x] 5.3 更新 `docs/internal-api-platform.md` 中 Redis mode 与 Oracle thick/legacy 配置说明
