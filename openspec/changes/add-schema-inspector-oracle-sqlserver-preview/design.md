## Context

Internal API Platform 已有统一的 `SchemaDirectoryReader` 协议和 `/tools/schema/directory` 工具，但默认组装仍通过 `default_schema_readers()` 手工创建字典：

- MySQL 使用真实 `MySqlSchemaDirectoryReader`。
- Oracle 和 SQL Server 使用 `UnsupportedSchemaDirectoryReader`。
- `PlatformService` 直接持有 `dict[DatabaseEngine, SchemaDirectoryReader]`，引擎选择和 inspector 生命周期散落在应用组装层。

数据库查询执行器已经支持 MySQL、SQL Server 和 Oracle；Oracle 路径也已经具备 thin/thick/auto、SID/service name、完整 descriptor 和 legacy `ROWNUM` 查询限界。schema 预览必须复用这些连接语义，同时继续保持只读、授权、workshop 前缀和响应大小边界。

## Goals / Non-Goals

**Goals:**

- 引入单一 `SchemaInspectorFactory`，集中管理数据库引擎到 inspector 的映射和不支持引擎的错误语义。
- 保留 MySQL 现有能力，并实现 Oracle、SQL Server 的表和字段元数据预览。
- Oracle 元数据查询兼容 Oracle 11g，不使用 `FETCH FIRST` 或 `OFFSET ... FETCH`。
- 继续通过现有 `SchemaDirectory` 和 `/tools/schema/directory` 返回有界、脱敏结果。
- 让数据库查询前的 schema 校验对 Oracle、SQL Server 与 MySQL 一致生效。

**Non-Goals:**

- 不读取或预览业务表样例数据。
- 不把 schema 元数据持久化或导入平台 PostgreSQL。
- 不生成或修改 ER 图。
- 不改变 `/tools/schema/directory` 请求契约。
- 不新增数据库写权限，不放宽 workshop 表前缀和访问授权。
- 不处理 view、materialized view、存储过程、索引、触发器或外键关系；第一版仅覆盖普通表和字段。

## Decisions

### 1. 使用 `SchemaInspectorFactory` 替代应用层 reader 字典

新增 `SchemaInspector` 协议，方法签名保持现有 `SchemaDirectoryReader.read(...)` 的语义；`SchemaInspectorFactory` 接收 inspector 注册表并提供 `for_engine(engine)`。

默认注册：

| Engine | Inspector |
|---|---|
| `mysql` | `MySqlSchemaInspector` |
| `sqlserver` | `SqlServerSchemaInspector` |
| `oracle` | `OracleSchemaInspector` |

`PlatformService` 依赖 factory 接口，不再自己从字典选 reader。测试可以注入只注册 fake inspector 的 factory，保持领域服务与具体驱动解耦。

不支持的引擎由 factory 返回 `UnsupportedSchemaInspector` 或抛出统一的安全配置错误；不得静默选择其它方言。

**替代方案：继续扩展 `default_schema_readers()` 字典。** 否决，因为每增加一个引擎都需要修改组装和应用服务，无法形成明确的创建边界，也不利于后续 Web 平台做连接测试和 schema 预览。

### 2. 保留 `SchemaDirectory` 作为公共输出模型

inspector 仍返回：

- table name
- column name
- data type
- nullable
- truncated
- limitation

不在本变更增加 vendor-specific 字段，避免 Agent prompt 和 HTTP 契约随数据库方言分叉。数据库原始类型先以安全字符串保留，后续如需统一类型映射另开 change。

现有 `SchemaDirectoryReader` 可在迁移期作为兼容别名或被 `SchemaInspector` 替代；外部 HTTP 契约不受影响。

### 3. Oracle inspector 使用 11g 兼容的两阶段元数据查询

Oracle inspector 复用现有 Oracle client mode、Instant Client 初始化和 DSN 构造规则。

owner 解析规则：

1. 若 `DatabaseConnection.schema` 非空，使用该值并规范化为 Oracle owner。
2. 否则使用当前连接用户作为 owner。
3. owner、表前缀和搜索词全部使用 bind 参数；对象名仅在经过严格标识符校验后用于必要的 SQL 片段。

元数据来源：

- 表：`ALL_TABLES`
- 字段：`ALL_TAB_COLUMNS`

表列表先按 owner、workshop 前缀和搜索词过滤、排序，再通过嵌套查询与 `ROWNUM <= :limit` 限界；不得使用 Oracle 12c 才支持的 `FETCH FIRST`。第二阶段只查询第一阶段选中的表的字段，并按 `COLUMN_ID` 排序，在应用层执行每表 `column_limit` 截断。

选择两阶段查询是为了让 `table_limit` 限制表数量，而不是错误地按字段行数截断，同时避免扫描并返回整个 owner 的字段目录。

### 4. SQL Server inspector 使用 `sys` catalog

SQL Server inspector 复用现有 `pymssql` 连接字段和 timeout，元数据来自：

- `sys.tables`
- `sys.schemas`
- `sys.columns`
- `sys.types`

schema 解析规则：

1. 若 `DatabaseConnection.schema` 非空，使用该 schema。
2. 否则默认 `dbo`。

表列表使用受控的 `TOP (n)` 限界；`n` 来自已校验的内部整数，不接受用户 SQL。schema、前缀和搜索词使用参数绑定。字段按表名和 `column_id` 排序，并在应用层执行每表字段上限。

选择 `sys` catalog 而不是只依赖 `INFORMATION_SCHEMA`，是为了稳定获得字段顺序和 SQL Server 类型信息。

### 5. 连接、错误和资源释放保持一致

每个 inspector 必须：

- 使用 resolved `ResourceBinding`，不接受调用方传入 host、用户或密码。
- 设置短连接/查询超时。
- 在 `finally` 中关闭 cursor 和 connection。
- 将缺失驱动、连接超时和上游不可用转换为安全的 platform error。
- 将无权限访问系统目录、owner/schema 不存在等情况转换为明确 limitation 或安全错误，不返回原始 DSN、host、用户名和数据库异常文本。

schema 预览只执行固定的系统目录 `SELECT`；不复用 Agent 提供的 SQL，也不允许拼接任意 SQL。

### 6. 前缀、搜索和截断由统一边界保证

`PlatformService` 继续在调用 inspector 前完成 topology、权限和 workshop 解析，并传入：

- `table_prefix`
- `query`
- `table_limit`
- `column_limit`

inspector 必须在数据库侧尽可能应用过滤，并在应用侧再次执行防御性过滤和截断。若实际表数超过 `table_limit`，返回 `truncated=true`；不得通过增大请求参数绕过平台最大值。

## Risks / Trade-offs

- **[系统目录权限不足]** Oracle 用户可能无法读取目标 owner 的 `ALL_*` 视图，SQL Server 用户可能缺少 metadata visibility → 使用最小只读账号并返回明确安全错误；集成文档列出所需最小元数据权限。
- **[大小写语义差异]** Oracle 默认大写对象名，SQL Server collation 可能大小写敏感 → inspector 做方言内规范化，但返回数据库真实对象名。
- **[大型 schema 性能]** 系统目录可能包含大量表和字段 → 数据库侧先过滤表，再查询选中表字段；严格应用 table/column limit 和 timeout。
- **[连接逻辑重复]** inspector 与 executor 都需要建立连接 → 第一版复用现有 DSN/client helper；若重复继续扩大，再提取独立 connection provider，不在本变更引入过度抽象。
- **[现有测试注入方式变化]** 测试目前注入 reader 字典 → 提供 factory 构造 helper，并在迁移期间保留小范围兼容适配。

## Migration Plan

1. 新增 factory、Oracle inspector 和 SQL Server inspector，保留现有 MySQL 行为。
2. 将默认应用组装改为注入 `SchemaInspectorFactory`。
3. 将 `PlatformService` 的 reader 字典依赖迁移为 factory；同步测试 fixture。
4. 先运行纯单元测试，再通过环境变量门控真实 Oracle 11g / SQL Server 集成 smoke。
5. 回滚时恢复旧 reader 字典组装；HTTP API 和数据模型未变化，不需要数据库迁移。

## Open Questions

- 生产 Oracle 账号是否能读取目标 owner 的 `ALL_TABLES` / `ALL_TAB_COLUMNS`；若只能读取自身对象，是否需要对该基地显式限定为当前用户。
- SQL Server 首版是否需要包含 view；当前范围只包含普通表，若业务需要应在后续 change 明确 view 的只读语义。
