## 1. 现状基线与失败用例

- [x] 1.1 梳理 `PlatformTopologySnapshotBuilder`、`internal_api_platform.app._load_topology_snapshot`、`PlatformService.config_status` 当前行为，记录 DB source、YAML fallback、database-invalid 的实际路径。
- [x] 1.2 新增 DB-backed snapshot 单元测试：启用 environment/base/workshop/resource binding/access grant 后，runtime snapshot source 为 `database`，revision/resource_count/access policy 正确。
- [x] 1.3 新增 DB empty 测试：没有启用 topology 时 source 为 `database-empty`；配置 YAML fallback 时 runtime source 才允许变为 `yaml`。
- [x] 1.4 新增 DB invalid 测试：数据库存在启用 topology 但 resource binding 缺少必要运行时字段时 source 为 `database-invalid`，并确认不会回退 YAML。

## 2. Runtime 装配与 Health/Debug

- [x] 2.1 加固 `_load_topology_snapshot`：明确 `database`、`database-empty`、`database-invalid`、`database-error`、`yaml` 分支，确保 invalid fail closed。
- [x] 2.2 确认或补齐 `/health` 输出：返回 `config.source`、`revision` 或 `config_hash`、`resource_count`、`valid`、`errors`，且字段名稳定可测。
- [x] 2.3 如 `/health` 不足以排障，新增只读 debug endpoint；否则在设计和文档中明确复用 `/health.config`。
- [x] 2.4 增加 health/debug 测试，覆盖 database、database-empty、database-invalid、yaml fallback，并确认响应不含 secret 明文。

## 3. DB-backed 工具链验证

- [x] 3.1 增加 Internal API Platform service-level 测试：使用 DB-backed topology 调用 `/tools/resolve`，验证 registry 和 access policy 来自 PostgreSQL。
- [x] 3.2 增加授权测试：allow grant 允许目标，disabled grant 或高优先级 deny grant 拒绝目标，并记录安全错误。
- [x] 3.3 增加 DB-backed database tool 测试：fake executor 下仍执行只读 SQL、车间表前缀、limit 和响应摘要规则。
- [x] 3.4 增加 DB-backed Redis/Loki tool 测试：fake 或注入式 gateway 下仍执行 key namespace、selector、时间范围、行数和脱敏规则。
- [x] 3.5 增加禁用 resource binding 测试：禁用资源不进入 snapshot，相关工具解析失败。

## 4. Platform Config API 验证闭环

- [x] 4.1 增加 `/api/platform/import/topology-yaml` 到 `/api/platform/topology-snapshot` 的测试，确认导入后 snapshot 为 DB-backed 且包含资源数量、revision/hash 和访问授权摘要。
- [x] 4.2 增加 platform config API 写入/禁用资源后的 snapshot 变化测试，确认 revision/hash 可观测变化。
- [x] 4.3 增加 secret reference 测试：public snapshot、health/debug、工具错误和审计摘要均不返回解析后的真实 secret。
- [x] 4.4 确认配置 repository 只访问 `platform_*` 表，不读取 agent job、message、tool call 运行表。

## 5. 本地 Smoke 与文档

- [x] 5.1 新增 `docs/db-backed-platform-config-runtime-test.md`，记录导入 YAML、查询 snapshot、重启/启动 internal-api-platform、检查 `/health.config.source=database`、调用 `/tools/resolve` 的命令和预期输出。
- [x] 5.2 更新 `README.md` 和 `backend/README.md`，明确 DB-backed runtime 验证流程、YAML fallback 边界、配置修改后的重启或 reload 语义。
- [x] 5.3 增加 Docker Compose smoke 命令：`api-server` 写 DB 配置，`internal-api-platform` 从 DB 启动，`agent-worker` 通过 `INTERNAL_API_BASE_URL=http://internal-api-platform:9000` 调用工具。
- [x] 5.4 记录 opt-in 真实 Loki/MySQL 验证方式，并明确默认测试不依赖真实外部系统。

## 6. 最终校验

- [x] 6.1 运行 `.venv/bin/pytest backend/tests`，确认新增和既有测试通过。
- [x] 6.2 运行 `.venv/bin/mypy backend/app` 和 `.venv/bin/ruff check .`。
- [x] 6.3 运行 `openspec validate validate-db-backed-platform-config-runtime --strict`。
- [x] 6.4 运行 `openspec validate --specs`，确认新增 delta 不破坏主规格。
- [x] 6.5 核对 proposal、design、specs、tasks 与实现一致，记录未完成的真实外部系统验证前提。
