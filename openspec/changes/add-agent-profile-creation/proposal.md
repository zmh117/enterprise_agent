## Why

全新数据库完成基础迁移后可能没有任何 Agent 定义，而现有管理页面既没有空状态引导，也没有创建 Agent 的能力，管理员无法恢复可配置的 Python 或 TypeScript Agent。当前 canonical 仍保留“第一版不得新建 Agent”的旧限制，也需要与已经接受的多 Runtime Agent 模型统一。

## What Changes

- 在平台 bootstrap 中幂等初始化固定的 `default-diagnostic-agent`（`python-v1`）和 `typescript-diagnostic-agent`（`typescript-v1`）。
- 提供受权管理 API，允许创建具有唯一稳定 code、名称、说明、项目范围和不可变 Runtime kind 的 Agent 定义。
- 创建 Agent 时原子生成初始 Draft revision，但不自动校验、发布、绑定业务应用或改变运行路由。
- 在 Agent 配置列表增加明确空状态、“新建 Agent”按钮和创建表单，可选择 Python 或 TypeScript Runtime；创建成功后进入详情配置流程。
- 删除“仅允许编辑默认 Agent、不得新建”的旧限制，并明确 Agent code 与 Runtime kind 创建后不可修改。
- 为初始化、权限拒绝、重复 code、并发创建、两种 Runtime 和前端交互增加回归测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-model`: 扩展 Agent Profile 管理与多 Runtime 定义要求，允许受权管理员创建 Agent，并要求空库幂等初始化固定的 Python/TypeScript 默认 Agent。

## Impact

- 数据库迁移或 bootstrap：默认 Agent 定义和初始 Draft 的幂等初始化。
- 后端 `agent_config` repository、service、controller、授权与审计契约。
- 前端 Agent Profile API、query hooks、列表空状态和创建表单。
- 后端/前端测试、OpenAPI 契约及 Compose 空库恢复验证。
