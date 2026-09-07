## Why

当前 `tool-mcp` 只能在 Agent 已知精确 environment/base/workshop/placement 后解析单个资源，却没有向当前 Job 提供经过用户、业务应用和工具授权过滤的资源目录；Agent 因而只能猜测环境并在失败后重复解释。与此同时，Schema 目录和 Redis SCAN 在达到单页上限后只标记截断、不返回可继续使用的游标，导致超过 50 条的合法结果无法完整读取。

## What Changes

- 新增代码 Manifest 所有的只读工具 `list_available_tool_resources`，分页返回当前 Job、当前用户及当前业务应用共同授权的 Database、Redis、Loki Published Resource 地址摘要。
- 资源目录只返回资源编码、类型、environment/base/workshop/placement 和用于稳定选择的非敏感版本事实；不得返回连接配置、Secret reference、数据范围细节或不可授权候选。
- 为资源目录与 `get_schema_directory` 定义统一的不透明游标协议；每页保持有界，并返回 `next_cursor`、`has_more` 与 `truncated`。
- 为 `query_redis_scan` 接入真实 Redis SCAN continuation cursor，后续页必须绑定同一 Job、资源 Revision、目标与查询条件。
- 保持 `query_database` 和 Loki 日志结果的既有行数、时间和响应大小上限，不引入通用偏移分页；调用方仍需使用受控 SQL keyset 条件或更窄的 Loki 时间窗口继续查询。
- 更新 Agent 运行指令：目标不明确时先查询授权资源目录，再使用目录返回的精确目标调用 Schema、Database、Redis 或 Loki 工具；不得猜测其他环境，也不得重复相同失败说明。
- 为 Manifest/schema 漂移、Job 快照、应用发布子集、授权拒绝、游标篡改/过期及多页续查补充测试和审计证据。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `builtin-tool-resource`: 增加 Job 绑定的授权资源发现工具、Schema/Redis 可续查分页协议，以及 Agent 的资源发现优先行为，同时保持唯一资源解析、只读执行和敏感信息隔离边界。

## Impact

- 后端：`tool-mcp` 代码 Manifest、Job Tool 服务、授权中心资源范围投影、资源解析器、Schema inspector、Redis gateway、审计与 Agent 上下文构建。
- 发布契约：新增 Tool identifier 并改变 `get_schema_directory`、`query_redis_scan` 的输入 schema hash；使用这些工具的 Agent/Application 需要重新发布，新 Job 才能获得新契约。
- 测试：资源目录授权隔离、分页游标完整性、跨资源/跨查询游标拒绝、Redis continuation、运行指令及 MCP 审计。
- 不新增数据库 migration、动态 MCP 地址、资源映射表、第二套 RBAC 或连接凭据暴露。
