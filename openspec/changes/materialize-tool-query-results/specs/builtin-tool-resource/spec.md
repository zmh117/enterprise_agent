## MODIFIED Requirements

### Requirement: 授权资源目录必须与实际工具授权一致
`list_available_tool_resources` SHALL 分页返回当前 RUNNING Job、当前用户、业务应用、角色访问、Application Tool 子集与精确 Job Snapshot 共同允许的 Database/Redis/Loki 当前 Published Resource 地址。目录自身必须被冻结授权；业务应用内必须在同一条角色应用访问记录中同时满足数据 Tool 与 scope，不得跨角色拼接。仅返回安全地址、可用工具、resolution_status 和白名单数值 effective_limits，不返回 host、port、username、Secret reference 或 scope 内部条件。限制 SHALL 与执行一致，不解析凭据且不得通过上限发现扩大授权。

#### Scenario: 当前应用内发现资源
- **WHEN** Job 冻结目录及相应数据 Tool，且同一访问记录同时允许 Tool 与目标
- **THEN** 目录返回对应非敏感资源地址、有效查询限制及 AVAILABLE 或 AMBIGUOUS 状态

#### Scenario: 不同角色权限不可拼接
- **WHEN** 角色 A 只有 Tool，角色 B 只有目标 scope
- **THEN** 目录不把两者合成为可见资源

#### Scenario: 直接 Agent Job
- **WHEN** 直接 Job 冻结目录和数据 Tool 且当前用户仍具备既有 Tool/项目 use grant
- **THEN** 目录沿用直接调用的权限边界，不创造额外资源映射或数据授权

### Requirement: 数据库执行必须限制表范围数量时间和响应容量
Database Tool MUST 使用实际 Resource 的数据库/schema 和适用的 Workshop 表前缀，拒绝结构目录外的表。查询默认 100 行、显式最多 10000 行，超限 MUST 拒绝而不静默夹取；执行超时最多 30 秒并与更小平台限制取交集。结果受独立于模型摘要长度的有界序列化容量限制并明确 truncated，不提供通用 cursor。空目录 MUST 返回 `mcp_schema_directory_empty`；字段或语法错误返回可停止的安全错误，不能引导无界猜表、猜字段。

#### Scenario: Workshop 跨表前缀
- **WHEN** Workshop 查询引用其他 Workshop 或缺少要求前缀的表
- **THEN** 请求被只读范围策略拒绝

#### Scenario: 达到结果上限
- **WHEN** 查询达到行数或响应字节上限
- **THEN** 只返回有界结果和截断事实，不提供通用 offset cursor

#### Scenario: 结构目录为空
- **WHEN** 资源没有可用的受限表目录
- **THEN** 系统拒绝执行 SQL，Agent 停止并报告证据不足

#### Scenario: 请求一万行
- **WHEN** 合法只读查询显式请求 10000 行且未超过其他预算
- **THEN** 执行上限为 10000 而非 100；请求 10001 在 Provider I/O 前被拒绝

### Requirement: Loki 单次行数采用平台和资源较小值
平台 Loki 单次行数默认上限 SHALL 为 10000，Web 新建资源默认 max_lines=1000，管理 API/Web 对新建编辑统一限制 1–10000。调用以平台限制与已发布资源 max_lines 的较小值校验，省略 limit 使用 100；超限请求不得自动夹取或分页。该值不是 Job 累计行数预算。

#### Scenario: 请求超过有效上限
- **WHEN** 平台 10000、资源 1000，Agent 请求 1001 条
- **THEN** Provider I/O 前拒绝且说明 1000 为有效上限；资源发布为 10000 后允许合法的 10000 条请求

#### Scenario: 多次合法查询
- **WHEN** 同一 Job 多次调用各自均未超过有效上限
- **THEN** 不因累计行数超过 10000 而拒绝，原工具次数、时间与容量限制仍生效

#### Scenario: 已有显式配置
- **WHEN** 已存在显式平台限制或已发布资源配置
- **THEN** 默认值不改写它们，运行继续取较小值；资源重新编辑验证时适用当前输入范围

## ADDED Requirements

### Requirement: Loki 响应字节保护由代码统一管理
Loki 资源表单与 Provider 配置合同 MUST 不再提供 max_response_bytes 配置，查询、标签发现及 selector 技术验证 MUST 统一使用代码级 8 MiB 上游响应限制。旧草稿或已发布版本的该字段 SHALL 兼容忽略，不修改不可变历史版本；新保存的草稿 MUST 不保留该字段。其他未知配置仍拒绝，时间、行数、授权和超时规则不变。

#### Scenario: 编辑带旧字节设置的资源
- **WHEN** 管理员打开并保存带 max_response_bytes 的旧 Loki 草稿
- **THEN** 界面不显示该输入项，保存不再保留该字段且不因该旧字段报错

#### Scenario: 使用旧发布版本
- **WHEN** 旧 Loki 发布版本仍保存自定义 max_response_bytes
- **THEN** 不改写发布版本，运行时忽略该值并使用统一代码级限制，超限安全失败

### Requirement: Loki 时间配置与错误必须展示有效边界
资源及平台最大查询分钟 MUST 支持配置 1–43200，默认 60、已有值不变，实际按两者较小值执行。四个 Loki 工具超限 MUST 返回稳定安全中文错误及具体有效上限。

#### Scenario: 平台仍为六十分钟
- **WHEN** 资源配置 43200、平台配置 60
- **THEN** 目录暴露有效 60 分钟且大于 60 的请求被拒绝，不声称可查询 30 天

### Requirement: Loki 正文不可按摘要字符预算丢弃
query_loki 与 diagnose_loki_probe MUST 保留本次有界 Provider 返回的每条脱敏日志，不再按 4000 字符省略 highlights。实际返回条数触及 limit MUST 标注查询可能未穷尽，不把 truncated=false 当作查全的替代。Provider 响应字节超限 MUST 失败；结果文件完整保存与查询覆盖完整性 MUST 分别表达。

#### Scenario: 单行超过四千字符
- **WHEN** 单行脱敏后超过 4000 字符但在字节及沙盒容量范围内
- **THEN** 该行完整保留在结果文件，不返回空 highlights 冒充正文

#### Scenario: 短日志顶满行数
- **WHEN** 返回 50 条短日志且 limit=50
- **THEN** 标记 line_limit_reached，不宣称已经查全
