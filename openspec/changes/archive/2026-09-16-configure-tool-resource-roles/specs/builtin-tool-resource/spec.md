## MODIFIED Requirements

### Requirement: 工具资源必须按调用目标唯一解析
`tool-mcp` SHALL 使用 Agent 在当前 Tool Call 中提供的 `environment`、可选 `base`/`workshop`/`placement`、Tool 资源类型和当前可用 Published Resource Revision 解析资源；调用目标 MUST 先通过当前角色数据范围校验。`placement` SHALL 表示可自定义资源角色而不局限于 cloud/edge，且不成为授权维度。匹配结果 MUST 恰好为一个，不得按顺序、默认值、最近父级或最新版本猜测；Job Snapshot 或 Routing Context 中的历史目标字段 MUST NOT 覆盖调用参数。

#### Scenario: test 环境唯一 MySQL 资源
- **WHEN** Tool Call 目标为 `environment=test` 且只有一个符合条件的已发布 MySQL Resource Revision
- **THEN** 工具使用该版本并记录资源 identity/revision 的非敏感审计

#### Scenario: 环境级资源不要求基地或车间
- **WHEN** Agent 调用目标为 `environment=test`、未提供 base/workshop，且存在唯一 environment scope 资源
- **THEN** 资源可以唯一解析，服务端不得要求虚构基地或车间

#### Scenario: 调用目标超出角色数据范围
- **WHEN** Agent 提供的 environment/base/workshop 不在当前用户角色数据范围内
- **THEN** 调用在资源连接前失败关闭，且不得尝试其它环境或候选

#### Scenario: 资源零命中或多命中
- **WHEN** 目标没有资源或存在两个同等候选
- **THEN** Tool Call 返回稳定资源解析错误且不访问任何候选

#### Scenario: cloud 与 edge 并存
- **WHEN** 同一逻辑目标存在 cloud 与 edge 资源
- **THEN** 调用必须提供明确 placement，否则失败关闭

#### Scenario: 自定义角色区分同目标实例
- **WHEN** 同一环境、基地、车间下两个资源分别发布角色“云”和“边”
- **THEN** 目录分别返回 AVAILABLE 与原样角色，调用显式角色只命中对应资源；未明确角色时不得猜测

#### Scenario: 同角色仍重复
- **WHEN** 同目标同资源类型下存在两条角色相同或同时为空的资源
- **THEN** 目录仍返回 AMBIGUOUS，不因名称差异、搜索过滤或分页而视为唯一

#### Scenario: 角色输入安全与兼容
- **WHEN** 输入旧 cloud/edge 或合法自定义角色
- **THEN** 仅允许有界中文、字母数字及 `_ . : -`，去首尾空白后精确匹配；空值兼容未指定，非法字符被拒绝；Loki 继续拒绝非空角色
