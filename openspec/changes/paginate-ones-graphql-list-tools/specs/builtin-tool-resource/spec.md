## ADDED Requirements

### Requirement: ONES GraphQL列表必须自动有界收集
系统 SHALL 对 ones_work_item_search、ones_search_projects、ones_list_issue_types、ones_query_work_items、ones_query_work_items_with_custom_options、ones_list_testcase_libraries、ones_list_testcase_modules、ones_list_test_plans、ones_query_test_cases 自动收集结果。累计上限 MUST 由服务端按工具固定：ones_list_testcase_libraries、ones_list_testcase_modules、ones_list_test_plans、ones_query_test_cases为10000，其余五个列表为1000；直到终页或达到对应上限；模型 MUST NOT 接收或提交 limit/cursor。ONES 内部 pagination.limit 只表示每页大小，最多200；REST列表契约不变。输出 MUST 包含 returned、cumulative_returned、total、truncated、pagination_limit_reached、untrusted_data；Runtime MUST 将集合正文存为 Job 临时结果文件后只向模型返回元数据和读取提示。不得将 truncated 结果声称为全量。

#### Scenario: 默认读取多页
- **WHEN** 模型仅提交合法业务筛选
- **THEN** 程序自动查询到终页或该工具的累计上限，并提供结果文件及完整性标记

#### Scenario: 达到上限仍有后续
- **WHEN** 收集达到对应工具上限且 Provider 仍有后续
- **THEN** truncated 与 pagination_limit_reached 均为 true，且没有 next_cursor

#### Scenario: 新旧契约不可混用
- **WHEN** 旧 Job 的冻结 schema 与新代码不一致，或输入 limit/cursor/Team/Token/GraphQL
- **THEN** 调用在访问 Provider 前失败关闭，不静默升级历史快照

#### Scenario: 上游返回短页仍有后续
- **WHEN** Provider 每页只返回50条且 hasNextPage=true，累计尚未达到该工具上限
- **THEN** 程序按 endCursor 继续翻页，不因短页或没有显式工具limit停止

#### Scenario: 测试资产读取10000条
- **WHEN** 四个测试资产列表收集到10000条，且未超过时间与容量预算
- **THEN** 输出数组、returned和cumulative_returned均允许10000，Runtime可物化到Job只读沙盒；其他五个列表仍不得超过1000

### Requirement: Tool Call时间线必须显示安全失败原因
系统 MUST 在失败 Tool Call 中保存并展示服务端安全 error 和 error_code，支持对象和 JSON 字符串摘要。不得用通用占位文案遮蔽已存在的安全原因；不得展示原始 Provider body、认证秘密或堆栈。成功计数 MUST 优先使用 returned，不能把 total 误述为实际返回条数。

#### Scenario: ONES查询失败
- **WHEN** ones_query_work_items 返回 ones_provider_schema_invalid 或分页错误
- **THEN** 运行记录显示 FAILED、对应中文原因和错误码

#### Scenario: 上游提供敏感错误正文
- **WHEN** Provider 返回含认证信息的非规范错误正文
- **THEN** 记录和展示平台映射的安全错误，不保存或显示原始正文
