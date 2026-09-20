## MODIFIED Requirements

### Requirement: 九类 ONES 集合必须自动有界收集
`ones_work_item_search`、`ones_search_projects`、`ones_list_issue_types`、`ones_query_work_items_with_custom_options` 的累计上限 MUST 为1000；`ones_query_work_items`、`ones_list_testcase_libraries`、`ones_list_testcase_modules`、`ones_list_test_plans`、`ones_query_test_cases` 的上限 MUST 为10000。模型不得收发limit/cursor，REST列表保留各自有界合同。集合输出包含total、returned、cumulative_returned、truncated、pagination_limit_reached与untrusted_data=true，不返回模型续页游标。

#### Scenario: 测试资产超过一页
- **WHEN** 四类测试资产尚有后续且未达到10000与时间容量预算
- **THEN** 程序继续收集，不因短页或total值提前判定完成

#### Scenario: 标准工作项查询超过1000
- **WHEN** ones_query_work_items匹配4715条且各项预算充足
- **THEN** 服务自动收集4715条并通过输出schema与Runtime只读物化，不在1000条停止

#### Scenario: 达到累计上限
- **WHEN** 收集达到该工具固定上限且仍有后续
- **THEN** truncated与pagination_limit_reached均为true，Agent不得声称已获得全量

#### Scenario: 其他列表超过1000
- **WHEN** 项目、类型、旧关键词搜索或自定义选项工作项查询达到1000
- **THEN** 仍按1000终止，不继承标准工作项查询或测试资产的10000限制

### Requirement: ONES 自动收集必须精确遵循 Provider 页合同
bucket列表 MUST 使用固定不做业务分组的groupBy、稳定筛选排序、最多200的pagination.limit与前页endCursor；以hasNextPage判断完成，不以totalCount推断精确授权总量。不得裁剪Provider页后沿用该页尾游标。直接完整列表如测试库模块只单次读取并有界截取，不伪造分页。

#### Scenario: 短页仍有后续
- **WHEN** Provider只返回50条且hasNextPage=true
- **THEN** 按原endCursor继续，游标只在本次调用内使用；标准工作项查询与四类测试资产可在200次请求内达到10000条

#### Scenario: 分页不稳定
- **WHEN** unstable=true、多个bucket、重复记录/游标、空续页、count不符或页长超过请求大小
- **THEN** 返回稳定安全错误，不发布部分集合为成功

#### Scenario: 收集预算耗尽
- **WHEN** 标准工作项查询或四类测试资产已耗尽200请求、其他集合50请求，或达到90秒/8MiB规范化结果预算
- **THEN** 有界失败，不无限翻页，不扩大授权或自动降低筛选精度
