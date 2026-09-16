## ADDED Requirements

### Requirement: tool-mcp 必须提供 Job 绑定的授权资源目录
系统 SHALL 由代码 Manifest 注册只读 `list_available_tool_resources` Tool，分页返回当前 RUNNING Job、当前用户、当前业务应用、当前有效角色访问、Application Tool 子集与 Job 精确 Tool Snapshot 共同允许的 Database、Redis、Loki 最新 Published Resource 地址摘要。该 Tool 本身 MUST 被 Agent/Application Publication 和 Job 精确冻结并通过调用授权；系统 MUST 以同一条角色应用访问记录中的 Tool 与 scope 组合判断可见性，不得把不同角色或不同 access 的工具与范围交叉拼接。目录 MUST NOT 返回连接配置、host、port、username、Secret reference、scope binding 内部条件、未授权候选或其它业务应用资源。

#### Scenario: 当前用户发现业务应用内资源
- **WHEN** RUNNING Job 冻结了 `list_available_tool_resources` 和 Database、Redis 或 Loki 数据工具，且当前用户在该业务应用的一条有效角色访问中同时获得相应 Tool 与资源目标 scope
- **THEN** `tool-mcp` 返回该目标最新 Published Resource Revision 的非敏感地址摘要和当前可用 Tool identifiers
- **AND** 不返回同一平台中未被该用户当前应用访问允许的资源

#### Scenario: 不同角色授权不得交叉拼接
- **WHEN** 用户的角色 A 只允许某数据 Tool 但不允许目标 scope，角色 B 只允许目标 scope 但不允许该 Tool
- **THEN** 资源目录不得把 A 的 Tool 与 B 的 scope 合并为可见资源

#### Scenario: 目录 Tool 未被 Job 冻结
- **WHEN** Runtime 尝试为未冻结 `list_available_tool_resources` 或 schema hash 不匹配的 Job 调用资源目录
- **THEN** `tool-mcp` 在读取资源候选或连接任何上游前失败关闭

#### Scenario: 相同目标存在多个资源候选
- **WHEN** 当前授权范围内的同一资源类型、environment/base/workshop 与 placement 存在多个最新 Published Resource 候选
- **THEN** 目录以 `AMBIGUOUS` 标记这些候选且不得选择默认资源
- **AND** 后续资源 Tool Call 仍按既有唯一解析规则失败关闭

#### Scenario: 直接 Agent Job 查询资源目录
- **WHEN** 不属于业务应用的直接 Job 冻结了目录 Tool 和某资源数据 Tool，且当前用户仍具有这些 Tool 与项目的既有 use grant
- **THEN** 目录只返回该资源类型的 Published Resource 非敏感地址
- **AND** 不引入新的数据范围、资源映射或比既有精确目标调用更宽的执行权限

### Requirement: Tool MCP 目录分页必须使用授权绑定的不透明游标
`list_available_tool_resources` SHALL 默认且最多每页返回 50 项，并按稳定资源地址键执行 keyset 分页。cursor MUST 绑定当前 Job MCP Tool Snapshot、authorization hash、Tool identifier、过滤条件和本次授权候选摘要；每一页 MUST 重新校验 RUNNING Job、精确 schema hash、当前授权和当前 Published Resource 候选。响应 SHALL 返回 `next_cursor`、`has_more`、`observed_at` 和有界 `truncated` 语义，cursor 不得包含可由模型修改后提升权限的可信身份或范围事实。

#### Scenario: 授权资源超过单页上限
- **WHEN** 当前用户有 51 个满足同一目录过滤条件的授权资源
- **THEN** 第一页只返回 50 个并提供非空 `next_cursor` 与 `has_more=true`
- **AND** 使用该 cursor 的下一页返回余下资源且不重复第一页条目

#### Scenario: cursor 被跨 Job 或跨过滤条件复用
- **WHEN** Agent 把资源目录 cursor 用于另一个 Job、Tool、resource_kind 或 query
- **THEN** `tool-mcp` 返回稳定分页游标错误且不返回资源目录内容

#### Scenario: 翻页期间授权或资源目录变化
- **WHEN** cursor 签发后用户授权、Job authorization hash 或当前 Published Resource 候选摘要发生变化
- **THEN** `tool-mcp` 返回稳定 cursor stale 错误并要求从第一页重新查询
- **AND** 不使用旧授权或旧 Resource Revision 继续分页

### Requirement: Schema 目录必须支持按表安全续查
`get_schema_directory` SHALL 在既有当前授权目标、唯一 Published Database Resource Revision、表范围、字段范围和响应上限内支持不透明 cursor。每页默认且最多返回 50 张按数据库方言稳定排序的完整表摘要；cursor MUST 绑定 Job、Tool、目标、placement、query 和实际 Resource Revision。Schema inspector MUST 使用有界 keyset 表名查询读取下一页，不得为了返回一页而把全部 schema 字段无界加载到内存。单表字段上限与是否存在下一表 MUST 分开表达。

#### Scenario: Schema 目录超过 50 张表
- **WHEN** 当前授权数据库中有 51 张符合 query 和资源表范围的表
- **THEN** 第一页返回 50 张表、非空 `next_cursor` 和 `has_more=true`
- **AND** 下一页返回第 51 张表且使用同一 Database Resource Revision

#### Scenario: Oracle 第一页没有游标
- **WHEN** Oracle Schema 目录首次查询没有 after_table
- **THEN** 查询必须允许空下界而不执行与 NULL 的大小比较，返回符合范围的第一批表

#### Scenario: Schema cursor 用于不同目标
- **WHEN** Agent 把 environment、base、workshop、placement 或 query 与签发 cursor 时的值改变
- **THEN** `tool-mcp` 在读取 schema 前拒绝 cursor

#### Scenario: Schema 翻页期间资源版本改变
- **WHEN** 第一页之后该目标解析到不同的当前 Published Database Resource Revision
- **THEN** 第二页返回稳定 cursor stale 错误并要求重新从第一页读取
- **AND** 不回退使用旧 Revision

#### Scenario: 单表字段达到独立上限
- **WHEN** 本页某张表的字段数超过单表字段上限但已不存在更多表
- **THEN** 响应明确标记字段摘要受限且 `has_more=false`
- **AND** 不生成指向不存在表页的 `next_cursor`

### Requirement: Redis SCAN 必须保留受治理 continuation
`query_redis_scan` SHALL 接受可选不透明 cursor，并把 Redis provider continuation 包装为当前 Job、Tool、目标、pattern、limit 策略和实际 Published Redis Resource Revision 绑定状态。每一页 MUST 重新执行 Tool 与数据范围授权、唯一资源解析、namespace 前缀校验和数量/响应大小限制。系统 MUST NOT 把原始 provider cursor 当作授权事实或允许 cursor 改变 namespace。

#### Scenario: Redis SCAN 返回下一页
- **WHEN** 合法 SCAN 的 provider cursor 非零且仍有后续键
- **THEN** `tool-mcp` 返回本页有界键列表、非空 `next_cursor` 和 `has_more=true`
- **AND** 下一次使用该 cursor 从 provider continuation 继续而不是重新从零开始

#### Scenario: Redis cursor 与 pattern 不匹配
- **WHEN** Agent 使用 cursor 时改变 pattern、目标或 placement
- **THEN** `tool-mcp` 在调用 Redis 前拒绝请求并返回稳定分页游标错误

#### Scenario: Redis 单批次超过页面上限
- **WHEN** Redis 返回的键数超过 limit，包括 provider cursor 已为零的末批
- **THEN** 本页仅返回 limit 项且提供非空 continuation，后续页返回该批剩余键
- **AND** 重读批次期间结果变化必须返回 cursor stale，不得以扫描完成掩盖漏键

#### Scenario: Redis 空批次与 Cluster 节点续查
- **WHEN** Redis 返回空键列表但 provider cursor 非零，或 Cluster 还有未扫描主节点
- **THEN** Tool 返回 has_more=true 并保留正确 continuation
- **AND** Cluster 逐主节点调用 SCAN，cursor 不包含节点连接地址，拓扑变化须拒绝旧 continuation

#### Scenario: Redis 翻页期间资源版本改变
- **WHEN** cursor 绑定的 Redis Resource Revision 不再是该目标唯一解析的当前版本
- **THEN** `tool-mcp` 拒绝 continuation 且不得访问旧 Revision 或新 Revision

### Requirement: Agent 必须先发现授权资源再调用目标工具
系统提示 SHALL 在 `list_available_tool_resources` 已冻结时要求 Agent 对“有哪些可用 Database、Redis、Loki 资源”或缺少唯一目标的问题先调用该目录，并只使用目录返回且 `resolution_status=AVAILABLE` 的精确 environment/base/workshop/placement。目录 Tool 未冻结时，Agent MUST 请求用户提供一个精确目标；不得猜测、枚举环境码、反复调用同一失败参数，或把一个目标的零命中解释为当前用户没有任何资源。

#### Scenario: 用户询问全部可用资源
- **WHEN** 当前 Job 已冻结授权资源目录 Tool，且用户询问其可用数据库、Redis 或 Loki
- **THEN** Agent 调用目录并按 cursor 续查，而不是先猜测 environment

#### Scenario: 用户给出的目标零命中
- **WHEN** 一个精确目标返回 `mcp_resource_not_resolved`
- **THEN** Agent 不得重复相同调用或试探其它环境码
- **AND** 若目录 Tool 可用则重新查询授权目录，否则只报告该精确目标不可用并请求用户补充

#### Scenario: 目录能力未发布
- **WHEN** Job 有资源查询 Tool 但没有冻结 `list_available_tool_resources`，且用户未给出精确目标
- **THEN** Agent 说明需要精确 environment 及适用的 base/workshop/placement
- **AND** 不宣称已检查当前用户的全部资源

### Requirement: 任意数据库结果和 Loki 日志不提供通用分页游标
`query_database` 和 `query_loki` MUST 继续执行既有 SQL 只读、selector、时间、行数、字节数和响应截断限制，不得把 offset、旧查询结果或上游 continuation 自动包装为通用分页能力。需要更多证据时，Agent SHALL 使用已允许字段构造更窄且稳定的 keyset SQL 条件，或缩小 Loki 时间窗；该后续查询仍是新的完整授权 Tool Call。

#### Scenario: 数据库结果达到行数上限
- **WHEN** `query_database` 结果达到当前行数或响应大小上限
- **THEN** Tool 返回有界截断结果且不返回通用 offset cursor

#### Scenario: Loki 结果达到行数上限
- **WHEN** `query_loki` 结果达到当前时间窗、行数或响应大小上限
- **THEN** Tool 返回有界截断结果且不返回可绕过当前查询约束的通用 cursor
