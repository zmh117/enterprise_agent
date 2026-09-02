## RENAMED Requirements

- FROM: `### Requirement: ONES MCP只发布两个代码固定只读Tool`
- TO: `### Requirement: ONES MCP只发布代码固定受治理Tool`

## MODIFIED Requirements

### Requirement: ONES MCP只发布代码固定受治理Tool
ONES MCP SHALL 发布代码 Manifest 固定的两个只读 Tool `ones_work_item_search`、`ones_list_project_role_members`，以及仅更新单个现有缺陷、受支持确认策略保护的 mutation Tool `ones_update_task`。`ones_update_task` MUST 声明稳定 schema hash、`effect=mutation`、确认策略、operation code、风险和目标策略；系统 MUST NOT 发布任意 GraphQL、任意 REST、其它写操作或数据库动态定义的 ONES Tool。

#### Scenario: 列出ONES MCP工具
- **WHEN** Runtime 为已授权 Job 请求 ONES MCP `tools/list`
- **THEN** 可见集合只能是该 Job 冻结且授权的上述三个代码固定 Tool 的子集
- **AND** 未经 Agent/Application Publication 选择的 `ones_update_task` 不可见

#### Scenario: 请求未注册ONES Tool
- **WHEN** 模型请求任意 GraphQL、任意 REST 或其它 ONES Tool 名称
- **THEN** 服务在解析个人 Credential 或 Provider 网络访问前拒绝

#### Scenario: mutation合同缺少确认元数据
- **WHEN** `ones_update_task` 的 effect、确认策略、operation code、风险、目标策略或 schema hash 缺失、未知或漂移
- **THEN** Manifest 校验、发布、Job 创建或调用在最早可判定阶段 fail closed

#### Scenario: 调用已授权ONES更新Tool
- **WHEN** 当前钉钉来源 RUNNING Job 冻结并授权了合同一致的 `ones_update_task`
- **THEN** Tool 只创建受逐次确认保护的 Action Intent
- **AND** 不得在用户确认前执行 ONES 写请求
