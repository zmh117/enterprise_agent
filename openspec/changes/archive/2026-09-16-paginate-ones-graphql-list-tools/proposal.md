## Why

2026-09-10 后续确认：仅 ones_list_testcase_libraries、ones_list_testcase_modules、ones_list_test_plans、ones_query_test_cases 四个测试资产列表累计上限提高到10000。其余五个 GraphQL 列表仍为1000，详情/REST/写工具不变；bucket单页最多200，测试资产最多200次请求以覆盖50条短页，保留90秒、8MiB及沙盒预算与清理。公开输入不新增limit/cursor。

2026-09-10 用户确认：九个 GraphQL 列表由服务端固定收集到终页或1000条，移除 MCP 入参 limit，防止模型把累计上限降到50。ONES 内部 pagination.limit 仍只表示单次请求页大小，最多200。REST接口不变，旧发布快照不静默升级。

第三阶段（用户要求，2026-09-09）：移除可运行的 ONES Mock 干扰，以 `ones_mock/ones` 中的现场接口结构逐项核对当前已注册 Operation，修复进度/时间单位、响应解析和安全错误定位。现场材料仅作为结构证据，认证材料与业务正文不得进入代码、测试或日志；现场文档保留，测试替身仅放在 tests 中用于进程内校验。用户最终确认：保留接口修复，只删除 Mock 服务，恢复环境示例及额外配置改动；ones-mcp 保持原启动方式和连接配置，不连接真实 ONES。本阶段明确包含 REST 和详情解析，不沿用下方第一阶段的排除项。

2026-09-09 用户确认的新范围替代下述第一阶段方案：九个 GraphQL 列表（包含 `ones_work_item_search`）由程序自动分页，每批最多 200 条、每次默认/最多 1000 条，不再向模型公开 cursor；Runtime 将结果写入 Job 只读临时沙盒并在 Job 终态清理。Tool Call 时间线显示既有安全错误报文与错误码。下方旧 cursor/500 条范围只保留为第一阶段背景，不再作为当前实施契约；以本 change 最新 delta 和 design 的第二阶段决策为准。

除 `ones_work_item_search` 外，当前 ONES GraphQL 列表 Tool 最多只返回首屏：部分 Operation 虽返回 Provider `endCursor`，公开输入却不能提交 cursor；另一些无 Provider cursor 的列表只在本地截断。Agent 因而无法完整读取项目、工作项类型、复杂工作项、测试库、测试模块、测试计划和测试用例，也可能把固定首屏误述为全部结果。

## What Changes

- 为 `ones_search_projects`、`ones_list_issue_types`、`ones_query_work_items`、`ones_query_work_items_with_custom_options`、`ones_list_testcase_libraries`、`ones_list_testcase_modules`、`ones_list_test_plans` 和 `ones_query_test_cases` 增加可选的平台不透明 `cursor` 输入，并统一输出 `returned`、`cumulative_returned`、`truncated`、`pagination_limit_reached` 与可选 `next_cursor`。
- 保留各 Tool 现有单页上限：项目、类型、复杂工作项、测试库和测试计划最多 100 条，测试模块和测试用例最多 200 条；每条分页链累计最多向模型返回 500 条。
- 对 ONES `buckets.pageInfo` 明确提供 continuation 的 Operation 使用 Provider `endCursor/hasNextPage` 续页，并将固定首屏 pagination 改为代码构造的有界 `$pagination`。
- 对当前 Provider Operation 只返回完整直接列表且没有 continuation 的工作项类型和测试模块查询，使用与结果集合指纹绑定的有界本地偏移游标；分页期间集合发生变化时失败关闭并要求从第一页重查。
- 保持 cursor 与 Job、用户、业务应用、授权快照、Tool schema、ONES 身份、默认 Team 和查询条件绑定；禁止跨上下文、跨查询、篡改或过期复用。
- **BREAKING**：上述 Tool 的公开 input/output schema hash 均会变化；既有 Publication 和 Job 保持冻结事实，新能力仅通过重新发布的 Agent 与业务应用进入新 Job。
- 不修改详情 Tool、REST 列表 Tool 或已经完成安全分页的 `ones_work_item_search`。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `builtin-tool-resource`：将已有 ONES GraphQL 列表 Tool 从首屏有界查询升级为可续页、累计有界且不会把截断结果描述为全部的公开契约。
- `governed-api-capability`：为所有 ONES GraphQL 列表 Operation 统一 Provider/local continuation、游标上下文绑定、固定请求和失败关闭要求。

## Impact

- `backend/app/shared/ones_tool_contracts.py`：GraphQL 列表 Tool schema、描述和 schema hash。
- `services/ones_mcp_server/`：通用分页游标、列表 Tool 服务、固定 GraphQL variables、响应规范化和直接列表集合漂移校验。
- `services/ones_mcp_server/provider/graphql/documents/`：将固定首屏 pagination 改为代码注入的 `$pagination`；保留各列表的有界内层保护。
- `ones_mock/` 与 `backend/tests/`：Provider cursor、多页、终页、500 条上限、集合漂移、跨上下文拒绝和 schema drift 回归。
- 发布与部署：需要重建 `ones-mcp` 及依赖共享 Manifest 的服务，并重新发布 Agent/Application；真实 ONES 分页兼容性必须单独只读验收。
