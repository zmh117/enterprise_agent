## 1. Inspector 契约与工厂

- [x] 1.1 在 internal_api_platform 数据库基础设施层定义 `SchemaInspector` 契约，并保持现有 `SchemaDirectory` 输出模型不变。
- [x] 1.2 实现 `SchemaInspectorFactory`，支持按 `DatabaseEngine` 注册和获取 inspector，并为未注册引擎提供安全、明确的 unsupported 行为。
- [x] 1.3 将 `MySqlSchemaDirectoryReader` 适配/重命名为 MySQL schema inspector，保持现有表前缀、搜索、表数和字段数限制。
- [x] 1.4 为 factory 增加单元测试，覆盖 MySQL/Oracle/SQL Server 路由、未注册引擎和禁止错误方言回退。

## 2. PlatformService 与应用组装迁移

- [x] 2.1 将 `PlatformService` 的 `schema_readers` 字典依赖迁移为 `SchemaInspectorFactory` 依赖。
- [x] 2.2 更新 internal-api-platform 默认组装，注册 MySQL、Oracle 和 SQL Server inspector，删除 Oracle/SQL Server 的默认 unsupported reader。
- [x] 2.3 更新现有测试 fixture/fake 注入方式，使单元测试通过 factory 注入 fake inspector。
- [x] 2.4 验证 `/tools/schema/directory` 的路径、请求体和响应结构保持向后兼容。

## 3. Oracle 11g Schema Inspector

- [x] 3.1 实现 `OracleSchemaInspector`，复用现有 Oracle client mode、Instant Client 初始化、SID/service name、connect descriptor 和 DSN helper。
- [x] 3.2 实现 Oracle owner/schema 解析与标识符校验；未配置 schema 时使用当前连接用户，禁止任意 SQL 标识符注入。
- [x] 3.3 使用 `ALL_TABLES`、bind 参数和嵌套 `ROWNUM` 查询实现表列表预览，应用 owner、workshop 表前缀、搜索词和 `table_limit + 1` 截断检测。
- [x] 3.4 使用 `ALL_TAB_COLUMNS` 实现选中表的字段预览，按 `COLUMN_ID` 排序并应用每表 `column_limit`。
- [x] 3.5 增加 Oracle inspector 单元测试，覆盖 11g SQL 不含 `FETCH FIRST/OFFSET`、owner 过滤、大小写、前缀、搜索、截断、nullable 映射和连接关闭。
- [x] 3.6 增加 Oracle 驱动缺失、连接失败、系统目录权限不足时的安全错误测试，确认不泄露 host、用户、密码、DSN 和原始异常。

## 4. SQL Server Schema Inspector

- [x] 4.1 实现 `SqlServerSchemaInspector`，复用现有 `pymssql` 连接字段、database 和 timeout。
- [x] 4.2 使用 `sys.tables`、`sys.schemas` 和受控 `TOP (n)` 实现目标 schema 的表列表预览；未配置 schema 时默认 `dbo`。
- [x] 4.3 使用 `sys.columns`、`sys.types` 实现选中表的字段预览，按 `column_id` 排序并应用每表 `column_limit`。
- [x] 4.4 增加 SQL Server inspector 单元测试，覆盖 schema、前缀、搜索、截断、类型/nullable 映射、默认 `dbo` 和连接关闭。
- [x] 4.5 增加 SQL Server 驱动缺失、连接失败、metadata visibility 不足时的安全错误测试，确认不泄露连接信息。

## 5. 只读边界与回归验证

- [x] 5.1 增加跨方言契约测试，确认所有 inspector 只执行固定系统目录 SELECT，不查询业务表样例行。
- [x] 5.2 增加 API/服务测试，确认 Oracle 和 SQL Server schema directory 返回真实 bounded 元数据，并继续执行权限和 workshop 前缀隔离。
- [x] 5.3 验证 schema directory 可用于 Oracle/SQL Server 查询前表名校验，未知表返回现有结构化停止提示。
- [x] 5.4 更新 internal-api-platform 文档，说明三种引擎的 schema 预览、Oracle 11g 兼容、SQL Server 默认 schema 和最小元数据权限。
- [x] 5.5 增加环境变量门控的 Oracle 11g 与 SQL Server 集成 smoke；未配置真实数据库时保持 skipped，不阻塞本地单测。
- [x] 5.6 运行 `.venv/bin/pytest backend/tests -q`、`.venv/bin/ruff check .` 和 `.venv/bin/mypy backend/app`。
- [x] 5.7 运行 `openspec validate add-schema-inspector-oracle-sqlserver-preview --strict` 和 `openspec validate --specs`。
