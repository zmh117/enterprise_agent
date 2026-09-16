## ADDED Requirements

### Requirement: Agent必须通过ONES查询Skill编排复杂只读查询
系统 SHALL 提供可选择的 `ones-query` Skill，指导 Agent 把复杂 ONES 请求拆为实时项目、迭代、事项类型和人员发现，受管状态或自定义选项解析，以及对应的只读工作项查询。Skill MUST NOT 内嵌真实 Team、项目、人员、状态、字段或选项 UUID，不得指导 Agent 读取字典文件、提交 Provider 筛选键或执行任意 GraphQL/REST。

#### Scenario: 查询某项目最新迭代已完成任务
- **WHEN** 用户用中文项目名和“最新迭代”“已完成”等语义提出查询
- **THEN** Agent 先使用实时 Tool 解析项目与迭代，再按稳定完成类别或有证据的精确状态查询工作项
- **AND** 项目或迭代存在多个合理候选时不猜测 UUID

#### Scenario: 查询自定义选项
- **WHEN** 用户用中文字段名和选项名描述自定义筛选
- **THEN** Agent 调用 `ones_resolve_query_conditions` 获取有界候选，再把确认后的字段 UUID 与选项 UUID 传给 `ones_query_work_items_with_custom_options`
- **AND** Agent 不读取受管字典文件、不构造 Provider 筛选键，也不自动选择同名候选的第一项

#### Scenario: 用户提出可变统计需求
- **WHEN** 用户要求统计完成量、响应时间或其他指标
- **THEN** Agent 仅按本次用户明确的统计口径选择数据和计算方式
- **AND** 完成定义、首次响应、工作时段、排除项、分组或月份边界缺失且会显著改变结果时，Agent 先请求澄清

#### Scenario: Skill未进入当前Publication
- **WHEN** 已冻结 Agent Publication 或 Job snapshot 未选择 `ones-query`
- **THEN** 运行时不加载该 Skill
- **AND** 新 Skill 只能通过新的 Agent Publication 以及后续显式 Business Application 发布与激活生效
