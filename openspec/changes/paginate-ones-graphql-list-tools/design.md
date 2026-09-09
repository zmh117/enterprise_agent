## Context

当前 ONES MCP 有八个除 `ones_work_item_search` 外的 GraphQL 列表 Tool。它们都返回有界数组和 `truncated`，但公开输入均不能提交 cursor。五类 `buckets` Operation 已能取得 `pageInfo.endCursor/hasNextPage`，其中项目、测试计划和测试用例文档仍把 `after` 固定为空字符串；工作项与测试库虽把 Provider cursor 投影为 `next_cursor`，也没有可信公开续页入口。工作项类型和测试模块 Operation 返回不带 `pageInfo` 的直接完整列表，Parser 仅在本地切片。

现有 `ones_work_item_search` 已实现 Job/授权/身份/查询绑定的平台不透明 cursor 和 500 条累计上限，可以复用安全模型，但不能复用其固定关键词/类型 request binding。所有新 schema 仍受 Publication/Application/Job 冻结约束；真实 ONES 行为必须与 Mock 分开验收。

## Goals / Non-Goals

**Goals:**

- 让所有当前会产生截断的 ONES GraphQL 列表 Tool 都能从第一页安全续查到终页或 500 条累计上限。
- 保留工具现有业务筛选、字段投影和单页上限，不把 51/101/201 统一成一个无业务依据的数字。
- 使用同一个通用游标绑定模型，拒绝跨 Tool、Job、用户、应用、授权、schema、外部身份、Team 和查询复用。
- 对 Provider 原生游标与无游标直接列表分别采用可验证的 continuation，并保持模型不可见原始 Provider cursor。
- 让 `total/returned/cumulative_returned/truncated/pagination_limit_reached/next_cursor` 语义在这些 Tool 中一致。

**Non-Goals:**

- 不修改详情 Tool、REST 列表 Tool、写 Tool 或 `ones_work_item_search`。
- 不提供无界导出，不把单条分页链累计上限提高到 500 以上。
- 不新增任意 GraphQL、动态 Operation、调用方可控 URL/Header/Team/Provider cursor。
- 不承诺无 Provider cursor 的直接列表在集合变化时无缝续页；变化时明确失败并要求重查。
- 不以 Mock 结果替代真实 ONES 的分页、计数和游标稳定性验收。

## Decisions

### 1. 按工具保留单页上限，统一分页分页协议而不是统一数字

公开上限保持不变：项目、工作项类型、复杂工作项、测试库和测试计划为 100；测试模块和测试用例为 200。GraphQL 文档中的 101/201 继续作为相应集合的内层保护，`work_item_search` 的 51 不在本 change 修改范围。所有 `buckets` Operation 的实际页大小由代码构造的 `$pagination.limit` 决定，固定 `after: ""` 改为只接收服务端解码后的 Provider cursor。

备选方案是统一为 50；它会无必要降低已有测试资产查询能力，也不能解决无法续页的问题，因此不采用。

### 2. 通用游标支持 provider 与 snapshot-offset 两种固定模式

新增通用 ONES GraphQL 列表游标，位置只允许两种代码选择的结构：

- `provider`：保存原始 Provider `endCursor` 和此前累计返回数；适用于项目、复杂工作项、测试库、测试计划和测试用例。
- `snapshot-offset`：保存下一偏移、整个有序 UUID 集合的摘要和此前累计返回数；适用于工作项类型与测试模块。续页时重新执行同一固定只读 Operation，集合摘要不一致则返回游标已失效。

游标 purpose 包含精确 Tool identifier；request hash 使用去除 `cursor` 后的全部规范化业务参数；上下文继续绑定 Job、内部用户、业务应用、Agent/Application Publication、授权 hash、Tool input schema hash、ONES 外部身份和 Team。

备选方案是把 Provider cursor 直接返回给模型；它无法在 Provider 调用前阻止跨查询与跨执行主体复用，因此不采用。对直接列表伪造 Provider cursor 也没有接口证据，不采用。

### 3. 分页服务层统一生成公开结果

新增分页 GraphQL 查询基类，在解析 Principal 后解码 cursor，将内部 Provider cursor 或 offset 注入固定 Operation，并在响应后统一：

- 移除内部 continuation 字段；
- 计算本页 `returned` 和链路 `cumulative_returned`；
- 当 Provider/本地集合仍有后续且累计小于 500 时签发平台 `next_cursor`；
- 当累计达到 500 且仍有后续时返回 `pagination_limit_reached=true` 且不签发 cursor；
- 当报告有后续却缺少合法 continuation、返回空页但仍称有下一页、或 snapshot 集合发生变化时失败关闭。

自定义选项工作项查询仍先按当前 Team 字典验证字段和值，再进入相同分页基类；cursor request binding 使用调用方规范化参数，不使用内部转换出的 Provider filter key。

### 4. Provider Parser 必须按累计位置解释 pageInfo

所有 bucket Parser 把此前累计返回数传给共享 `page_items`，避免终页仍因 `totalCount > 当前页 count` 被错误标记为截断。`hasNextPage` 是 Provider continuation 的主要事实；`totalCount` 继续作为 Provider 报告值展示，但不能单独替代游标终止条件。

对于 `preciseCount=false` 的 Provider Operation，不把 `totalCount` 宣称为权限过滤后的精确总数；完整性由 `hasNextPage=false` 或平台累计上限决定。

### 5. Schema 变化只通过新 Publication 生效

八个 Tool 的 input schema 新增可选 `cursor`，output schema新增 `cumulative_returned` 与 `pagination_limit_reached`，并将公开 `next_cursor` 上限统一为 4096。代码 Manifest schema hash 随之变化。旧 Publication、旧 Job 和旧授权快照不自动升级，也不得放宽 drift 失败关闭。

## Risks / Trade-offs

- [真实 ONES 对某些内部 GraphQL 文档的 `$pagination.after` 行为与 Mock 不同] → 保持固定 Operation 和现有查询结构，补齐请求/响应测试，并把真实只读首/续/终页作为独立验收门槛。
- [直接列表在两次调用之间变化] → cursor 保存有序 UUID 集合摘要，变化时失败关闭，不返回可能重复或遗漏的页面。
- [直接列表每页都需重新读取完整 Provider 响应] → 仍受现有 1 MiB Provider 响应限制和 500 条平台累计上限保护；若将来 Provider 提供原生 cursor，再通过独立 change 切换。
- [schema hash 更新导致旧 Job drift] → 只通过重新发布 Agent/Application 启用新 schema，历史快照保持不可变。
- [固定内层 101/201 与 Provider 外层 page size 语义漂移] → 测试同时断言固定文档、实际 `$pagination.limit/after` 和 Parser 输出；真实环境验收记录每页 count、hasNextPage 和 cursor 前进事实。

## Migration Plan

1. 更新 delta spec、共享 Tool schema、通用游标和 Provider Operation/Parser。
2. 更新合成 Mock 与回归，覆盖每种分页模式、终页、500 上限、篡改/跨上下文和集合漂移。
3. 严格校验 OpenSpec，运行 ONES MCP、Manifest、Principal、Runtime、Mock 和静态检查。
4. 重建并替换本地 `ones-mcp` 及依赖共享 Manifest 的服务，核对容器内关键文件和 Tool schema。
5. 重新发布 Agent 与业务应用后，以新 Job 在真实 ONES 对每类 Provider cursor Operation 完成只读首/续/终页验收；未完成前只标记本地 Confirmed-current。

回滚时恢复旧代码并重新发布旧 schema 的 Agent/Application；已经冻结新 schema 的 Job 不静默降级，要求重新发起。

## Open Questions

无。
