## Why

`agent-platform-config-api` 已经把 topology、resource binding、secret reference 和 access grant 落到 PostgreSQL，但还需要证明 `internal-api-platform` 运行时真的优先使用 DB-backed snapshot，而不是继续依赖 YAML/env。这个 change 用集成测试、运行时 health/debug 和本地 smoke 流程把 DB 配置到工具调用的闭环验证清楚，为后续 Web 配置平台上线打基础。

## What Changes

- 增加 DB-backed runtime 配置验证：从 `/api/platform/import/topology-yaml` 或平台配置 API 写入 PostgreSQL 后，`internal-api-platform` 启动时必须从数据库构造 topology、resource binding 和 access policy。
- 明确 YAML fallback 边界：只有数据库没有启用 topology 且配置允许 fallback 时才使用 YAML；数据库存在但无效时必须暴露 `database-invalid`，不能静默回退。
- 增加 health/debug 可观测性：`internal-api-platform` 必须返回配置来源、revision/hash、资源数量和配置错误摘要，便于判断当前运行时用的是 database 还是 yaml。
- 增加端到端验证：通过 Docker Compose 或本地进程验证 `api-server -> PostgreSQL platform_config -> internal-api-platform -> read-only tools` 路径，并覆盖授权、禁用资源、secret 不泄漏、只读策略仍生效。
- 更新中文 README/测试记录，给出可复现 curl 命令和预期输出。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `readonly-tool-platform`: 加强 DB-backed snapshot 在 Internal API Platform 运行时的使用、fallback、health/debug 和只读工具验证要求。
- `platform-config-api`: 增加平台配置写入后可被运行时消费的验证要求，包括 import/upsert 后 snapshot 与运行时来源一致。
- `platform-config-registry`: 增加配置 revision/hash、禁用资源排除、secret reference runtime 解析边界和访问授权投影的一致性要求。

## Impact

- 代码：`backend/app/modules/internal_api_platform/`、`backend/app/modules/platform_config/`、`backend/app/bootstrap.py`、`backend/app/shared/config.py`。
- 测试：新增或扩展 platform config snapshot、internal API platform runtime、HTTP endpoint 和 Compose smoke 相关测试。
- 文档：更新 `README.md`、`backend/README.md` 或新增 `docs/db-backed-platform-config-runtime-test.md`。
- 外部系统：不新增写操作；仍保持只读诊断边界。真实 DB/Redis/Loki 可用时仅做只读验证，默认可用 fake/stub gateway 完成确定性测试。
