## MODIFIED Requirements

### Requirement: 工作项搜索公开输入契约固定
`ones_work_item_search` Input Schema MUST 只公开 `keyword`、`issue_type`、`limit` 和可选 `cursor`；`issue_type` MUST 限定为 `demand`、`task`、`defect`，`limit` MUST 为 1 至 50 的整数，`cursor` MUST 为长度不超过 4096 的平台不透明字符串。User ID、Team ID、Token、Origin、Path、Provider cursor 和 GraphQL document MUST NOT 公开。

#### Scenario: Agent提交合法首查
- **WHEN** Tool Input 包含合法 keyword、issue_type 和 limit 且不包含 cursor
- **THEN** ONES MCP 接受输入并从当前已验证 Principal 与 Credential 注入 User、Team 和 Token
- **AND** 使用第一页 Provider 分页位置执行查询

#### Scenario: Agent提交合法续页
- **WHEN** Tool Input 包含合法 keyword、issue_type、limit 和由上一页签发的 next_cursor
- **THEN** ONES MCP 校验游标执行上下文与查询绑定后执行下一页查询

#### Scenario: limit或cursor超出范围
- **WHEN** Agent 提交 limit 为 0、51 或非整数，或者 cursor 为空以外且超过 4096 字符
- **THEN** 系统在外部调用前拒绝并返回结构化输入错误

#### Scenario: Agent尝试覆盖Team
- **WHEN** Tool 输入包含 `team_id`、`user_id`、认证字段、原始 Provider cursor 或其它未知字段
- **THEN** 系统按未知或禁止字段拒绝且不使用这些值

### Requirement: 工作项搜索公开输出契约固定
`ones_work_item_search` Output Schema MUST 返回单页有界工作项数组，每项只包含 `number`、`name`、`type`，并返回 `total`、`returned`、`cumulative_returned`、`truncated`、`pagination_limit_reached`、可选 `next_cursor` 和 `untrusted_data=true`；所有字段 MUST 完整通过代码固定的类型和大小校验后才能交给模型。

#### Scenario: 返回有限搜索结果
- **WHEN** ONES 返回匹配工作项且 Operation 解析成功
- **THEN** 模型只收到契约字段、分页计数和截断状态
- **AND** items 与 returned 均不超过请求 limit 和 50 条单页上限

#### Scenario: 单项缺少必填number
- **WHEN** 外部响应中的任一映射项无法产生合法 number
- **THEN** 整次调用按输出契约错误失败且不返回其他部分工作项

#### Scenario: 外部结果超过limit且可续页
- **WHEN** ONES 匹配数超过请求 limit、Provider 返回合法 endCursor 且累计返回数小于 500
- **THEN** 规范化输出最多包含 limit 项、truncated=true、pagination_limit_reached=false 和平台签发的 next_cursor

#### Scenario: Provider结果已经读完
- **WHEN** Provider 明确报告没有下一页
- **THEN** 输出 truncated=false、pagination_limit_reached=false 且不返回 next_cursor

### Requirement: ONES 搜索使用固定只读 GraphQL POST
工作项搜索 MUST 使用代码拥有的固定 GraphQL document 和 Operation，以 POST 调用代码固定的 ONES GraphQL 路径。模型、Agent、Application、数据库和管理 API MUST NOT 修改 document、operation name、URL、Method、Header 模板、原始 Provider 分页位置或响应解析逻辑。续页位置 MUST 仅来自 ONES MCP 对平台游标签名校验后的内部解码结果。

#### Scenario: 执行工作项首查
- **WHEN** 已授权 Job 调用不带 cursor 的 `ones_work_item_search`
- **THEN** ONES MCP 使用代码固定 GraphQL document、变量和空 after 执行只读 POST
- **AND** 返回经过代码固定解析与限界的工作项摘要

#### Scenario: 执行工作项续页
- **WHEN** 已授权 Job 使用合法平台游标调用 `ones_work_item_search`
- **THEN** ONES MCP 只把解码出的 Provider 分页位置注入代码固定的 pagination.after
- **AND** 模型不能直接提供或覆盖该值

#### Scenario: 输入尝试覆盖请求定义
- **WHEN** Tool 输入包含 GraphQL 文本、URL、Method、Header、原始 Provider cursor 或解析模板
- **THEN** 输入 schema 或 Operation 在发起外部请求前拒绝

### Requirement: ONES查询公开输入输出必须有界
`ones_work_item_search` SHALL 只接受 `keyword`、`issue_type`、`limit` 和可选的平台不透明 `cursor`；`keyword` 长度为 1..200，`issue_type` 只允许 `demand|task|defect`，`limit` 为 1..50，`cursor` 最长 4096 字符。输出 SHALL 只包含单页有界 `number/name/type` 列表、`total`、`returned`、`cumulative_returned`、`truncated`、`pagination_limit_reached`、可选 `next_cursor` 和 `untrusted_data=true`；一条分页链累计最多返回 500 条。

#### Scenario: 合法首查
- **WHEN** Agent 提交合法 keyword、issue type 和 limit
- **THEN** MCP 返回不超过 limit 的规范化第一页结果及分页状态

#### Scenario: 合法续页
- **WHEN** Agent 保持同一查询条件并提交上一页返回的 next_cursor
- **THEN** MCP 返回下一页且 cumulative_returned 包含此前页面与当前页面的累计数量

#### Scenario: 达到累计上限
- **WHEN** 当前页使分页链累计达到 500 条且 Provider 仍有下一页
- **THEN** MCP 返回 truncated=true 和 pagination_limit_reached=true，不返回 next_cursor，也不再允许该分页链继续

#### Scenario: 输入尝试覆盖身份或GraphQL
- **WHEN** Tool Input 包含 user ID、Team、Token、URL、Header、query、document、原始 Provider cursor 或其它额外字段
- **THEN** 输入 schema 拒绝整个调用且不访问数据库凭据或 ONES

## ADDED Requirements

### Requirement: ONES工作项续页游标绑定当前执行事实
系统 MUST 将 `ones_work_item_search` 的 next_cursor 绑定到当前 Job、当前用户、业务应用、授权 hash、Tool schema、ONES 外部身份、默认 Team 以及不含 cursor 的查询参数。系统 MUST 在访问 Provider 前拒绝篡改、跨 Job、跨用户、跨应用、跨授权、跨身份、跨 Team 或跨查询条件复用的游标。

#### Scenario: 同一查询合法续页
- **WHEN** 当前 Job 使用上一页签发的 next_cursor 且所有绑定事实未变化
- **THEN** MCP 解码 Provider 分页位置和累计计数并允许一次续页请求

#### Scenario: 游标跨查询复用
- **WHEN** Agent 修改 keyword、issue_type 或 limit 后复用旧游标
- **THEN** MCP 返回分页游标无效且不访问 ONES

#### Scenario: 游标跨执行主体复用
- **WHEN** 游标被另一个 Job、用户、业务应用、授权快照、ONES 身份或 Team 使用
- **THEN** MCP 返回分页游标无效或已失效且不访问 ONES

#### Scenario: Provider缺少续页位置
- **WHEN** Provider 报告 hasNextPage=true、累计数小于 500 但未返回合法 endCursor
- **THEN** MCP 按 Provider schema 错误失败关闭，不向模型返回无法续页的部分成功结果
