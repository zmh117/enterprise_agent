## ADDED Requirements

### Requirement: Workshop Resource Partition Policy 必须版本化发布
系统 SHALL 为每个需要共享物理资源的逻辑 Workshop 管理稳定 Policy Identity、可编辑 Draft、机器验证证据和不可变 Published Revision；修改任何前缀或规则后 MUST 创建新 Draft、重新验证并发布新 revision。

#### Scenario: 发布已验证策略
- **WHEN** 授权管理员发布内容 hash 与当前成功证据一致的 Policy Draft
- **THEN** 系统创建不可变 Published Revision 并记录 workshop、规则、验证摘要、actor 和时间

#### Scenario: 修改已发布策略
- **WHEN** 管理员尝试原地修改 Published Revision 的数据库或 Redis 前缀
- **THEN** 系统拒绝并要求复制为新 Draft

#### Scenario: 策略发布新版本
- **WHEN** Workshop Policy 发布新 revision 但应用未重新发布
- **THEN** 既有 Application Publication 和 Job 继续使用原 revision

### Requirement: 数据库车间策略第一阶段必须恰好包含一个精确表名前缀
需要 Workshop 隔离的数据库 Policy MUST 为该 Workshop 保存恰好一个非空、非通配、非正则的表名前缀；前缀比较 MUST 遵循目标数据库方言的标识符规范化规则。

#### Scenario: 配置 GL001 表前缀
- **WHEN** 管理员为 Workshop `GL001` 保存数据库前缀 `GL001_`
- **THEN** 系统接受该 Draft 并在验证和运行时使用规范化后的精确前缀

#### Scenario: 提交多个或模糊前缀
- **WHEN** Draft 提交前缀列表、正则、空值、`*` 或 `%`
- **THEN** 系统拒绝保存或验证

#### Scenario: 目标没有 Workshop 层级
- **WHEN** Environment 或 Base 是实际叶子目标且没有 Workshop 子节点
- **THEN** 该目标的数据库 Mapping 不要求创建虚拟 Workshop Policy

### Requirement: Schema Directory 必须按冻结的数据库前缀过滤
数据库 Schema Directory MUST 只返回名称满足 Job 冻结 Policy Revision 精确前缀的表及其有界字段摘要；不得暴露其它 Workshop 的表名或连接信息。

#### Scenario: GL001 查询 schema 目录
- **WHEN** Job 目标为 GL001 且冻结前缀为 `GL001_`
- **THEN** Schema Directory 只返回符合方言比较规则的 `GL001_` 表和有界字段摘要

#### Scenario: 同库存在 GL002 表
- **WHEN** 数据库同时包含 `GL001_` 和 `GL002_` 开头的表
- **THEN** GL001 的 Schema Directory 不返回 `GL002_` 表名或字段

### Requirement: 数据库执行前必须验证所有物理表引用
数据库网关 MUST 在连接和执行前解析只读 SQL 中所有物理表引用，并逐一验证其满足冻结的表名前缀；无法可靠解析、动态表名、多语句或任一越界引用 MUST 被拒绝。

#### Scenario: 查询允许的单表
- **WHEN** 只读 SQL 仅引用符合 `GL001_` 前缀的表
- **THEN** 请求可进入既有只读语法、权限、超时和结果边界校验

#### Scenario: Join 跨车间表
- **WHEN** SQL 同时引用 `GL001_ORDER` 与 `GL002_ORDER`
- **THEN** 网关在访问数据库前拒绝整个请求

#### Scenario: SQL 表引用无法静态确定
- **WHEN** SQL 使用平台不支持且无法可靠解析的动态表名或方言结构
- **THEN** 网关失败关闭，不以字符串包含判断放行

### Requirement: Redis 车间策略必须保存一个或多个精确完整 namespace 前缀
共享 Redis 的 Workshop Policy SHALL 保存一个或多个非空的精确完整 key namespace 前缀；每个前缀 MUST 包含由部署契约定义的固定 namespace 与 Workshop code 边界，例如 `cr999.crmes.CRMES_TEST_GL#GL001@$`，并 MUST NOT 使用正则或通配符。

#### Scenario: 配置一个完整前缀
- **WHEN** 管理员为 GL001 保存 `cr999.crmes.CRMES_TEST_GL#GL001@$`
- **THEN** 系统接受其作为一个精确 namespace 前缀

#### Scenario: 一个 Workshop 有多个合法 namespace
- **WHEN** 同一 Workshop 的业务数据确实分布在两个固定 namespace
- **THEN** Policy 可以保存两个分别验证的精确前缀，而不是一个宽泛共同前缀

#### Scenario: 提交模糊 namespace
- **WHEN** 管理员提交 `*GL001*`、正则或只包含 `GL001` 的片段
- **THEN** 系统拒绝该 Policy Draft

### Requirement: Redis GET 和 SCAN 必须强制执行冻结前缀
`query_redis_get` 的完整 key MUST 以冻结 Policy Revision 中某个完整 namespace 前缀开头；`query_redis_scan` 的 pattern MUST 从某个完整前缀开始且通配符只能出现在该前缀之后。系统 MUST 继续限制命令、迭代次数、返回数量、字节和脱敏。

#### Scenario: GET 命中允许前缀
- **WHEN** GL001 Job 请求 key `cr999.crmes.CRMES_TEST_GL#GL001@$EBRDataText.809901890274822.Sheet4.rows`
- **THEN** 请求可进入只读 GET 执行和结果边界校验

#### Scenario: GET 跨 Workshop
- **WHEN** GL001 Job 请求以 `cr999.crmes.CRMES_TEST_CZ#CZ002@$` 开头的 key
- **THEN** 平台在访问 Redis 前拒绝请求

#### Scenario: 有界 SCAN pattern
- **WHEN** GL001 Job 使用 `cr999.crmes.CRMES_TEST_GL#GL001@$[BATCH_RECORD]:*` pattern
- **THEN** 平台在既有 SCAN 次数与返回上限内执行

#### Scenario: 前缀前出现通配符
- **WHEN** SCAN pattern 为 `*GL001*` 或通配符出现在完整 namespace 前缀内
- **THEN** 平台拒绝请求且不向 Redis 发送 SCAN

### Requirement: Redis 连接测试与 namespace 验证必须分离
Redis Resource 连接测试 MUST 只验证受治理连接字段、Secret、认证、TLS、database 和 PING，不得枚举 key；Partition Policy 验证 MUST 由系统为每个精确前缀生成有界 `prefix*` SCAN，并只保存匹配数、截断标志、摘要 hash、时间和脱敏错误。

#### Scenario: 测试 Redis 连接
- **WHEN** 管理员点击 Redis Resource Draft 的连接测试
- **THEN** 系统不执行 KEYS 或 SCAN，不返回任何业务 key

#### Scenario: 验证前缀存在数据
- **WHEN** 系统生成的有界 SCAN 找到匹配 key
- **THEN** 验证证据保存匹配数量和摘要，不保存完整 key 列表

#### Scenario: 验证前缀零匹配
- **WHEN** 有界 SCAN 成功但没有匹配 key
- **THEN** Policy 可以带明确 warning 发布，系统不得自动缩短或扩大前缀

### Requirement: 同一 Workshop 的所有 placement 必须共享一个策略语义
对于同一逻辑 Workshop，Application Publication 中 cloud、edge 或无 placement 的同类资源 Mapping MUST 使用同一个 Workshop Partition Policy Revision；系统 MUST NOT 允许为不同 placement 配置不同数据库或 Redis 隔离边界。

#### Scenario: 云边使用同一 Policy
- **WHEN** GL001 同时绑定 cloud 和 edge 数据库 Resource Revision
- **THEN** 两条 Mapping 都引用同一个 GL001 Partition Policy Revision

#### Scenario: 云边策略不一致
- **WHEN** cloud Mapping 引用 GL001 Policy A 而 edge Mapping 引用 GL001 Policy B
- **THEN** Application Publish 拒绝并指出同一逻辑 Workshop 的策略不一致
