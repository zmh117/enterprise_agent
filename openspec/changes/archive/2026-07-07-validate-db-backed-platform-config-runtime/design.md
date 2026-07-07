## Context

当前平台已经具备两套配置来源：

- `platform_config` 模块把环境、基地、车间、资源绑定、密钥引用和访问授权持久化到 PostgreSQL。
- `internal_api_platform` 仍保留 YAML topology 作为本地 bootstrap/fallback 来源。

现有实现中 `PlatformTopologySnapshotBuilder` 可以构造 `database`、`database-empty`、`database-invalid` 等 runtime snapshot source，`internal-api-platform` 启动时也会把 `config.source/revision/errors/resource_count` 暴露到 health。这个 change 不重做表结构，重点是验证这条运行时路径真实闭环：配置写入 PostgreSQL 后，工具平台必须从 DB snapshot 构造 registry/access policy，并且工具调用、授权、禁用资源、secret 边界和只读策略都仍然生效。

## Goals / Non-Goals

**Goals:**

- 证明 `internal-api-platform` 优先消费 PostgreSQL platform configuration。
- 明确 DB empty、DB invalid、DB error、YAML fallback 的行为边界。
- 增加运行时可观测信息，能从 health/debug 判断当前配置来源和 revision/hash。
- 增加确定性测试和本地 smoke 文档，覆盖 DB-backed 配置到 read-only tool endpoint 的完整路径。
- 保持第一版只读诊断边界，不引入写库、删 Redis、重启服务或代码修改能力。

**Non-Goals:**

- 不新增 Web 前端。
- 不引入 Vault/KMS 真实密钥后端；本阶段仍只验证 secret reference 边界和 env resolver。
- 不要求连接真实 SQL Server、Oracle、Redis 或生产 Loki；真实外部源验证可以作为可选 smoke。
- 不实现复杂多 Agent 编排或运行时 DAG。

## Decisions

### 1. 以 PostgreSQL snapshot 作为 runtime source of truth

`internal-api-platform` 启动时先读取 `platform_*` 表并构造 `RuntimeTopologySnapshot`。当 snapshot source 为 `database` 时，运行时 registry、access policy、resource binding 全部来自 DB；`INTERNAL_PLATFORM_TOPOLOGY_FILE` 只作为本地 bootstrap fallback，不参与覆盖。

替代方案是每次工具调用实时查询 PostgreSQL。这个方案会让工具调用路径更复杂，也会把配置库短暂抖动放大到诊断请求。MVP 使用启动时 snapshot 更简单，后续 Web 平台需要热更新时再设计 revision polling 或 reload endpoint。

### 2. DB invalid 必须 fail closed，不静默回退 YAML

当数据库存在启用 topology 但资源绑定缺少 endpoint、engine、secret ref 或结构不完整时，source 必须是 `database-invalid`，health 为 degraded，工具解析应表现为不可用或安全失败。即使设置了 YAML 文件，也不能回退到 YAML，否则 Web 配置错误会被本地文件掩盖。

替代方案是 invalid 时自动 fallback YAML。拒绝该方案，因为这会让生产排障误判当前生效配置，也可能绕过 Web 平台的禁用和授权变更。

### 3. DB empty 才允许本地 YAML fallback

当数据库没有启用 environment/topology，且显式配置了 `INTERNAL_PLATFORM_TOPOLOGY_FILE`，才允许使用 YAML fallback，source 标记为 `yaml`。没有 YAML 时 source 保持 `database-empty`，工具平台应以空 topology 启动并在解析目标时失败。

这个边界让本地开发仍然可以用 YAML 启动，同时不影响 DB-backed 配置上线后的确定性。

### 4. 用 fake/stub gateway 做确定性 runtime 验证

单元和集成测试应优先使用 fake DB executor、fake Redis/Loki 或注入式 service，验证 addressing、authorization、source、read-only policy 和 response metadata。真实 MySQL/Loki 作为 opt-in smoke，不作为默认 CI 前提。

这样可以避免测试依赖外部系统，同时仍能证明 runtime wiring 没有绕过 Internal API Platform。

### 5. Health/debug 必须返回可判断的信息，但不泄漏密钥

`/health` 或 debug 输出必须包含 config source、revision/hash、resource_count、valid/errors。配置和工具响应只能出现 secret reference 或脱敏摘要，不能出现解析后的 password/token/api key。

## Risks / Trade-offs

- [Risk] 启动时 snapshot 不支持配置热更新。  
  Mitigation: 本 change 明确这是当前 MVP 行为，并在文档中说明修改 DB 配置后需要重启 `internal-api-platform` 或未来实现 reload。

- [Risk] 本地 YAML fallback 继续存在，容易误以为使用了 DB。  
  Mitigation: health/debug 和 smoke 文档必须要求检查 `config.source=database`，并覆盖 DB invalid 不回退场景。

- [Risk] 测试使用 fake gateway 可能漏掉真实驱动问题。  
  Mitigation: 默认测试验证运行时装配和策略；真实 MySQL/Loki 验证放到 opt-in smoke 文档。

- [Risk] secret resolver 在运行时解析 env 后可能被错误写入日志或响应。  
  Mitigation: 增加 secret 不泄漏测试，覆盖 public snapshot、health、工具错误和审计摘要。

## Migration Plan

1. 不新增迁移表结构，优先复用 `004_platform_config_and_workflow.sql`。
2. 增加或修正 seed/import，让本地 `local-user` 可以导入 topology 并拥有只读访问授权。
3. 扩展测试覆盖 DB-backed snapshot、fallback、invalid、health 和工具端点。
4. 更新中文文档，提供从 YAML import 到 DB-backed runtime smoke 的完整命令。
5. 回滚方式：停止使用 DB-backed 配置或清空启用 topology，保留 `INTERNAL_PLATFORM_TOPOLOGY_FILE` 本地 fallback；生产回滚必须显式确认 source 是否变回 `yaml`。

## Open Questions

- 已决策：本 change 复用 `/health.config` 作为只读 debug 输出，不新增 `/debug/config` endpoint。
- 已决策：第一版接受启动时 snapshot，修改 DB-backed platform config 后重启 `internal-api-platform` 生效；runtime reload endpoint 留到后续 change。
