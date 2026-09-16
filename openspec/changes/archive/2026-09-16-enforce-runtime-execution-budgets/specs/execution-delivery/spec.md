## MODIFIED Requirements

### Requirement: Execution is bounded by turns and wall-clock time
系统 SHALL 使用 Job 固定的有效执行策略限制真实 Claude Agent 执行的 SDK 最大轮次、单次 attempt 墙钟时间和内部工具调用次数。所有进入 Worker 的 Job MUST 具有合法的当前 Execution Policy 快照；Worker MUST NOT 对缺失或不支持的策略使用 `AGENT_MAX_TURNS`、`AGENT_TIMEOUT_SECONDS` 或 Agent Publication 进行运行时 fallback。Runtime MUST 将工具调用次数与墙钟耗尽作为当前 attempt 的强制终止边界，而不是仅向模型返回可继续执行的普通拒绝或把本地预算耗尽误分类为瞬时传输故障。

#### Scenario: Execution exceeds configured timeout
- **WHEN** Runtime 自身的墙钟监视器确认 SDK session 超过 Job 有效 `timeout_seconds`
- **THEN** Runtime 取消当前 session，保留已有安全工具事件并返回稳定的 `runtime_timeout` 安全错误
- **AND** Worker 不为该错误安排自动重试，把 Job 转为 `TIMEOUT`

#### Scenario: Execution reaches maximum turns
- **WHEN** SDK session 达到 Job 有效 `max_turns` 且没有有效最终结果
- **THEN** 运行时按最大轮次耗尽分类结束执行
- **AND** 不把该错误仅作为普通 transport transient 立即重试

#### Scenario: Execution reaches maximum tool calls
- **WHEN** 当前 Agent attempt 的统一权限守卫已经接收 Job 有效 `max_tool_calls` 次内部工具请求，并收到下一次工具请求
- **THEN** Runtime 在该请求进入 ToolRegistry 或产生文件工具副作用前以硬中断拒绝该请求
- **AND** 当前 attempt 以稳定、非瞬时的 `execution_policy_max_tool_calls_exhausted` 结束，不再执行后续模型轮次或工具请求
- **AND** Runtime 保留终止前已有的安全工具事件，执行策略证据记录 `exhausted=true`

#### Scenario: Zero tool-call budget rejects the first request
- **WHEN** Job 有效 `max_tool_calls` 为 `0` 且模型发起首次内部工具请求
- **THEN** Runtime 在调用 ToolRegistry 或文件工具副作用路径前以 `execution_policy_max_tool_calls_exhausted` 终止当前 attempt

#### Scenario: Job缺少执行策略
- **WHEN** Job 没有 Execution Policy 快照、schema version 不受支持或有效字段不完整
- **THEN** Worker 在调用 Claude SDK 前以不可重试的完整性错误停止
- **AND** 不调用模型或任何内部工具

### Requirement: SDK failures are classified for retry policy
系统 SHALL 根据结构化语义分类 Claude Agent SDK/CLI 故障：网络、429/5xx、transport、CLI JSON decode 和可确认的瞬时 provider 故障映射为可重试；缺少凭据、CLI 不存在、明确无效模型配置、工具策略拒绝和 Runtime 自身 Job 墙钟预算耗尽映射为不可重试；矛盾的 error result MUST 使用独立错误码并只允许受最大次数约束的有限重试。错误分类 MUST 使用稳定错误码和协议 retry class，不得依赖用户可见消息文本。

#### Scenario: Transient process error triggers retry
- **WHEN** SDK 返回网络、rate limit、overloaded、transport 或 CLI JSON decode 瞬时错误
- **THEN** runtime 抛出带稳定错误码的 `RetryableExecutionError`，由 Job retry service 延迟调度

#### Scenario: Local runtime timeout does not retry
- **WHEN** Runtime 自身 Job 墙钟监视器达到冻结的 `timeout_seconds`
- **THEN** Runtime 使用 `runtime_timeout` 和非瞬时 retry class 返回失败，Worker 不创建 retry dispatch
- **AND** Job 进入 `TIMEOUT`，已有安全工具事件和执行证据继续持久化

#### Scenario: SDK reports contradictory success error
- **WHEN** SDK/CLI 返回 `is_error=true`，但 errors 为空且 subtype 为 `success`，或抛出等价的 `Claude Code returned an error result: success`
- **THEN** runtime 不把该结果作为最终答案，映射为 `claude_inconsistent_result`，生成用户可理解的安全消息，并在最大重试次数内有限重试

#### Scenario: Contradictory result exhausts retries
- **WHEN** 同一 Job 持续收到 `claude_inconsistent_result` 并达到最大重试次数
- **THEN** Job 进入终态失败，不再调用模型，并通过原 reply route 发送一次安全失败通知

#### Scenario: Configuration failure does not retry
- **WHEN** runtime 确认缺少凭据、CLI runtime 不存在或模型配置明确无效
- **THEN** runtime 返回不可重试配置错误，不进入延迟 retry queue

#### Scenario: Policy violation does not retry as transport error
- **WHEN** 工具调用因为 SQL policy、只读边界、权限拒绝或 `max_tool_calls` 耗尽而停止
- **THEN** runtime 将安全拒绝结果返回模型或终止本次执行，不将其误分类为 SDK transport retry
