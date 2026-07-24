## MODIFIED Requirements

### Requirement: Execution is bounded by turns and wall-clock time
系统 SHALL 使用 Job 固定的有效执行策略限制真实 Claude Agent 执行的 SDK 最大轮次、单次 attempt 墙钟时间和内部工具调用次数。所有进入 Worker 的 Job MUST 具有合法的当前 Execution Policy 快照；Worker MUST NOT 对缺失或不支持的策略使用 `AGENT_MAX_TURNS`、`AGENT_TIMEOUT_SECONDS` 或 Agent Publication 进行运行时 fallback。

#### Scenario: Execution exceeds configured timeout
- **WHEN** SDK session 超过 Job 有效 `timeout_seconds`
- **THEN** 运行时取消当前 session，保留已有安全工具事件并抛出安全 timeout 错误

#### Scenario: Execution reaches maximum turns
- **WHEN** SDK session 达到 Job 有效 `max_turns` 且没有有效最终结果
- **THEN** 运行时按最大轮次耗尽分类结束执行
- **AND** 不把该错误仅作为普通 transport transient 立即重试

#### Scenario: Execution reaches maximum tool calls
- **WHEN** 当前 Agent attempt 已经执行 Job 有效 `max_tool_calls` 次内部工具调用
- **THEN** 内部 MCP 工具桥拒绝下一次调用且不进入 ToolRegistry
- **AND** 运行时返回稳定、非瞬时的策略耗尽错误并保留此前工具事件

#### Scenario: Job缺少执行策略
- **WHEN** Job 没有 Execution Policy 快照、schema version 不受支持或有效字段不完整
- **THEN** Worker 在调用 Claude SDK 前以不可重试的完整性错误停止
- **AND** 不调用模型或任何内部工具
