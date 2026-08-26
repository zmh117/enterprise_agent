## Why

当前 `ones-mcp` 只提供有界关键字工作项查询和项目角色成员查询，且工作项查询仍依赖仓库自定义 GraphQL 端点，无法表达真实 ONES 中按项目、迭代、工作项详情、时间线、人员和测试资产进行查询的基础能力。现有本地接口抓取已经提供这些只读 Provider 契约，适合在不引入任意 GraphQL/HTTP 执行器的前提下补齐固定业务查询接口。

## What Changes

- 为真实 ONES GraphQL 查询增加代码拥有的固定文档、固定 `t` 查询类型、Team 路径模板、变量构造和有界响应解析；所有 `.graphql` 文档集中存放，Tool 输入不得提供 GraphQL、URL、Header、Token、Team 或任意查询参数。
- 为迭代列表、工作项时间线、Team 人员搜索等非 GraphQL 接口增加精确 REST Operation，保留现有项目角色成员的两步 REST 查询。
- 增加项目、迭代、工作项类型、工作项查询/详情/时间线、Team 人员以及测试库/路径/计划/用例等只读业务 MCP Tool，并将其加入代码 Manifest、发布和 Job 冻结链路。
- 保留现有 `ones_work_item_search` Tool 的 Schema 兼容性，并把它映射到真实 ONES 工作项查询契约，避免已发布配置因无必要的 Schema 变化而漂移。
- 扩展独立 ONES Mock，使其使用合成数据精确模拟新增请求方法、路径、固定查询类型、分页和有界响应；真实抓取中的人员、消息、附件、标识和认证材料不得进入代码、测试或审计。
- 本 change 不增加统计口径、统计聚合 Tool、Agent Skill、写接口、任意查询执行器或真实 ONES 凭据管理能力。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `builtin-tool-resource`: 增加代码拥有、只读、有界且可组合的 ONES 基础查询 Tool 与真实 GraphQL/REST Provider 契约要求。

## Impact

- `services/ones_mcp_server/`：Provider HTTP、GraphQL documents/operations、REST operations、Tool services、registry 和 contracts。
- `backend/app/modules/mcp_tool_runtime/manifest.py` 及相关发布、授权、Runtime 测试：新增稳定 Tool identifier 和输入 Schema。
- `ones_mock/`：使用仓库合成 fixture 扩展真实形状的 GraphQL/REST Mock，不提交 `ones_mock/ones/` 的真实抓取内容。
- `backend/tests/`：补齐 Provider、Tool、Manifest、权限、审计、Runtime 与 Mock 回归测试。
- 不改变现有 Principal JWT、外部身份、Credential refresh、Publication/Application/Job 冻结和只读安全边界。
