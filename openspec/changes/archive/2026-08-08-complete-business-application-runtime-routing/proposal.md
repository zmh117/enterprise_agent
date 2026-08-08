## Why

业务应用控制面已经能够创建草稿、发布和激活，Channel 入口也已经存在一条非完整的可选解析路径，但管理 API 仍将 `runtime_wired` 固定返回为 `false`，且 Agent Job 没有保存业务应用归属、Delivery 与 Execution Policy 也未完整执行。这种“页面宣称未接线、运行代码可能在路由匹配时部分生效”的状态会让激活操作的实际影响不可预测，因此必须先收敛为可解释、可审计、可回退的正式运行时路由。

## What Changes

- 正式定义业务应用运行时接管状态，删除硬编码 `runtime_wired=false`，由服务端按部署闸门、环境 deployment、活动 trigger route 和已支持策略计算并返回真实状态。
- 第一阶段只正式接管钉钉 Stream 私聊和群聊；Webhook、Workflow 执行、API Capability 和任意自定义入口继续保持未接管，并在 API 与页面明确展示。
- 为钉钉私聊定义稳定的应用级路由键，按受信 connector 与 bot/robot identity 匹配，不要求为每个用户会话创建 route；群聊按 connector 与 conversation ID 显式匹配。
- 钉钉消息必须命中 `local` 的活动业务应用 route；未命中或命中后配置缺失、版本/hash 错误、策略不支持时均 fail closed，不创建 Job 或发布 MQ，并向原会话返回安全配置错误。
- 明确业务应用路由的优先级：命中的不可变 Application Publication 固定 Agent Publication 和已支持的 Session Policy；入口不得用另一个隐式 Agent 配置覆盖已命中的应用。
- 将 Business Application、Application Publication、deployment、route 和解析结果持久化到 Agent Job 与审计记录，使运行记录能够回答“本次消息由哪个应用版本处理”。
- 将业务应用 Delivery Binding 接入钉钉“回复原会话”路径并执行 connector/目标一致性校验；未支持的 delivery 类型阻止激活或运行，不伪装成已生效。
- 对 Execution Policy、Workflow、Capability 等尚未接线字段返回逐项生效状态；第一阶段不得把未执行的配置显示为已接管。
- 在激活、回退和停用页面展示将受影响的钉钉入口、真实接管状态与未命中失败行为，并保留基于历史 publication 的显式回退。
- 增加私聊、群聊、无匹配失败关闭、命中后失败关闭、发布版本固定、幂等、身份/RBAC、Job provenance、最终回复和历史回退的完整测试。

## Capabilities

### New Capabilities

- `business-application-runtime-routing`: 定义业务应用从活动路由解析、真实接管状态、发布版本固定、失败关闭到运行审计的完整运行时契约。

### Modified Capabilities

- `channel-ingress-contract`: Channel event 在创建 Agent Job 前增加业务应用解析、明确的路由优先级以及“未命中和命中异常均失败关闭”语义。
- `dingtalk-stream-ingress`: 钉钉私聊和群聊增加稳定且不同的业务应用路由键，并在接管后保持身份、幂等和快速 ACK 行为。
- `agent-job-lifecycle`: Agent Job 增加业务应用、发布版本、deployment 和 route provenance，且这些事实在入队前持久化。
- `result-delivery-routing`: 命中业务应用后，钉钉结果投递必须受已发布 Delivery Binding 约束并继续保持投递失败不重跑 Agent。

## Impact

- 后端：Business Application Resolver/Service/API、Channel ingress、DingTalk Stream adapter、CreateAgentJobService、Job Repository/DTO、Delivery 路由、审计和数据库迁移。
- 前端：业务应用列表、详情、发布/激活确认、接管状态和运行 provenance 展示。
- 配置：复用现有 `FEATURE_PUBLISHED_AGENT_RUNTIME` 数据面闸门，不新增面向部署者的功能开关；Business Application Deployment 只允许 `local`，并收敛钉钉 bot/robot identity 来源。
- 数据：新增 Agent Job 业务应用 provenance 字段和必要索引；现有 Job 保持空值兼容，不回填猜测归属。
- 运行边界：本变更只接管钉钉 Stream 私聊和群聊；现有 Webhook 路径保持原状。
- 前置关系：依赖已完成的 `add-business-application-control-plane-foundation`、统一身份/RBAC、已发布 Agent Runtime 和钉钉失败通知能力。
