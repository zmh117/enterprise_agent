## Context

现有 Internal API Platform（`backend/app/modules/local_internal_api_platform/`）是本地 stub：扁平 `datasource="default"`、单 Loki upstream、DB/Redis 为 placeholder。真实排障需要面对如下拓扑：

```text
Environment
  三九 sanjiu
    └─ Base 观澜 guanlan   (engine=mysql, 基地级一种引擎)
         ├─ Database (基地级连接)
         │     车间通过表前缀区分: GL001_EBR_*, GL002_EBR_*
         ├─ Redis    (基地级)   车间通过 key 前缀区分: GL001:*, GL002:*
         ├─ Loki     (基地级)   车间通过标签区分: {workshop="GL001"}
         └─ Workshops: GL001, GL002   ← 逻辑分区，非物理资源
  mmk
    └─ Base (无车间分层, degenerate)
         ├─ Database / Redis / Loki (基地级)
```

关键结论（来自需求确认）：

- **基地用业务 code**（`guanlan`），IP/host 只是内部连接细节，不暴露给 Agent/模型。
- **引擎在基地级**：一个基地一种引擎；车间不改变引擎。
- **车间是逻辑分区**：DB/Redis/Loki 都是基地级资源，车间只通过命名区分。
- **`local_internal_api_platform` 升级为正式 `internal_api_platform` 模块**，不再是 dev 替身。
- **配置先 YAML + seed**，密钥引用而非明文，后续可迁移 DB registry。

## Goals / Non-Goals

**Goals:**

- 建立 Environment/Base/Workshop 拓扑领域模型与结构化寻址解析。
- 多方言只读数据库网关（MySQL/SQL Server/Oracle）：只读、方言分页/引用、强制车间表前缀、跨基地/跨车间隔离。
- 基地级 Redis/Loki 网关：按基地路由，按车间 code 约束 key 前缀 / 日志标签。
- 平台侧访问控制（第二层）+ 审计。
- 把 platform 升级为分层模块，工具契约支持结构化寻址，同时保持只读边界。

**Non-Goals:**

- 不引入写操作、审批、沙盒。
- 不做拓扑配置 Web 后台或 DB 持久化后台（YAML+seed 为主，DB 仅预留）。
- 不改 Claude/RabbitMQ/DingTalk 主流程。
- 不支持 MySQL/SQL Server/Oracle 之外的引擎。

## Decisions

### 1. 模块升级：local_internal_api_platform → internal_api_platform（分层）

```text
backend/app/modules/internal_api_platform/
  domain/
    topology.py        Environment / Base / Workshop / ResourceKind / DatabaseEngine
    addressing.py      TargetRef(env, base, workshop, kind) 值对象
    binding.py         ResourceBinding(resolved) 值对象
    sql/
      readonly.py      ReadonlySqlQuery 值对象 + 只读校验
      table_prefix.py  表名提取 + 车间前缀策略
      dialect.py       Dialect 枚举 + 分页/引用规则
    redis_policy.py    KeyNamespacePolicy
    loki_policy.py     SelectorPolicy + workshop label
    access.py          AccessScope / 决策
  application/
    resolve_target_service.py     TargetRef -> ResourceBinding
    query_database_service.py
    query_redis_service.py
    query_loki_service.py
    authorize_service.py
  infrastructure/
    config/            YAML 加载 + secret 解析
    registry/          TopologyRegistry（内存投影，预留 DB 实现）
    db/                MysqlExecutor / SqlServerExecutor / OracleExecutor
    redis/             RedisGateway（按 base 实例）
    loki/              LokiGateway（复用现有，按 base 拆）
  api/
    routes.py          HTTP 适配，仅编排，不含业务规则
  app.py               create_app 装配
```

兼容入口：保留 `backend/app/local_internal_api_platform.py` re-export，或把 Compose command 迁移到新入口（见 Risk）。

替代方案：继续在现有 flat 文件加 if/else。否决——三九多基地/多车间/多方言下会复制粘贴爆炸。

### 2. 结构化寻址契约（方案 C：粗权限 + 结构化语义）

工具请求字段升级：

```json
POST /tools/database/query
{
  "environment": "sanjiu",
  "base": "guanlan",
  "workshop": "GL001",
  "sql": "select * from GL001_EBR_order where status='WAITING_MATERIAL'",
  "limit": 100
}
```

- Redis/Loki 请求同样带 `environment/base/workshop`（workshop 用于 key 前缀 / label）。
- `project_code` 仍保留作为 Agent 侧粗粒度权限（可映射到 environment）。
- 平台把 `environment/base/workshop + kind` 解析为 `ResourceBinding`；解析失败 = 非 retryable。

对 Agent 侧影响：`InternalApiClient` 协议、`HttpInternalApiClient`、`ReadOnlyToolService._execute`、`mcp_tool_registry` 工具 schema、Claude tool JSON schema 都要加字段。ER/业务流上下文工具帮助模型把自然语言（观澜、GL001）映射到寻址字段。

替代方案 A（扁平 datasource code，如 `sanjiu-guanlan-gl001-db`）：兼容性好但 code 爆炸、对模型不友好；作为高级/debug 直达通道可保留，但默认用结构化。

### 3. 拓扑配置 YAML（先文件后 DB）

```yaml
environments:
  sanjiu:
    bases:
      guanlan:
        engine: mysql
        database:
          host_ref: secret://sanjiu/guanlan/db_host
          port: 3306
          database: erp
          user_ref: secret://sanjiu/guanlan/db_user
          password_ref: secret://sanjiu/guanlan/db_password
        redis:
          host_ref: secret://sanjiu/guanlan/redis_host
          port: 6379
        loki:
          base_url_ref: secret://sanjiu/guanlan/loki_url
          tenant: sanjiu-guanlan
        workshops:
          GL001:
            table_prefix: GL001_EBR_
            redis_key_prefix: "GL001:"
            loki_label: { workshop: GL001 }
          GL002:
            table_prefix: GL002_EBR_
            redis_key_prefix: "GL002:"
            loki_label: { workshop: GL002 }
  mmk:
    bases:
      main:
        engine: sqlserver
        database: { ... }
        redis: { ... }
        loki: { ... }
        # 无 workshops -> degenerate
```

- 密钥用 `*_ref` 引用，真实值从环境变量/secret source 解析，topology 文件不含明文。
- `TopologyRegistry` 加载后是不可变内存模型；后续 DB 版本实现同一 `TopologyRegistry` 接口即可替换。

### 4. 多方言只读 SQL 安全（重点，最易踩坑）

这是本 change 风险最高的部分。分层设计：

```text
raw sql
  -> 归一化: 去注释(/* */、--)、去多余空白、统一大小写用于分析(保留原文用于执行)
  -> 单语句校验: 分号切分后必须只有 1 条有效语句
  -> 只读校验: 首关键字 ∈ {SELECT, WITH}; 禁止 token ∈ {INSERT,UPDATE,DELETE,DROP,ALTER,
     TRUNCATE,CREATE,GRANT,REVOKE,MERGE,CALL,EXEC/EXECUTE,COPY,INTO(SELECT..INTO)}
  -> 表名提取: 解析 FROM/JOIN/WITH 引用的表标识符
  -> 车间前缀校验: 每个表名必须以 workshop.table_prefix 开头(去 schema/引号后比较)
  -> 方言处理: 按 engine 施加行数限制与标识符规则
  -> 执行(参数/只读连接) -> 截断 -> summary
```

**4.1 只靠字符串匹配不够，必须做表名提取。**  
用户/模型可能写 `select * from order_header`（缺前缀）、`GL002_EBR_order`（跨车间）、`db.other_table`。必须解析出真实表标识符再比对前缀，不能 `sql.contains("GL001_EBR_")`（会被 `where col='GL001_EBR_x'` 骗过）。

实现选型：
- 首选轻量 SQL 解析器（如 `sqlglot`，支持多方言 AST + 表提取），用它做**分析**，执行仍用原始 SQL（或 sqlglot 归一化后的安全重写）。
- `sqlglot` 还能帮助按方言加 LIMIT（`limit`/`top`/`fetch`）与做方言校验。
- 备选：正则+词法（脆弱，不推荐作为唯一手段）。

**4.2 方言差异矩阵（分页/引用/只读陷阱）：**

| 关注点 | MySQL | SQL Server | Oracle |
|--------|-------|-----------|--------|
| 分页/限行 | `LIMIT n` | `TOP n` 或 `OFFSET..FETCH` | `FETCH FIRST n ROWS ONLY` 或 `ROWNUM<=n` |
| 标识符引用 | `` `id` `` | `[id]` | `"ID"`（默认大写敏感） |
| schema/表 | `db.table` | `schema.table` | `owner.table` |
| 注释 | `-- ` `/* */` `#` | `-- ` `/* */` | `-- ` `/* */` |
| 只读陷阱 | `SELECT ... INTO OUTFILE` | `SELECT ... INTO t` 建表 | `SELECT ... FOR UPDATE`、PL/SQL 块 |

要点：
- **禁止 `SELECT ... INTO`**（MySQL OUTFILE / SQL Server 建新表）——按方言识别 INTO 子句。
- **禁止 `FOR UPDATE`**（Oracle/MySQL 会加锁，非纯只读）。
- **禁止 PL/SQL 匿名块 / `BEGIN...END` / `DECLARE`**（Oracle、SQL Server 批处理）。
- **Oracle 大小写**：`GL001_EBR_order` 未加引号时会被折叠为大写 `GL001_EBR_ORDER`，前缀比较要大小写不敏感或按方言折叠。
- **限行注入**：不要盲目字符串拼 `LIMIT`；用 AST 判断是否已有限制，没有才按方言加。

**4.3 表前缀 = domain 硬规则，且大小写/引号规范化后比较：**

```text
extract_tables(sql, dialect) -> [TableRef(schema?, name)]
for t in tables:
    normalized = strip_quotes(t.name)         # 去 `` [] ""
    normalized = fold_case(normalized, dialect) # Oracle 折叠大写
    assert normalized.startswith(fold_case(prefix, dialect))
```

跨车间（`GL002_EBR_*` 出现在 GL001 请求）和无前缀都拒绝。degenerate base（mmk 无 workshop）跳过前缀校验，但仍只读 + 限行。

**4.4 执行安全：**
- 只读连接/账号（DB 侧只授予 SELECT 权限，作为纵深防御，不依赖解析器唯一防线）。
- 语句级 timeout；结果行数与序列化字节双重上限；超限截断并标记 `truncated`。
- 参数化不适用（Agent 传的是整条 SQL），因此**解析+只读账号+超时+限行**是四道防线。

替代方案：只用 DB 只读账号、不做 SQL 解析。否决——无法阻止跨车间读取（只读账号仍能读 GL002 表），拿不到车间隔离。

### 5. Redis / Loki 基地级 + 车间命名约束

- Redis：基地级连接；workshop 决定 key 前缀（`GL001:`）。`GET` 校验 key 以前缀开头；`SCAN` pattern 必须落在前缀内且有 bound，禁止 `*`。只读命令白名单（get/scan）。
- Loki：基地级 upstream（含 tenant）；workshop 注入 label（`workshop="GL001"`）叠加现有 selector/时间/行数上限。复用现有 `LokiGateway`，改为按 base 实例化。
- degenerate base：无 workshop 时不加前缀/label，仍保留 bound。

### 6. 平台访问控制（第二层）

```text
Agent 侧 (已存在): user 能调 query_database 吗? (tool + project)
Platform 侧 (新增): user 能访问 sanjiu/guanlan/GL001 吗? (env/base/workshop scope)
```

- 从请求头解析 caller（`X-Agent-User-Id`），可选平台 token。
- `AccessScope` 先从 YAML/seed 配置（user -> 可访问 env/base/workshop）。
- allow/deny 审计（脱敏），deny = 非 retryable。
- `permission_policy` 表 `resource_type` 预留扩展：`environment/base/workshop`。

### 7. 依赖与驱动

- MySQL：`PyMySQL` 或 `mysqlclient`。
- SQL Server：`pyodbc`（需系统 ODBC driver）或 `pymssql`。
- Oracle：`oracledb`（thin mode，免 Instant Client，优先）。
- `sqlglot` 做多方言 SQL 分析。
- 注意容器内 SQL Server ODBC / Oracle 依赖体积，Dockerfile 需评估（见 Risk）。

## Risks / Trade-offs

- [Risk] SQL 解析绕过（模型构造畸形 SQL 逃过前缀检查）→ 解析器 + 只读 DB 账号 + 语句 timeout + 限行四道防线；解析失败一律拒绝（fail closed）。
- [Risk] Oracle 大小写/引号导致前缀误判 → 规范化（去引号 + 方言折叠）后比较；加针对性测试。
- [Risk] `sqlglot` 对某些方言/语法解析不全 → 解析失败即拒绝而非放行；保留 forbidden-token 兜底校验。
- [Risk] SQL Server(pyodbc)/Oracle 驱动在容器内依赖重 → 优先 thin/纯 Python 驱动（`oracledb` thin、`pymssql`）；必要时分镜像。
- [Risk] 密钥管理 → topology 只存 `*_ref`，明文从环境/secret 源解析；错误信息脱敏。
- [Risk] 只读账号仍能跨车间读 → 车间隔离必须靠解析层，不能只靠 DB 权限。
- [Risk] 工具契约变更影响 Agent/Claude schema → 分步：先加可选寻址字段并兼容旧 `datasource`，再逐步切换。
- [Risk] Compose 启动入口迁移 → 若 rename 模块，保留 `app.local_internal_api_platform:create_app` re-export，避免改 Compose；或同一 change 内同步更新。
- [Trade-off] 本期 YAML 配置、无热更新 → 拓扑变更需重启；可接受，DB registry 留待后续。

## Migration Plan

1. 新增 `internal_api_platform` 分层骨架 + 兼容入口（re-export 旧 create_app）。
2. 拓扑 domain 模型 + YAML 加载 + TopologyRegistry + resolve 服务（dry-run 可返回将连哪个资源）。
3. 多方言 SQL 安全（readonly + 表提取 + 前缀 + 方言限行），先只接 MySQL 打通端到端。
4. Redis/Loki 基地级网关 + 车间命名约束（Loki 复用现有实现按 base 拆）。
5. 平台访问控制 + 审计。
6. 工具契约升级（结构化寻址）：Agent 侧 client/tool schema 同步，保留旧字段兼容。
7. 接入 SQL Server、Oracle 方言与驱动，补方言测试矩阵。
8. mmk degenerate 拓扑验证。
9. Compose 样例（三九观澜 + GL001/GL002；mmk）与文档、端到端验证。

Rollback：保留 `FEATURE_REAL_INTERNAL_TOOLS`/fake client 与旧扁平入口；新平台异常时回退到 mock/fake，Agent 闭环不受影响；无破坏性数据迁移。

## Open Questions

- `environment` 与现有 `project_code` 的映射关系：是 1:1（project=environment）还是 project 更细？
- Redis 车间 key 前缀是否稳定统一为 `GL001:`，还是各基地命名不同（需可配置）？
- Loki 车间 label 名统一为 `workshop` 还是各环境不同？
- SQL Server/Oracle 在容器内是否接受 `pymssql`/`oracledb thin`，还是必须官方 ODBC/Instant Client？
- 只读 DB 账号是否可由 DBA 保证（作为纵深防御的前提）？
- AccessScope 初期粒度：到 workshop 还是先到 base？
