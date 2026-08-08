## Why

业务应用已经接管钉钉路由、固定 Agent Publication 并回复原会话，但应用页面配置的 `max_turns`、`timeout_seconds` 和 `max_tool_calls` 仍只保存、未约束实际 Job，导致管理员看到的执行策略与真实运行不一致。与此同时，`retention_days` 这类后台数据治理缺口会把同步消息链路显示为“部分接管”，容易被误解为只处理了一部分消息。

## What Changes

- 将业务应用 Publication 中的 Execution Policy 固定到新建 Agent Job，并保证已入队 Job 不受后续发布、激活或回退影响。
- **BREAKING**：不兼容迁移前的旧 Agent Job；实施时删除没有 v1 Execution Policy 快照的旧 Job 及其关联运行数据，不提供旧 Job fallback。
- 要求迁移后的每个新 Agent Job 都持久化规范化 v1 Execution Policy；业务应用、普通 Agent、调试入口等不同来源只影响策略来源，不允许产生空策略 Job。
- 结合业务应用策略、固定 Agent Publication 和系统默认值计算可审计的有效执行策略；业务应用只能收紧 Agent 限制，不能扩大其允许范围。
- 在真实与 Stub Agent 执行链中强制执行 `max_turns`、`timeout_seconds` 和 `max_tool_calls`，并为策略耗尽提供稳定错误码、安全钉钉失败回复和完整工具事件审计。
- 更新运行时就绪判定：Execution Policy 三个字段全部由 Worker 强制执行后标记为 `wired`；同步接管状态只由消息执行关键路径决定。
- `retention_days` 继续逐字段标记为 `stored_only` 并在管理端显示治理提示，但作为非阻塞后台治理缺口，不再单独把同步消息接管状态降为 `partially_wired`。
- 保留 Workflow Publication、未支持 Trigger/Delivery 和其他已声明但未执行的同步能力对 `partially_wired`、`blocked` 或 `unsupported` 的现有影响。
- 明确不增加 `retention_days` 清理 Worker、定时任务、消息删除、附件删除或审计数据清理。

## Capabilities

### New Capabilities

- `business-application-execution-policy`: 规定业务应用执行策略的不可变快照、有效值计算、Worker 强制执行、策略耗尽语义、审计和运行时就绪状态。

### Modified Capabilities

- `agent-job-lifecycle`: Agent Job 需要持久化固定的业务应用执行策略及其来源，并在重试和历史查询中保持不变。
- `claude-agent-runtime-integration`: Agent 运行时除现有默认限制外，还需要执行 Job 固定的最大轮次、墙钟超时和工具调用次数限制。

## Impact

- 后端领域与应用层：Business Application 路由解析、Job 创建、Job 模型、会话/执行上下文构建、Agent Executor、失败分类和运行时就绪评估。
- 后端基础设施：`agent_job` 非空策略快照迁移、旧运行数据及附件对象清理、PostgreSQL 仓储、真实 Claude SDK 工具桥接、Stub runtime 和运行记录查询投影。
- 管理 API 与 Web：逐字段策略状态、请求值与有效值、非阻塞治理缺口以及“已接管/部分接管”文案。
- 测试与运行验证：领域单测、仓储迁移测试、Worker/Claude fake 集成测试、工具调用上限测试、钉钉失败投递测试和 Docker Compose 闭环。
- 不新增中间件，不新增清理队列，不改变 RabbitMQ 消息仍只传递 `job_id`/`correlation_id` 的边界。
- 数据影响：删除迁移前测试环境中的 Agent session、Job 及相关消息、步骤、工具调用、产物、投递、附件、关联 Webhook 运行事件和 Job 级审计；保留用户、外部身份、RBAC、Agent 配置、业务应用、Publication、Deployment、Connector 和 Secret 等控制面配置。
