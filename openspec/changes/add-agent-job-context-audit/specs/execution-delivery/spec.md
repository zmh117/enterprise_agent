## MODIFIED Requirements

### Requirement: Agent Job 运行审计必须保持执行事实与完整上下文快照的边界
系统 SHALL 继续以 `agent_job_execution_summary`、`agent_model_call`、`agent_tool_call`、`mcp_operation_audit` 和 Delivery 事实分别承担可筛选执行、模型轮次、安全工具、MCP 与投递主账，并 MUST 为 Runtime protocol v1.5 的每个 invocation 保存一份完整上下文/runtime I/O 快照。完整快照不得替代或反向修改这些主账；相同 invocation 的恢复重放必须幂等。

#### Scenario: Agent 成功而 Delivery 失败
- **WHEN** Runtime invocation 成功并保存完整审计，但后续 Delivery 失败
- **THEN** 执行审计保持成功，Delivery 独立显示失败

#### Scenario: Job retry
- **WHEN** 同一 Job 产生多个 invocation
- **THEN** 每个 invocation 独立保存完整审计，Job 执行汇总继续按唯一 terminal 重算
