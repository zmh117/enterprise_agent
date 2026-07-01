## 1. 平台模块升级与骨架

- [x] 1.1 新增 `backend/app/modules/internal_api_platform/`，按 `domain / application / infrastructure / api` 分层建包。
- [x] 1.2 迁移现有 Loki 实现与 envelope/error/脱敏 helper 到新模块对应层，保持行为不变。（复用 `build_logql`/`summarize_loki_response`/`redact_text`，新模块 loki client 自管 fetch 以支持 workshop label）
- [x] 1.3 新增 `backend/app/internal_api_platform.py` 正式入口（re-export `create_app`）；保留旧 `local_internal_api_platform` 入口/服务用于回退（决策：flip_now，Compose 新增 `real-tools` profile 服务）。
- [x] 1.4 更新受影响的现有测试 import，保证回归通过。（新增为附加模块，旧模块与测试未改动，71 passed）

## 2. 拓扑领域模型与配置

- [x] 2.1 定义 domain：`Environment` / `Base`（业务 code，基地级 engine）/ `Workshop`（逻辑分区）/ `ResourceKind` / `DatabaseEngine`。
- [x] 2.2 定义寻址值对象 `TargetRef(environment, base, workshop?, kind)` 与 `ResourceBinding`。
- [x] 2.3 实现拓扑 YAML schema 与加载器，密钥用 `*_ref` 引用，明文从环境/secret 源解析。
- [x] 2.4 实现 `TopologyRegistry`（不可变内存投影）与 resolve，未知 env/base/workshop 返回非 retryable 错误。
- [x] 2.5 提供三九（观澜 + GL001/GL002，mysql）与 mmk（degenerate 无车间）样例 YAML（`backend/config/internal_platform_topology.example.yaml`）。
- [x] 2.6 单元测试：完整三层解析、degenerate 解析、缺 workshop 拒绝、未知目标拒绝、secret 不落明文。

## 3. 多方言只读 SQL 安全

- [x] 3.1 引入 SQL 分析依赖（`sqlglot`），实现注释剥离、单语句校验、只读首关键字与禁止 token 校验。
- [x] 3.2 实现按方言的只读陷阱拦截：`SELECT INTO`、`FOR UPDATE`、PL/SQL 匿名块 / 批处理。
- [x] 3.3 实现表名提取（FROM/JOIN/WITH），去 schema/引号并按方言折叠大小写。
- [x] 3.4 实现车间表前缀强制（`GL001_EBR_`）：无前缀拒绝、跨车间拒绝；degenerate base 跳过前缀但仍只读。
- [x] 3.5 实现按方言限行（MySQL `LIMIT` / SQL Server `TOP` / Oracle `FETCH FIRST`）与截断标记（行数上限；字节上限沿用 Loki summarize）。
- [x] 3.6 单元测试矩阵：三方言 ×（正确前缀 / 缺前缀 / 跨车间 / 多语句 / INTO / FOR UPDATE / PL/SQL / Oracle 折叠 / 限行）。

## 4. 数据库网关（多引擎执行）

- [x] 4.1 定义 `QueryExecutor` port（含 `FakeQueryExecutor`）与 `MysqlExecutor` 实现，只读会话 + 语句 timeout。
- [x] 4.2 实现 `SqlServerExecutor` 与 `OracleExecutor`（`oracledb` thin、`pymssql`，驱动 lazy import）。
- [x] 4.3 实现 `query_database`：resolve -> access -> SQL 安全 -> execute -> 截断 -> summary。
- [x] 4.4 错误分类：连接/超时 -> `UpstreamUnavailable`(retryable)，策略/语法 -> `PolicyViolation`(non-retryable)，错误信息脱敏（仅暴露异常类型名）。
- [x] 4.5 端到端打通 MySQL（真实库 localhost:3306，`SELECT v.* FROM lims.var AS v` → 分析加 `LIMIT` → pymysql 只读执行返回行）；SQL Server / Oracle 待真实实例。

## 5. 基地级 Redis / Loki 网关

- [x] 5.1 实现按 base 路由的 `RedisGateway`（`Fake` + `Real` lazy import），只读命令白名单（get / bounded scan）。
- [x] 5.2 实现车间 key 前缀约束：GET/SCAN 必须落在 `workshop.redis_key_prefix` 内，禁止 `*` / 空 pattern。
- [x] 5.3 新 `HttpLokiClient` 按 base 实例化，注入 workshop label，叠加 selector/时间/行数上限（复用 LogQL/summarize）。
- [x] 5.4 degenerate base：无 workshop 时不加前缀/label，仍保留 bound。
- [x] 5.5 单元测试：车间前缀内/外、bounded scan、Loki label 注入、上游 5xx retryable。

## 6. 平台访问控制与审计

- [x] 6.1 定义 `AccessScope`/`ScopeRule`/`AccessPolicy`（user -> 可访问 env/base/workshop，支持 `*`）与 YAML 配置。
- [x] 6.2 实现授权：路由解析 caller（`X-Agent-User-Id`），越权 -> `AuthorizationError`(403, non-retryable)。
- [x] 6.3 access allow/deny 审计（`internal_api_platform.audit` logger，含 caller + 目标 + decision + reason）。
- [ ] 6.4 `permission_policy` 预留 `resource_type` 扩展（environment/base/workshop）。（DB 迁移预留，YAML 优先，暂缓）
- [x] 6.5 单元测试：in-scope 通过、跨 workshop 拒绝、缺身份拒绝、未知用户拒绝、通配授权。

## 7. 工具契约升级（Agent 侧对接）

- [x] 7.1 平台 HTTP 契约：`/tools/database|redis|loki` 结构化 `environment/base/workshop` 字段（组 1-6 新路由）。
- [x] 7.2 更新 `InternalApiClient` 协议与 `HttpInternalApiClient`、`FakeInternalApiClient`、`ReadOnlyToolService._execute`（可选寻址 kw，缺省不传，兼容旧调用/测试替身）。
- [x] 7.3 Claude tool JSON schema 加入 `environment/base/workshop`（`_ADDRESSING_PROPERTIES`），保留 `datasource`；`ToolRegistry` 白名单不变。
- [x] 7.4 契约闭环测试：Http payload 携带/省略寻址、ReadOnlyToolService 透传至 client（mock platform 忽略额外字段，无需改动）。
- [x] 7.5 ER 上下文→寻址：新平台 `/tools/context/er`、`/tools/context/business-flow` 返回**按访问过滤**的寻址目录（env/base/workshop code + display_name + aliases，无连接信息）；topology 增 display_name/aliases；系统提示词指引模型据目录把自然语言（观澜基地/GL001）映射为寻址字段，禁止臆造目录外 code；Fake ER 附带示例目录。

## 8. 依赖、Compose 与文档

- [x] 8.1 `pyproject.toml` 增加 `sqlglot`/`pyyaml` 为主依赖；DB 驱动（pymysql/pymssql/oracledb/redis）置于可选 extra `database` 以控制镜像体积。
- [x] 8.2 新增 `backend/Dockerfile` `internal-api-platform` stage，仅该镜像安装 DB 驱动（pymysql/pymssql/oracledb thin/redis）控制体积。
- [x] 8.3 `docker-compose.yml` 新增 `internal-api-platform` 服务（profile `real-tools`，挂载拓扑 + secret 引用 env）；`.env.example` 增补 `INTERNAL_PLATFORM_*` 与 `SECRET_*` 样例。
- [x] 8.4 新增 `docs/internal-api-platform.md`：拓扑寻址、表前缀规则、多方言 SQL 安全、Redis/Loki 隔离、访问控制与验证步骤。

## 9. 最终检查

- [x] 9.1 运行 `make check` 核心项（compile/format/lint/typecheck/test/unittest 全绿，76 tests）+ `make openspec-validate`。
- [x] 9.2 `openspec validate add-internal-platform-topology-and-multi-db` 通过。
- [x] 9.3 端到端验证：MySQL 真实库只读执行 + 车间前缀/跨车间/只读拒绝（单测矩阵 + opt-in 集成测试 `RUN_DB_INTEGRATION=1`）；SQL Server / Oracle 待真实实例。
- [x] 9.4 核对 proposal/specs/design/tasks 与实现一致；剩余待真实实例项（SQL Server/Oracle 真库、6.4 DB registry）已在 tasks 标注。
