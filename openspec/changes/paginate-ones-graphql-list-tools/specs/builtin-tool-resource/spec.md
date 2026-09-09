## ADDED Requirements

### Requirement: ONES GraphQL列表Tool必须公开有界续页契约
系统 SHALL 为 `ones_search_projects`、`ones_list_issue_types`、`ones_query_work_items`、`ones_query_work_items_with_custom_options`、`ones_list_testcase_libraries`、`ones_list_testcase_modules`、`ones_list_test_plans` 和 `ones_query_test_cases` 提供可选的平台不透明 `cursor` 输入。每次调用 MUST 返回单页有界数组、Provider 报告或本地已知的 `total`、`returned`、`cumulative_returned`、`truncated`、`pagination_limit_reached`、可选 `next_cursor` 和 `untrusted_data=true`；系统和 Agent MUST NOT 在 `truncated=true` 时把结果描述为全部数据。

#### Scenario: 首次查询仍有下一页
- **WHEN** 任一上述 Tool 首次返回一页页结果且对应列表仍有后续、累计返回数小于 500
- **THEN** 输出包含 `truncated=true`、`pagination_limit_reached=false` 和平台签发的 `next_cursor`
- **AND** `returned` 不超过该 Tool 的单页上限

#### Scenario: 使用合法游标续页
- **WHEN** 同一 Job 使用上一页 `next_cursor` 且保持相同业务参数和执行上下文
- **THEN** Tool 返回下一页且 `cumulative_returned` 等于此前页面与当前页面实际返回数量之和

#### Scenario: 查询到终页
- **WHEN** Provider 或本地完整列表明确没有后续数据
- **THEN** 输出包含 `truncated=false`、`pagination_limit_reached=false` 且不包含 `next_cursor`

#### Scenario: 达到累计上限
- **WHEN** 当前页使同一分页链累计返回 500 条且列表仍有后续
- **THEN** 输出包含 `truncated=true` 和 `pagination_limit_reached=true`
- **AND** 系统不返回 `next_cursor`，也不允许该分页链继续

### Requirement: ONES GraphQL列表Tool必须保持各自单页边界
系统 MUST 保持现有业务 Tool 的单页边界：项目、工作项类型、复杂工作项、测试库和测试计划每页最多 100 条，测试模块和测试用例每页最多 200 条。公开 `limit` MUST 为 1 至对应单页上限的整数；`cursor` MUST 为长度不超过 4096 的平台不透明字符串。Team、User、Token、URL、Header、GraphQL 文本和原始 Provider cursor MUST NOT 公开。

#### Scenario: 提交超过工具上限的limit
- **WHEN** Agent 为 100 条上限的 Tool 提交 101，或为 200 条上限的 Tool 提交 201
- **THEN** 系统在 Provider 调用前返回结构化输入错误

#### Scenario: 尝试提交原始Provider游标
- **WHEN** Agent 提交 `after`、`provider_cursor`、GraphQL、Team、User、Token 或其它未知字段
- **THEN** 输入 schema 在访问凭据和 Provider 前拒绝整个调用

#### Scenario: 旧Publication继续保持冻结事实
- **WHEN** 代码 Manifest 发布带 cursor 的新 schema
- **THEN** 既有 Publication 和 Job 不自动获得新字段
- **AND** schema hash 不匹配继续在 Provider 调用前失败关闭
