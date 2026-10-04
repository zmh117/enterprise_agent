## MODIFIED Requirements

### Requirement: 九类 ONES 集合必须自动有界收集
`ones_work_item_search`、`ones_search_projects`、`ones_list_issue_types`、`ones_query_work_items_with_custom_options` 的累计上限 MUST 为 1000；`ones_query_work_items`、`ones_list_testcase_libraries`、`ones_list_testcase_modules`、`ones_list_test_plans`、`ones_query_test_cases` 的上限 MUST 为 10000。模型不得收发 limit/cursor，REST 列表保留各自有界合同。集合输出包含 total、returned、cumulative_returned、truncated、pagination_limit_reached 与 untrusted_data=true，不返回模型续页游标。

#### Scenario: 扩展集合超过一页
- **WHEN** 普通工作项查询或四类测试资产尚有后续且未达到 10000 与时间容量预算
- **THEN** 程序继续收集，不因短页或 total 值提前判定完成

#### Scenario: 达到累计上限
- **WHEN** 收集达到该工具固定上限且仍有后续
- **THEN** truncated 与 pagination_limit_reached 均为 true，Agent 不得声称已获得全量

#### Scenario: 其他列表超过 1000
- **WHEN** 工作项关键词搜索、项目/类型列表或自定义选项工作项查询达到 1000
- **THEN** 仍按 1000 终止，不继承扩展集合的 10000 限制

### Requirement: ONES 自动收集必须精确遵循 Provider 页合同
bucket 列表 MUST 使用固定不做业务分组的 groupBy、稳定筛选排序、最多 200 的 pagination.limit 与前页 endCursor；以 hasNextPage 判断完成，不以 totalCount 推断精确授权总量。不得裁剪 Provider 页后沿用该页尾游标。直接完整列表如测试库模块只单次读取并有界截取，不伪造分页。

#### Scenario: 短页仍有后续
- **WHEN** Provider 只返回 50 条且 hasNextPage=true
- **THEN** 按原 endCursor 继续，游标只在本次调用内使用

#### Scenario: 分页不稳定
- **WHEN** unstable=true、多个 bucket、重复记录/游标、空续页、count 不符或页长超过请求大小
- **THEN** 返回稳定安全错误，不发布部分集合为成功

#### Scenario: 收集预算耗尽
- **WHEN** 普通工作项查询或四类测试资产已耗尽 200 请求、其他集合 50 请求，或达到 90 秒/8 MiB 规范化结果预算
- **THEN** 有界失败，不无限翻页，不扩大授权或自动降低筛选精度
