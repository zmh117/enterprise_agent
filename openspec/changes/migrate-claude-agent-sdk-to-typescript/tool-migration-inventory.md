# 当前Tool远程MCP迁移清单

## 结论

`mcp_new` 的真实 Claude Client 目前把两类能力动态注册为名为 `internal` 的进程内 SDK MCP Server。TypeScript Runtime 无法安全复用 Python 闭包，因此灰度前需要一个代码注册、按 Job Token 复核的 `runtime-tool-mcp` 服务。该服务只代理当前已注册能力，不接受自由 Tool、URL、SQL模板、脚本或任意 Handler。

## 内置只读Tool映射

| 当前Tool | 当前执行事实源 | 远程MCP名称 | 灰度要求 |
|---|---|---|---|
| `get_er_context` | `ReadOnlyToolService` / Internal API client | 同名 | 必须保持 Job/project 权限和有界结果 |
| `get_business_flow_context` | `ReadOnlyToolService` / Internal API client | 同名 | 必须保持 Job/project 权限和有界结果 |
| `get_schema_directory` | `ReadOnlyToolService` / Internal API Platform | 同名 | 必须保持 environment/base/workshop scope |
| `diagnose_loki_labels` | `ReadOnlyToolService` / Internal API Platform | 同名 | 必须保持 Loki scope 和时间/数量限制 |
| `diagnose_loki_label_values` | 同上 | 同名 | 同上 |
| `diagnose_loki_probe` | 同上 | 同名 | 同上 |
| `query_loki` | 同上 | 同名 | 必须保持只读 selector/query policy |
| `query_database` | 同上 | 同名 | 必须继续经过 SQL 只读策略、schema、行数和响应上限 |
| `query_redis_get` | 同上 | 同名 | 必须保持 datasource/key scope |
| `query_redis_scan` | 同上 | 同名 | 必须保持 prefix/数量边界 |

这些 Tool 继续调用现有 `ToolRegistry.call()`，远程层不重写 SQL、Loki、Redis 或上下文实现。

## Governed QUERY Capability映射

当前 `AgentExecutionContext.governed_capabilities` 中的精确 identifier、release ID、input schema 和 data classification 由 Job/Application Publication 固定。远程服务只可为 Token 中冻结的 identifier 注册调用，并继续委托 `GovernedApiRuntimeExecutor.execute()`；不得让 Runtime 或模型提供 release ID、endpoint、Credential、Header 或 URL。

## Token与调用复核

每次远程 MCP 调用至少复核：

- Token issuer/audience/authorized party/expiry/JTI；
- `job_id`、app user、application publication 与数据库事实一致；
- Job 仍处于可执行状态；
- Tool 名在当前 Job 固定 allowlist 内；
- 内置 Tool 仍在 `ToolRegistry.READONLY_TOOLS` 和 Handler Registry；
- governed Capability identifier/release 与 Job 冻结集合一致；
- project、environment/base/workshop、resource 和业务授权由现有服务再次检查。

## 失败关闭门禁

- `runtime-tool-mcp` 未就绪、Token 无效、Job 终态、Tool 未映射或 schema hash 不一致时，调用必须失败且不得进入底层 Handler。
- 对应 Application 不得切换 `typescript-v1`，直到其全部 Tool 在该服务中具有等价映射和契约测试。
- Runtime transport 失败不得改用 Python SDK；由 Python Job retry policy 处理。

## 不移植的mcp_dev内容

本变更不引入 `mcp_dev` 的 `mcp_resource_*`、MCP Tool Publication 控制面、ONES provider credential 重构或 destructive schema 清理。未来若独立采用这些能力，应通过新的 OpenSpec change 演进；当前桥接只保持 `mcp_new` 已有行为。
