# 标准 MCP Tool 清单

当前两个 Runtime 都连接固定服务码 `tool-mcp`。Tool 来自代码 Manifest，不经过动态 Handler 或 Release。

| Tool | 资源类型 | 关键边界 |
|---|---|---|
| `get_er_context` | 无 | Job/Application Tool 子集与有界结果 |
| `get_business_flow_context` | 无 | Job/Application Tool 子集与有界结果 |
| `get_schema_directory` | database | 目标、数据范围、Published Resource |
| `query_database` | database | schema、SQL 只读、行数和响应上限 |
| `query_redis_get` | redis | key 前缀和响应上限 |
| `query_redis_scan` | redis | prefix、scan 数量和响应上限 |
| `diagnose_loki_labels` | loki | selector、时间和数量限制 |
| `diagnose_loki_label_values` | loki | selector、时间和数量限制 |
| `diagnose_loki_probe` | loki | selector、时间和数量限制 |
| `query_loki` | loki | selector/query 只读策略 |

每次调用复核 Job 状态、精确 tool identifier/schema hash、当前用户、Application、角色 Tool grant、数据范围和资源唯一解析。Job 终态、撤权、Tool 未分配、schema drift、资源零命中/多命中均失败关闭；transport 失败由 Worker 的 Job retry policy 处理，不跨 Runtime fallback。
