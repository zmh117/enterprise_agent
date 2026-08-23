## ADDED Requirements

### Requirement: Workflow 管理必须使用 Agent 权限矩阵
系统 SHALL 将 Workflow 模板、节点、边和发布记录视为 Agent 管理资产。读取 MUST 要求 `agent/read`，草稿新增、修改、启停 MUST 要求 `agent/edit`，发布 MUST 要求 `agent/publish`；Workflow API MUST NOT 复用平台配置 manage 作为通用管理员权限。

#### Scenario: 只有 Agent 读取权限
- **WHEN** 已登录用户只有 `agents.read`
- **THEN** 用户可以读取 Workflow 模板、节点、边和最新 Publication，但修改和发布返回 403

#### Scenario: 具有 Agent 编辑权限
- **WHEN** 已登录用户具有 `agents.edit` 但没有 `agents.publish`
- **THEN** 用户可以保存草稿和修改图，但发布返回 403

#### Scenario: 具有 Agent 发布权限
- **WHEN** 已登录用户具有 `agents.publish` 且发布内容通过校验
- **THEN** 系统创建不可变 Workflow Publication 并记录当前 principal actor
