## 1. 平台模块升级与骨架

- [ ] 1.1 新增 `backend/app/modules/internal_api_platform/`，按 `domain / application / infrastructure / api` 分层建包。
- [ ] 1.2 迁移现有 Loki 实现与 envelope/error/脱敏 helper 到新模块对应层，保持行为不变。
- [ ] 1.3 保留 `backend/app/local_internal_api_platform.py` 为兼容入口（re-export `create_app`），确认 Compose 启动目标无需修改。
- [ ] 1.4 更新受影响的现有测试 import，保证回归通过。

## 2. 拓扑领域模型与配置

- [ ] 2.1 定义 domain：`Environment` / `Base`（业务 code，基地级 engine）/ `Workshop`（逻辑分区）/ `ResourceKind` / `DatabaseEngine`。
- [ ] 2.2 定义寻址值对象 `TargetRef(environment, base, workshop?, kind)` 与 `ResourceBinding`。
- [ ] 2.3 实现拓扑 YAML schema 与加载器，密钥用 `*_ref` 引用，明文从环境/secret 源解析。
- [ ] 2.4 实现 `TopologyRegistry`（不可变内存投影）与 `ResolveTargetService`，未知 env/base/workshop 返回非 retryable 错误。
- [ ] 2.5 提供三九（观澜 + GL001/GL002，mysql）与 mmk（degenerate 无车间）样例 YAML + seed。
- [ ] 2.6 单元测试：完整三层解析、degenerate 解析、缺 workshop 拒绝、未知目标拒绝、secret 不落明文。

## 3. 多方言只读 SQL 安全

- [ ] 3.1 引入 SQL 分析依赖（如 `sqlglot`），实现注释剥离、单语句校验、只读首关键字与禁止 token 校验。
- [ ] 3.2 实现按方言的只读陷阱拦截：`SELECT INTO`、`FOR UPDATE`、PL/SQL 匿名块 / 批处理。
- [ ] 3.3 实现表名提取（FROM/JOIN/WITH），去 schema/引号并按方言折叠大小写。
- [ ] 3.4 实现车间表前缀强制（`GL001_EBR_`）：无前缀拒绝、跨车间拒绝；degenerate base 跳过前缀但仍只读。
- [ ] 3.5 实现按方言限行（MySQL `LIMIT` / SQL Server `TOP`/`OFFSET FETCH` / Oracle `FETCH FIRST`）与响应字节上限、截断标记。
- [ ] 3.6 单元测试矩阵：三方言 ×（正确前缀 / 缺前缀 / 跨车间 / 变异注释 / 多语句 / INTO / FOR UPDATE / 超限截断）。

## 4. 数据库网关（多引擎执行）

- [ ] 4.1 定义 `QueryExecutor` port 与 `MysqlExecutor` 实现，走只读账号 + 语句 timeout。
- [ ] 4.2 实现 `SqlServerExecutor` 与 `OracleExecutor`（优先 `oracledb` thin、`pymssql`）。
- [ ] 4.3 实现 `QueryDatabaseService`：resolve -> access -> SQL 安全 -> execute -> 截断 -> summary。
- [ ] 4.4 错误分类：连接/超时 retryable，策略/语法 non-retryable，错误信息脱敏。
- [ ] 4.5 端到端先打通 MySQL（三九观澜 GL001），再补 SQL Server / Oracle。

## 5. 基地级 Redis / Loki 网关

- [ ] 5.1 实现按 base 路由的 `RedisGateway`，只读命令白名单（get / bounded scan）。
- [ ] 5.2 实现车间 key 前缀约束：GET/SCAN 必须落在 `workshop.redis_key_prefix` 内，禁止 `*`。
- [ ] 5.3 将现有 Loki gateway 改为按 base 实例化，注入 workshop label，叠加现有 selector/时间/行数上限。
- [ ] 5.4 degenerate base：无 workshop 时不加前缀/label，仍保留 bound。
- [ ] 5.5 单元测试：基地路由、车间前缀内/外、mutating 命令拒绝、Loki label 注入、上游超时 retryable。

## 6. 平台访问控制与审计

- [ ] 6.1 定义 `AccessScope`（user -> 可访问 env/base/workshop）与 YAML/seed 配置。
- [ ] 6.2 实现 `AuthorizeService`：解析 caller（`X-Agent-User-Id`，可选平台 token），越权非 retryable。
- [ ] 6.3 access allow/deny 审计（脱敏，含 caller + 目标 + 原因）。
- [ ] 6.4 `permission_policy` 预留 `resource_type` 扩展（environment/base/workshop）。
- [ ] 6.5 单元测试：in-scope 通过、跨 base 拒绝、跨 workshop 拒绝、缺身份拒绝、deny 审计。

## 7. 工具契约升级（Agent 侧对接）

- [ ] 7.1 升级平台 HTTP 契约：`/tools/database|redis|loki` 支持 `environment/base/workshop` 结构化字段。
- [ ] 7.2 更新 `InternalApiClient` 协议与 `HttpInternalApiClient`、`FakeInternalApiClient`、`ReadOnlyToolService._execute`。
- [ ] 7.3 更新 `mcp_tool_registry` 与 Claude tool JSON schema，加入寻址字段并保留兼容旧 `datasource`。
- [ ] 7.4 更新 mock platform 与相关测试，保证结构化寻址闭环。

## 8. 依赖、Compose 与文档

- [ ] 8.1 `pyproject.toml` 增加 SQL 分析与数据库驱动依赖，评估容器体积。
- [ ] 8.2 更新 `backend/Dockerfile`（如 SQL Server/Oracle 驱动系统依赖）。
- [ ] 8.3 更新 `docker-compose.yml` 与 `.env.example`：三九/mmk 拓扑与 secret 引用样例。
- [ ] 8.4 更新 README/平台文档：拓扑寻址、表前缀规则、多方言安全、验证步骤。

## 9. 最终检查

- [ ] 9.1 运行 `make check`（格式、lint、类型、pytest/unittest）。
- [ ] 9.2 运行 `openspec validate add-internal-platform-topology-and-multi-db`。
- [ ] 9.3 端到端验证：三九观澜 GL001/GL002（MySQL）+ mmk degenerate，确认只读、车间隔离、跨基地/跨车间拒绝生效。
- [ ] 9.4 核对 proposal/specs/design/tasks 与实现范围一致，change 可进入 apply 阶段。
