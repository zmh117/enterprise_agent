## ADDED Requirements

### Requirement: SchemaInspectorFactory 必须按数据库引擎选择 inspector
系统 SHALL 提供统一的 `SchemaInspectorFactory`，根据 resolved resource binding 的数据库引擎返回 MySQL、Oracle 或 SQL Server schema inspector。应用服务 MUST 依赖 factory 契约，而不是自行分支或维护引擎 reader 字典。

#### Scenario: 为 Oracle 选择 inspector
- **WHEN** schema directory 请求解析到 engine 为 `oracle` 的 database binding
- **THEN** factory 返回 Oracle schema inspector，且不得回退到 MySQL、SQL Server 或 unsupported 实现

#### Scenario: 不支持的引擎被安全拒绝
- **WHEN** factory 收到未注册的数据库引擎
- **THEN** 系统返回明确的非重试配置错误或 limitation，不尝试使用其它方言

### Requirement: Oracle inspector 必须兼容 Oracle 11g
Oracle schema inspector SHALL 从固定的 Oracle 系统目录视图读取普通表和字段元数据，并 MUST 使用 Oracle 11g 可执行的限界语法。它 MUST NOT 依赖 `FETCH FIRST` 或 `OFFSET ... FETCH`。

#### Scenario: 预览 Oracle 11g schema
- **WHEN** 已授权用户请求 Oracle 11g binding 的 schema directory
- **THEN** inspector 使用 `ALL_TABLES`、`ALL_TAB_COLUMNS` 和 `ROWNUM` 兼容查询返回表名、字段名、数据类型和可空性

#### Scenario: Oracle owner 被限制
- **WHEN** database binding 配置了 schema/owner
- **THEN** inspector 只返回该 owner 下且符合 workshop 表前缀和搜索条件的普通表

### Requirement: SQL Server inspector 必须提供真实 schema 预览
SQL Server schema inspector SHALL 从 SQL Server 系统目录读取目标 database/schema 下的普通表和字段元数据，并返回与其它方言一致的 `SchemaDirectory`。

#### Scenario: 预览 SQL Server schema
- **WHEN** 已授权用户请求 engine 为 `sqlserver` 的 schema directory
- **THEN** inspector 返回目标 schema 下普通表的表名、字段名、数据类型和可空性

#### Scenario: SQL Server 默认使用 dbo
- **WHEN** SQL Server database binding 未配置 schema
- **THEN** inspector 将 `dbo` 作为默认 schema，且不返回其它 schema 的表

### Requirement: Schema 预览必须只读、有界且不泄露连接信息
所有 schema inspector MUST 只执行平台定义的系统目录只读查询，MUST 应用表数、每表字段数、workshop 表前缀和搜索条件限制，并 MUST 对响应和错误进行脱敏。schema 预览 MUST NOT 读取业务表样例行。

#### Scenario: 大型 schema 被截断
- **WHEN** 匹配的表或字段数量超过平台配置上限
- **THEN** inspector 仅返回允许范围内的元数据并标记 `truncated=true` 或等价限制信息

#### Scenario: 响应不包含连接凭据
- **WHEN** Oracle、SQL Server 或 MySQL schema inspector 返回成功或失败结果
- **THEN** 响应和审计摘要不包含 host、port、username、password、DSN、connect descriptor 或原始数据库错误

#### Scenario: 不读取业务数据
- **WHEN** 用户请求 schema 预览
- **THEN** inspector 只查询系统目录元数据，不执行针对业务表的样例数据查询
