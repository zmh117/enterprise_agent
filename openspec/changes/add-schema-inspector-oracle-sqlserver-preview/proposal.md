## Why

Internal API Platform 当前只有 MySQL 的真实 schema directory reader，Oracle 和 SQL Server 即使能够执行只读查询，仍会返回“schema directory 未实现”。这会迫使 Agent 猜测表名和字段名，既降低诊断成功率，也削弱现有的只读表字段校验。

## What Changes

- 新增统一的 `SchemaInspectorFactory`，根据解析后的数据库引擎创建 MySQL、Oracle 或 SQL Server schema inspector，替代应用层手工维护 reader 映射。
- 保留现有 MySQL schema 预览行为，并将其适配到统一 inspector 契约。
- 实现 Oracle schema 预览，读取当前允许 schema/owner 下的表、字段、数据类型和可空性；元数据 SQL 兼容 Oracle 11g。
- 实现 SQL Server schema 预览，读取目标 database/schema 下的表、字段、数据类型和可空性。
- 继续通过现有 `/tools/schema/directory` 暴露有界、只读、脱敏的元数据摘要，不读取业务样例行，不返回数据库连接信息。
- 所有 inspector 复用 topology 解析、访问授权、workshop 表前缀、表数上限和字段数上限；不支持的引擎返回明确的安全限制说明。

## Capabilities

### New Capabilities

- `multi-dialect-schema-inspection`: 定义 `SchemaInspectorFactory`、MySQL/Oracle/SQL Server inspector 选择、Oracle 11g 兼容元数据查询和有界 schema 预览契约。

### Modified Capabilities

- `readonly-tool-platform`: schema directory 工具对已配置的 MySQL、Oracle、SQL Server 都提供真实只读元数据预览，并保持授权、前缀隔离、大小限制和脱敏要求。

## Impact

- **代码**：`backend/app/modules/internal_api_platform/infrastructure/db/schema_directory.py`、Internal API Platform 组装逻辑、`PlatformService` 的 schema inspector 获取方式。
- **API**：保留 `/tools/schema/directory` 路径和请求体；Oracle/SQL Server 从“unsupported/empty”变为返回真实元数据。
- **数据库驱动**：复用现有 `pymysql`、`pymssql`、`oracledb` 连接能力，不新增写入权限。
- **安全**：只查询系统目录视图，不读取业务表数据；响应不包含 host、port、用户名、密码、DSN 或原始数据库错误。
- **测试**：增加工厂路由、Oracle 11g 元数据 SQL、SQL Server 元数据映射、前缀/搜索/限量和安全错误测试；真实数据库集成测试保持环境变量门控。
