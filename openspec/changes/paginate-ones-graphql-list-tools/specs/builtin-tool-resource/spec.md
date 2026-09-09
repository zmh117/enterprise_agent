## ADDED Requirements

### Requirement: ONES GraphQL列表必须自动有界收集
系统 SHALL 对 ones_work_item_search、ones_search_projects、ones_list_issue_types、ones_query_work_items、ones_query_work_items_with_custom_options、ones_list_testcase_libraries、ones_list_testcase_modules、ones_list_test_plans、ones_query_test_cases 自动收集结果。limit MUST 表示可选总量上限，默认1000，允许1至1000；模型 MUST NOT 接收或提交 cursor。输出 MUST 包含 returned、cumulative_returned、total、truncated、pagination_limit_reached、untrusted_data；Runtime MUST 将集合正文存为 Job 临时结果文件后只向模型返回元数据和读取提示。不得将 truncated 结果声称为全量。

#### Scenario: 默认读取多页
- **WHEN** 模型仅提交合法业务筛选
- **THEN** 程序自动查询到终页或1000条，并提供结果文件及完整性标记

#### Scenario: 达到上限仍有后续
- **WHEN** 收集达到调用方 limit 且 Provider 仍有后续
- **THEN** truncated 与 pagination_limit_reached 均为 true，且没有 next_cursor

#### Scenario: 新旧契约不可混用
- **WHEN** 旧 Job 的冻结 schema 与新代码不一致，或输入 cursor/Team/Token/GraphQL
- **THEN** 调用在访问 Provider 前失败关闭，不静默升级历史快照

### Requirement: Tool Call时间线必须显示安全失败原因
系统 MUST 在失败 Tool Call 中保存并展示服务端安全 error 和 error_code，支持对象和 JSON 字符串摘要。不得用通用占位文案遮蔽已存在的安全原因；不得展示原始 Provider body、认证秘密或堆栈。成功计数 MUST 优先使用 returned，不能把 total 误述为实际返回条数。

#### Scenario: ONES查询失败
- **WHEN** ones_query_work_items 返回 ones_provider_schema_invalid 或分页错误
- **THEN** 运行记录显示 FAILED、对应中文原因和错误码

#### Scenario: 上游提供敏感错误正文
- **WHEN** Provider 返回含认证信息的非规范错误正文
- **THEN** 记录和展示平台映射的安全错误，不保存或显示原始正文
