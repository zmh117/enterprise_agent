## Why

当前平台只有受治理的只读业务 MCP，尚不能让 Agent 安全地创建钉钉待办，也没有可复用的“模型提出外部写操作、用户确认后再执行”生命周期。若直接把钉钉或后续 ONES 修改接口暴露给模型，将绕过当前发布快照、身份复核、幂等、审计与用户意图边界。

## What Changes

- 新增部署固定、代码 Manifest 拥有的 `dingtalk-mcp`，MVP 只提供 `dingtalk_create_todo`；服务复用 Business Principal JWT、Job/Publication/Tool/RBAC 实时复核和统一 MCP 审计。
- 新增通用外部操作意图与执行状态机。非只读业务 Tool 首次调用只持久化不可变操作参数和确认意图，不得直接访问 Provider；只有原始发起人在钉钉确认卡片上同意当前 revision 后才进入异步执行。
- 使用已发布模板 `0ad7c643-7e30-4797-8284-da5ef89d3841.schema` 投放不可转发的单人确认卡；`outTrackId` 与操作意图一一对应，并通过现有 `dingtalk-runtime` 的唯一 Stream Client 接收卡片回调。
- 新增有租约、可恢复、幂等的卡片投放与操作执行 worker；成功、失败、拒绝和重复点击都写入持久状态与有界审计，并更新原卡片。
- 修改业务 Tool 治理规则：只读 Tool 继续按现有路径执行；任何声明为 mutation 的业务 MCP Tool 必须绑定平台确认策略。没有确认策略、确认已过期、点击人不匹配、revision 不匹配或 Tool/schema 漂移时失败关闭。
- ONES 本轮不新增修改 Tool；后续 ONES 创建、更新、评论、状态变更等接口必须复用同一确认生命周期，不得在 `ones-mcp` 内自建旁路确认或直接执行。
- 制定后续升级计划，覆盖更多钉钉只读能力、待办更新/完成、文档与聊天、修订再生成、用户 OAuth、多企业路由、共享 Token 缓存和 ONES mutation 接入。

## Capabilities

### New Capabilities

- `governed-external-action-confirmation`: 定义外部写操作意图、卡片确认、幂等执行、状态更新、审计以及 Provider mutation 的统一失败关闭边界。
- `dingtalk-mcp`: 定义部署固定的钉钉业务 MCP、MVP 创建本人待办 Tool、当前用户/企业身份解析和钉钉 Provider 合同。

### Modified Capabilities

- `identity-access`: 允许固定业务 MCP 按当前 Job 主体解析钉钉外部身份，并要求 mutation 的确认 actor 与原始 Job 用户一致。
- `business-application`: 允许 Application/Agent Publication 显式冻结代码注册的 mutation Tool，并把确认策略作为发布与运行时就绪条件。
- `channel-conversation`: 扩展唯一 `dingtalk-runtime` Stream 连接以接收、持久转交和 ACK 互动卡片回调。
- `execution-delivery`: 新增卡片投放、确认后的外部操作执行、租约恢复、幂等与结果卡片更新链。
- `builtin-tool-resource`: 将“角色授权中心一律排除非只读 Tool”收敛为“内置基础设施 Tool 仍只读，代码注册的业务 mutation Tool 只有在强制确认策略下才可授权”。
- `platform-operations`: 将 `dingtalk-mcp` 与外部操作 worker 纳入固定 Compose 拓扑、健康检查和 Secret 隔离。

## Impact

- 影响 `services/dingtalk_mcp_server/`、业务 MCP 公共 Principal/Tool 合同、代码 Tool Manifest、`dingtalk-runtime`、API 控制面、数据库 migration、后台 worker、Compose 与相关测试。
- 使用现有钉钉企业 App Connector 的平台 Secret 和当前用户 `user_external_identity.union_id`；Secret、Access Token、Principal JWT 和原始回调载荷不得进入 Job、Tool 参数、卡片参数、日志或审计。
- MVP 需要钉钉应用具备 `Todo.Todo.Write` 与互动卡片权限，并要求创建卡片和监听回调使用同一 Client ID；同一 Client ID 仍只允许一个受租约保护的 Stream Client。
