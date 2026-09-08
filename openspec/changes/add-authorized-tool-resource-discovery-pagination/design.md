## Context

当前 `DirectResourceResolver.resolve()` 只接受 Agent 明确提供的 environment/base/workshop/placement，并按资源类型解析唯一最新 Published Resource Revision；这是既有 fail-closed 边界。`DirectResourceResolver.directory()` 虽能枚举 Database、Redis、Loki 的非敏感地址，但没有用户、业务应用、Job Tool Snapshot 或数据范围过滤，仅适合作为内部候选源，不能直接进入模型上下文。

`get_schema_directory` 当前把 `limit=50` 当作表数量上限，返回 `truncated=true` 后没有 continuation；Redis gateway 每次固定从 SCAN cursor 0 开始，丢弃上游返回的 cursor。Agent 上下文只要求在数据库查询前调用 Schema Tool，没有授权资源发现路径，因此目标不明确时容易猜测 environment、重复调用和重复解释失败。

本变更横跨 Manifest、Job 授权、资源解析、数据库 inspector、Redis gateway、MCP 审计和 Agent 指令。现有不可变 Publication、Job 精确 schema hash、调用时当前 Published Revision、只读策略及 Secret 隔离必须保持不变。

## Goals / Non-Goals

**Goals:**

- 让已冻结新目录 Tool 的当前 Job 能发现当前用户实际可调用的 Database、Redis、Loki 资源地址。
- 让资源目录、Schema 表目录和 Redis SCAN 在单页上限后可安全续查。
- 让 Agent 在不知道目标时先发现、再选择、后调用，不猜测环境且不重复相同失败。
- 每一页都重新验证 Job、Tool schema、当前用户/应用授权和当前 Resource Revision。
- 保持响应、上游读取、审计和模型自动翻页均受既有执行预算约束。

**Non-Goals:**

- 不让 `get_schema_directory` 同时承担 Database、Redis、Loki 资源发现职责。
- 不冻结 Resource Revision 到 Job，不恢复 Application Resource Mapping，也不引入资源目录持久化快照。
- 不向模型返回连接地址、用户名、Secret reference、scope binding 内部配置或未授权候选数量。
- 不为任意 SQL 结果或 Loki 日志结果提供通用 offset cursor；调用方继续使用更窄时间窗、受控 keyset 条件和既有结果上限。
- 不改变 Redis GET、数据库只读 SQL、Loki selector 与响应脱敏策略。

## Decisions

### 1. 新增独立的授权资源目录 Tool

新增代码 Manifest Tool `list_available_tool_resources`。输入为可选 `resource_kind`、安全文本过滤 `query`、`limit` 和 `cursor`；每页默认及最多 50 项。输出保持有界，包含：

- `resource_code`
- `resource_kind`
- `environment`、`base`、`workshop`
- `placement`
- `resource_revision_id` 和 revision number
- `resolution_status=AVAILABLE|AMBIGUOUS`
- `usable_tools`（当前 Job 中针对该资源类型且当前用户已获授权的 Tool identifier）
- `next_cursor`、`has_more`、`observed_at`

目录 Tool 自身必须存在于 Agent/Application Publication 和当前 Job 的精确 Tool Snapshot，并通过正常 Tool 调用授权。服务端再从 Job Snapshot 取得当前实际冻结的数据工具集合，只显示至少可由其中一个工具访问的资源。

业务应用 Job 以当前启用用户、当前启用应用、当前有效 Application Tool 子集、当前角色应用访问和 scope 并集计算授权投影。某角色的环境级 scope 可覆盖其下基地/车间，基地级 scope 可覆盖其下车间；不同角色的工具与 scope 不得交叉拼接成并不存在的授权组合。直接 Agent Job 沿用既有语义：只对当前 Job 已冻结且当前用户仍有 `tool:use`/project use grant 的资源工具开放相应种类；由于直接 Job 当前没有业务应用数据范围，目录不会引入比精确目标调用更宽的新权限。

候选仍来自每个启用 Resource Identity 的最新 Published Revision。相同资源类型与目标在同一 placement 下有多个候选时，目录返回 `AMBIGUOUS`，Agent 不得调用该目标，并可向用户报告需要管理员处理冲突；目录不得自行挑选第一候选。

**备选方案：** 让 `get_schema_directory` 在省略 environment 时返回全部资源。该方案会把数据库结构与跨类型资源发现混成一个契约，难以表达 Redis/Loki 且会模糊审计语义，因此不采用。

### 2. 授权投影位于应用服务，不下沉到 Resolver

`DirectResourceResolver` 继续只负责读取当前 Published Revision、返回非敏感候选和唯一解析。新增应用层目录协作者把 Job Snapshot 中的数据工具、当前授权事实和 Resolver 候选做交集，然后才执行过滤、排序和分页。原始 `directory()` 不直接暴露给 MCP 响应。

目录审计保存过滤条件、返回数量、是否还有下一页及返回项的资源 identity/revision 摘要；不保存未授权候选、角色明细、连接配置或 Secret。

**备选方案：** 对每个候选逐个调用现有 `decide()`。结果正确但会产生候选数乘工具数的重复数据库读取，目录越大越慢；改为一次读取当前 Job Tool 和当前用户应用访问事实后在内存中逐条使用同一 scope 匹配语义。

### 3. Tool MCP 使用 Job 绑定的不透明 keyset cursor

统一 cursor envelope 包含版本、用途、过滤哈希、最后排序键，以及目录候选摘要或 Resource Revision 绑定；外层 checksum 使用当前 Job MCP Tool Snapshot hash 与 authorization hash 派生。模型只能回传整个 cursor，不能在参数中声明 revision、授权范围或 offset。

每页调用顺序为：验证 RUNNING Job和精确 Tool schema → 复核当前授权 → 解析当前资源或重建授权目录 → 校验 cursor 绑定 → 读取下一页。以下情况返回稳定 `mcp_pagination_cursor_invalid` 或 `mcp_pagination_cursor_stale`，且不访问越权资源：

- cursor 结构、checksum、用途或过滤哈希不匹配；
- cursor 来自另一个 Job、Tool、目标或查询条件；
- 授权投影、目录候选摘要或当前 Published Resource Revision 已改变；
- Redis cursor 类型不符合当前连接模式。

资源目录按 `(resource_kind, environment, base, workshop, placement, resource_code, resource_revision_id)` keyset 排序。Schema 按数据库引擎的规范化表名和原始表名稳定排序，并以最后一张完整返回的表作为 keyset；每页最多 50 张表，单表字段仍受既有字段上限及响应字节上限约束。Redis wrapper cursor 保存上游 continuation 状态，但每页仍重新解析同一目标并要求同一 Resource Revision、pattern 和 limit 策略。

不新增游标表或通用签名 Secret。Job Snapshot hash 与 authorization hash 不进入 Tool 响应；cursor checksum 只用于完整性与绑定，真正的权限仍由每页实时授权决定。

### 4. Schema inspector 与 Redis gateway 显式返回 continuation

Schema inspector 协议增加 `after_table`，各数据库方言在表名查询阶段使用参数化 keyset 条件并读取 `limit + 1` 张表，再仅查询本页所选表的字段。MySQL 从当前一次读取全部 `information_schema.columns` 改为与 Oracle/SQL Server 一致的“两阶段：有界表名 + 本页字段”策略。`SchemaDirectory` 区分是否仍有后续表与字段被单表上限截断，避免把不可续查的字段截断错误编码为下一页。

Redis gateway 的 `scan()` 接受受控扫描位置并返回下一扫描位置。Tool 层把位置包装到 Job/Revision/查询绑定 cursor 中；仅终止哨兵 `0` 表示 `has_more=false`。standalone 与 cluster 共用有界批次重读位置；Cluster 额外记录主节点序号与拓扑摘要，禁止把节点地址映射放入公开 cursor。非法形状失败关闭。

### 5. Manifest 漂移与 Agent 行为显式升级

新增目录 Tool，并给 `get_schema_directory`、`query_redis_scan` 增加 `cursor` 和最大长度约束，会改变 schema hash。既有 Publication 和运行中 Job 不自动获得能力；管理员必须重新发布 Agent 和业务应用，新 Job 才可使用。运行时仍按精确 schema hash 拒绝旧快照调用新契约。

Agent 指令在目录 Tool 已分配时规定：用户询问可用资源或没有给出唯一目标，先调用目录；自动续页时保持完全相同过滤条件、拒绝重复 cursor，并受 Job 最大 Tool Call 数约束。目录 Tool 未分配时，只能请用户提供一个精确目标，不能猜测、遍历或把一次零命中夸大为整个系统无资源。

## Risks / Trade-offs

### 2026-09-08 正确性修订

Redis COUNT 仅为工作量提示，不是响应数量上限。Gateway 必须保留超出单页的批次位置：continuation 记录原 provider cursor、已返回数量及完整批次摘要，下一页重读同一批次并验证摘要后续取；摘要变化返回 cursor stale，不得静默跳过。摘要包含规范排序后的 keys 和 provider next cursor，不把 key 正文写入 cursor，不新增持久化游标表。只有整个批次已返回才推进 provider cursor；空批次的非零 cursor 仍须继续。

Cluster 按固定排序逐个主节点扫描，调用 redis-py 的单节点 SCAN，分别维护节点序号与 provider cursor；cursor 只包含节点拓扑摘要及序号，不包含 host/port。拓扑变化失败关闭。客户端在每次读取后释放连接。旧的节点字典 continuation 不再直接传入 SCAN。

上述续查不提供数据库式快照：Redis 扫描期间发生写入、删除、过期或迁槽时仍受 SCAN 原生语义约束；批次摘要只保证未读完批次发生变化时明确拒绝，不承诺动态数据集 exactly-once。真实单机和三主节点 Cluster 的合成稳定数据集验收纳入 CI，覆盖 0/50/51/501 键；测试只创建和清理自身无持久化数据卷的隔离容器。

Oracle 第一页使用空值游标时必须显式绕过 keyset 比较，避免空字符串被解释为 NULL 后把全部表过滤掉。后续页继续使用原始返回表名作为排他下界。

- [目录构建需要扫描当前 Published Resource 摘要] → 只读取非敏感索引字段，在授权过滤后分页；用候选摘要检测翻页期间变化，不持久化目录副本。
- [多个角色的工具和 scope 组合可能误放大权限] → 以单个 access 记录为单位匹配工具和 scope，再对合法结果求并集，禁止先分别合并工具与 scope。
- [发布或授权在翻页期间变化] → cursor 判定过期，要求从第一页重查；不提供旧 Revision 或旧权限回退。
- [Redis Cluster cursor 在不同 redis-py 版本中形状不同] → gateway 做显式类型规范化并测试标量、节点映射和非法值；不把原始对象直接序列化给模型。
- [单表字段超过字段上限] → 继续返回明确字段截断信息；本变更分页单位是表而非单列，避免破坏既有嵌套 `tables[].columns[]` 契约。
- [新 schema hash 使旧发布不可调用] → 部署后按 Agent → Application 顺序重新发布并创建新 Job；旧 Job 保持不可变且不静默升级。

## Migration Plan

1. 部署代码 Manifest、授权目录、cursor codec、Schema/Redis continuation 和测试；不执行数据库 migration。
2. 在管理端为目标 Agent 选择 `list_available_tool_resources`，并重新发布 Agent。
3. 在业务应用和角色中加入该 Tool，确认原有 Database/Redis/Loki Tool 与 scope 未扩大，再重新发布/激活应用。
4. 创建新 Job 验证资源目录、Schema 第二页、Redis 第二页、授权拒绝及审计；旧 Job 不重放、不修改。
5. 回滚时恢复旧代码与旧 Publication；新 Job 的 schema hash 将失败关闭，不回退到不匹配实现。

## Open Questions

无。用户已确认“全部资源”限定为当前 Job 所属业务应用内、当前用户获授权的全部资源，并确认不为任意数据库查询或 Loki 日志结果增加通用分页。
