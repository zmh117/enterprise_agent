## Why

现有 ONES MCP 已能按项目、迭代、事项类型、状态、处理人和时间查询工作项，但 Agent 不能把中文自定义选项稳定转换为受支持的筛选参数，也缺少按明确用户 UUID 批量取得安全用户摘要的独立能力。用户已经提供当前个人 ONES 身份在一个 Team 下采集并整理的查询条件字典及真实“查用户”接口契约，需要在不传播凭据、个人详情或跨身份静态授权事实的前提下补齐查询链路。

## What Changes

- 新增 `ones_query_work_items_with_custom_options`，在不改变既有 `ones_query_work_items` 契约与 schema hash 的前提下提供有界自定义选项筛选；只接受字段 UUID 与选项 UUID，MCP 在当前 Principal Team 的受管字典中校验后，才转换为固定 GraphQL `filterGroup` 条件。
- 新增只读 `ones_resolve_query_conditions`，按中文或显示名解析当前受管快照中的状态和自定义选项候选；该接口不访问任意 Provider 路径，也不返回整份字典。
- 新增只读 `ones_get_users_by_uuids`，复用固定 REST `POST /project/api/project/team/{team_uuid}/users`，只返回用户 UUID 和姓名。
- 从被忽略的个人抓取字典生成可审查、可版本化的最小运行快照；只保留状态和自定义选项，不复制人员、项目、迭代、原始响应、Token、Cookie、邮箱、手机号或部门信息，并按来源 Team 失败关闭。
- 新增可发布的 `ones-query` Agent Skill，指导 Agent 把复杂自然语言查询拆为实时实体发现、受管条件解析、工作项查询和用户定义的统计步骤；Skill 不包含真实 UUID 字典或固定统计公式。
- 扩展合成 ONES Mock、共享 Tool Manifest、架构测试和运行测试，保持 GraphQL 文档集中管理、REST/本地资源边界明确、只读与有界响应不变。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `builtin-tool-resource`: 扩展身份感知 ONES 只读工具，增加受管查询条件解析、受校验的自定义选项筛选和按 UUID 查询用户摘要。
- `agent-model`: 增加可选择并冻结进 Agent Publication 的基础 ONES 查询编排 Skill。

## Impact

- 影响 `services/ones_mcp_server/` 的 Tool 注册、参数校验、固定 GraphQL 变量构造、固定 REST 操作和受管字典资源。
- 影响 `backend/app/shared/ones_tool_contracts.py`、平台 MCP Tool Manifest、Agent Skill 注册和 `.claude/skills/` 运行时内容。
- 影响 `ones_mock/` 的合成响应及 ONES MCP 契约、架构、Mock 和 Runtime 测试。
- 不新增数据库表、Secret 类型、任意 GraphQL/REST 执行器或写入 ONES 的能力；既有已发布 Agent/Application/Job 仍需通过新的显式 Publication 才能获得新增 Tool 与 Skill。
