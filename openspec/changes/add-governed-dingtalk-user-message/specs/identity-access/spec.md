## ADDED Requirements

### Requirement: 批量消息收件人必须与确认主体分离
系统 SHALL 保持原始内部用户及其钉钉身份为 Action Intent 的 actor 和唯一确认人，并把官方 batch Tool 的非空 `user_ids` 建模为独立外部收件人集合。收件人可以来自本轮 Agent 搜索/消歧结果或用户直接提供的明确 userId；系统 MUST NOT 使用当前发起人、昵称、姓名首个匹配、JWT、Credential、其它 Job 的候选或未经用户消歧的模型文本替代任一目标。

#### Scenario: 当前用户选择多名员工
- **WHEN** 当前用户从本轮候选中明确选择多个稳定 userId
- **THEN** Intent 仍以当前用户为 actor/确认人，并把所选 `user_ids` 冻结为独立收件人集合
- **AND** 任一收件人都不会获得确认该 Intent 的权限

#### Scenario: 用户直接提供明确 userId
- **WHEN** 用户直接提供一个或多个明确 userId 且批量 Tool 已授权
- **THEN** 系统 MAY 直接准备该批量 Tool 的确认 Intent
- **AND** MCP 服务不得把这些 ID 替换为搜索结果、当前用户或其它同名人员

#### Scenario: Agent 根据发送人昵称回退
- **WHEN** 姓名搜索失败但当前发送人的昵称与查询词相似
- **THEN** 系统不得把当前发送人自动解释为目标收件人
- **AND** 不创建消息或工作通知 Intent

### Requirement: 执行前必须复核原主体和服务端执行身份
worker SHALL 在机器人批量消息执行前复核原始内部用户、原钉钉外部身份、来源企业、Connector/Credential、Publication、角色、Job Snapshot 和 robot code 与 Intent 冻结事实一致。原主体解绑、停用、换绑或歧义，或者任一服务端执行身份事实漂移，MUST 阻止 Provider 写入；系统不得改用其它 Connector、身份、当前用户或同名人员继续执行。

官方 batch Tool 接受明确 userId，因此身份复核 MUST NOT 被扩展为 MCP 服务端对每个收件人进行隐式详情预查。按姓名发起时的人员解析和消歧属于确认前的 Agent 多 Tool 编排。

#### Scenario: 原主体换绑
- **WHEN** 冻结收件人不变但原确认人的钉钉身份已换绑
- **THEN** worker 拒绝执行且不得使用新身份静默续行

#### Scenario: Connector 执行身份漂移
- **WHEN** 确认后 Connector、Credential 关联或 robot code 不再匹配 Intent
- **THEN** worker 在 batch endpoint 前失败关闭
- **AND** 不改用其它 Connector 或修改收件人集合
