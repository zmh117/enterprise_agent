## Why

当前运行中心能够查看 Agent Job 状态、步骤、工具调用和投递证据，但缺少模型轮次耗时、Token、估算成本和稳定失败阶段，无法支持运行优化与故障定位。继续向字段已较多的 `agent_job` 增加统计列会混淆生命周期事实与可重算的执行投影，因此需要在不引入 OpenTelemetry 或新基础设施的前提下建立清晰的数据边界。

## What Changes

- 复用 Claude Agent SDK 消息流和现有版本化 Runtime event 协议，投影模型初始化、模型轮次、API 重试和 ResultMessage 终态汇总；不引入 OTel Collector、Tempo、audit-ingestor、Trace 上下文传播或新的外部可观测服务。
- 新增与 `agent_job` 一对一的执行汇总事实，保存模型调用数、重试数、总耗时、API 总耗时、四类 Token、按模型汇总的 usage、估算成本和稳定失败位置；`agent_job` 不新增运行统计字段。
- 新增与 Job/Invocation 关联的模型轮次事实，保存 SDK 可观察到的模型、request ID、完成时间、Token、停止原因、重试和安全错误；页面必须将其耗时标记为“SDK 观测”，不得宣称为 Provider HTTP 精确 Span。
- 以 `invocation_id + request_digest` 和 Runtime 单调 sequence 保证恢复、重复消费和终态重放不会重复累计 Token、成本、模型轮次或重试。
- 复用 `agent_tool_call`、`mcp_operation_audit`、`audit_event` 和 `delivery_attempt` 展示工具、MCP 业务证据、Job 阶段和投递结果，不复制完整业务载荷或建立第二套工具审计主账。
- 增加确定性的失败阶段归类，至少区分 Runtime 启动、Runtime 协议、MCP 连接、模型 API、工具权限、工具执行、Job 重试耗尽和结果投递，并保持 Agent 执行状态与 Delivery 状态相互独立。
- 扩展受授权保护的管理端运行记录列表、详情 API 和页面，展示用户、Agent、执行/投递状态、总耗时、模型轮次、Token、估算成本、工具摘要和失败位置。
- 所有新增持久化和查询继续排除完整 Prompt、原始 SDK 消息、模型完整回复、Provider/MCP 原始载荷、private thinking 和认证材料；错误仅保存稳定分类和有界安全摘要。
- **BREAKING**：Runtime 事件与终态协议将使用新的受支持 minor version 增加模型轮次和 ResultMessage 汇总字段；Worker 必须先支持旧版和新版协议，新 Runtime 与新 Agent Publication 按受控顺序切换。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `execution-delivery`：增加 Agent 执行汇总、模型轮次、失败定位、幂等聚合和运行记录页面的规范要求，并明确 Job 生命周期主表与运行审计投影的职责边界。

## Impact

- Runtime：TypeScript/Python Claude Agent SDK 消息归一化、版本化事件 schema、终态恢复账本和双版本协议兼容。
- Worker/Domain：`AgentRunResult`、异常诊断、终态汇总持久化、失败阶段分类和重放幂等处理。
- PostgreSQL：新增 `agent_job_execution_summary`、`agent_model_call`、索引、外键、约束、保留策略和 Schema fact-source 登记；不向 `agent_job` 增加统计字段。
- 审计事实：只读复用 `agent_tool_call`、`mcp_operation_audit`、`audit_event` 和 `delivery_attempt`，不改变其既有治理和保留边界。
- API/Web：运行记录列表、Job evidence/detail 投影、模型轮次查询、筛选与详情展示；继续复用当前登录、应用运维权限和平台管理员授权。
- 部署：无需新增容器或外部依赖；需按 Worker 双读、Runtime 升级、Publication 切换的顺序发布。
- 验证：双 Runtime 合约、成功/失败 ResultMessage、API retry、模型轮次、Job retry、终态恢复、重复消费、工具/MCP/Delivery 证据、RBAC 和 Secret 泄漏回归。
