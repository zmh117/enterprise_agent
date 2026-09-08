## Why

`ones_work_item_search` 当前单次最多返回 50 条，虽然能报告 `truncated=true`，却不公开续页游标，导致 Agent 无法完整读取超过 50 条的结果。周度缺陷汇总等任务因此可能把不完整数据写入下游系统。

## What Changes

- 为 `ones_work_item_search` 增加可选的、不透明且与当前 Job 和查询条件绑定的 `cursor` 输入。
- 在分页结果中返回 `returned`、`cumulative_returned`、可选 `next_cursor` 与 `pagination_limit_reached`，保留 `total` 和 `truncated`。
- 保持每页最多 50 条；Agent 在需要完整结果时按 `next_cursor` 续页，直至 `truncated=false`。
- 每条分页链最多向模型返回 500 条；达到上限且 Provider 仍有后续结果时停止签发游标，并明确报告仍被截断。
- 拒绝跨 Job、跨用户、跨应用、跨授权快照或跨查询条件复用以及篡改的游标。
- 更新固定 GraphQL Operation、Mock、审计、工具描述、测试和发布契约；已有 Publication 与 Job 不自动获得新 schema。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `governed-api-capability`：将 ONES 工作项搜索从“只报告截断”升级为有界、可续页且绑定当前执行上下文的游标分页契约。

## Impact

- 影响 `ones_work_item_search` 的公开输入/输出 schema、schema hash、ONES MCP GraphQL 请求变量和响应归一化。
- 影响 Agent 工具说明及分页编排行为、ONES Mock、MCP 审计和回归测试。
- 需要重新构建并发布 `ones-mcp`，重新发布使用该 Tool 的 Agent 和业务应用；旧 Publication、旧 Job 和旧授权快照保持原冻结事实，不自动升级。
