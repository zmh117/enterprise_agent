## Context

`ones_work_item_search` 是已发布的兼容型只读 Tool，当前公开契约只允许 `keyword`、`issue_type` 和 `limit`，单页上限为 50。Provider 响应已包含 `pageInfo.endCursor/hasNextPage`，但解析层丢弃游标，导致 `truncated=true` 后无法继续。该 Tool 受 Job 冻结 schema、角色授权、个人 ONES 身份、固定 GraphQL Operation 和 MCP 审计约束。

## Goals / Non-Goals

**Goals:**

- 允许同一 Job 在相同查询条件下安全续页，每页最多 50 条。
- 将游标绑定到 Job、用户、业务应用、授权事实、Tool schema、ONES 身份、Team 和查询条件，拒绝篡改与跨上下文复用。
- 每条分页链最多向模型返回 500 条，并明确区分“Provider 已读完”和“达到平台累计上限仍有后续”。
- 保持固定只读 Provider Operation、个人身份边界、审计与旧 Publication 冻结语义。

**Non-Goals:**

- 不提高单页 50 条上限，不提供无界全量导出。
- 不改变工作项字段白名单，也不新增筛选条件或写操作。
- 不自动升级旧 Agent/Application Publication、角色授权或运行中的 Job。
- 不为其它 ONES 列表 Tool 顺带增加分页。

## Decisions

### 1. 使用平台签发的不透明续页游标

公开 `cursor` 不是原始 ONES `endCursor`。ONES MCP 使用现有 `ToolPaginationCursorCodec` 封装 Provider 游标和累计返回数，并绑定当前 Job、用户、业务应用、授权 hash、Tool schema、查询参数以及当前 ONES 身份/Team。这样既能复用平台已有游标错误语义，也能阻止模型把任意游标跨查询或跨 Job 复用。

备选方案是直接透传 Provider 游标；实现更短，但不能可靠限制累计条数，也无法在 Provider 前识别跨查询误用，因此不采用。

### 2. 每次 Tool 调用只执行一页 Provider 请求

首次查询将空 `after` 注入固定 `$pagination`，续页时仅把服务端解码后的 Provider 游标注入 `after`。Agent 根据 Tool 描述，在需要完整结果时使用 `next_cursor` 重复调用，直至 `truncated=false`。每次调用仍只产生一个 Provider 审计 attempt，401 刷新后的原请求重试规则保持不变。

备选方案是在一次 Tool 调用中自动抓取全部页面；它会放大延迟、响应大小和外部调用次数，并削弱逐页审计与运行预算可见性，因此不采用。

### 3. 服务端强制累计 500 条上限

游标记录此前累计返回数。续页请求的实际 Provider `limit` 取公开 `limit` 与剩余额度的较小值，确保累计永不超过 500。达到 500 且 Provider 仍有下一页时，返回 `truncated=true`、`pagination_limit_reached=true`，不再签发 `next_cursor`；未达到上限且存在下一页时才签发新游标。

若 Provider 声称有下一页却未返回合法 `endCursor`，则在达到累计上限前按 Provider schema 错误失败关闭，避免产生无法继续却看似正常的部分结果。

### 4. Schema 变更通过新发布生效

输入新增可选 `cursor`；输出新增 `returned`、`cumulative_returned`、`pagination_limit_reached` 和可选 `next_cursor`。这会改变 manifest schema hash。新代码部署后，管理员必须重新发布 Agent 与业务应用；旧 Publication 和旧 Job 保留冻结 hash，发生 drift 时继续失败关闭。

## Risks / Trade-offs

- [真实 ONES 环境对 `pagination.after` 的行为可能与 Mock 不同] → 使用现有固定 GraphQL `Pagination` 变量和 Provider `pageInfo` 契约，补齐请求/响应测试，并将真实只读分页验收单独记录，不能用 Mock 代替。
- [分页期间身份、Team 或授权变化] → 游标绑定当前执行上下文和身份状态；变化后拒绝游标并要求从第一页重查。
- [模型未继续分页便声称完整] → Tool 描述明确要求需要完整结果时持续分页，并在 `truncated=true` 时禁止声称结果完整。
- [500 条仍不足] → 明确返回 `pagination_limit_reached=true`；用户可进一步缩小关键词或改用更精确的查询 Tool。

## Migration Plan

1. 更新 delta spec、Tool schema、游标编解码、Provider Operation、描述和测试。
2. 严格校验 OpenSpec，运行 ONES MCP、Principal、Runtime 和 schema hash 回归。
3. 重建并替换本机 `ones-mcp` 及依赖新 manifest 的服务。
4. 在 Web 重新发布 Agent，随后更新并重新发布业务应用；新 Job 才获得新 schema。
5. 使用超过 50 条的只读查询验证第一页、续页、终页和 500 条上限；未经真实 ONES 验收前标记为本地已实现、真实环境未验证。

回滚时恢复旧代码并重新发布旧 schema 的 Agent/Application；已冻结的新 Job 不应静默降级，应失败关闭并要求重新发起。

## Open Questions

无。
