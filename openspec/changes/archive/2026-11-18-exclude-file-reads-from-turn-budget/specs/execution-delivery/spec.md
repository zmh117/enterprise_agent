## MODIFIED Requirements

### Requirement: Execution is bounded by turns and wall-clock time
系统 SHALL 使用 Job 固定的有效执行策略限制真实 Claude Agent 执行的任务计入预算的轮次、单次 attempt 墙钟时间和内部工具调用次数；有效范围为 max_turns 1–100、timeout_seconds 10–3600、max_tool_calls 0–500。所有进入 Worker 的 Job MUST 具有合法的当前 Execution Policy 快照；Worker MUST NOT 对缺失或不支持的策略使用 `AGENT_MAX_TURNS`、`AGENT_TIMEOUT_SECONDS` 或 Agent Publication 进行运行时 fallback。Runtime MUST 将工具调用次数与墙钟耗尽作为当前 attempt 的强制终止边界，而不是仅向模型返回可继续执行的普通拒绝或把本地预算耗尽误分类为瞬时传输故障。

#### Scenario: Execution exceeds configured timeout
- **WHEN** Runtime 自身的墙钟监视器确认 SDK session 超过 Job 有效 `timeout_seconds`
- **THEN** Runtime 取消当前 session，保留已有安全工具事件并返回稳定的 `runtime_timeout` 安全错误
- **AND** Worker 不为该错误安排自动重试，把 Job 转为 `TIMEOUT`

#### Scenario: Execution reaches maximum turns
- **WHEN** 当前 attempt 超过 Job 有效 `max_turns` 个计入预算的轮次且没有有效最终结果
- **THEN** 运行时以 `max_turns_exhausted` / `NEVER` 结束执行
- **AND** Worker 不为该错误安排自动重试

#### Scenario: Execution reaches maximum tool calls
- **WHEN** 当前 Agent attempt 的统一权限守卫已经接收 Job 有效 `max_tool_calls` 次内部工具请求，并收到下一次工具请求
- **THEN** Runtime 在该请求进入受治理工具实现 或产生文件工具副作用前以硬中断拒绝该请求
- **AND** 当前 attempt 以稳定、非瞬时的 `execution_policy_max_tool_calls_exhausted` 结束，不再执行后续模型轮次或工具请求
- **AND** Runtime 保留终止前已有的安全工具事件，执行策略证据记录 `exhausted=true`

#### Scenario: Zero tool-call budget rejects the first request
- **WHEN** Job 有效 `max_tool_calls` 为 `0` 且模型发起首次内部工具请求
- **THEN** Runtime 在调用受治理工具实现 或文件工具副作用路径前以 `execution_policy_max_tool_calls_exhausted` 终止当前 attempt

#### Scenario: Job缺少执行策略
- **WHEN** Job 没有 Execution Policy 快照、schema version 不受支持或有效字段不完整
- **THEN** Worker 在调用 Claude SDK 前以不可重试的完整性错误停止
- **AND** 不调用模型或任何内部工具

#### Scenario: 原生只读文件工具免计轮次
- **WHEN** 同一模型响应仅请求冻结可用集合内的原生 Grep、Glob、Read（含失败或拒绝结果）
- **THEN** 该响应免计任务轮次，但所有工具请求仍完整审计并消耗统一工具总预算
- **AND** 实际模型调用、Token 与耗时不得因免计而删减

#### Scenario: 分块和混合工具计入预算
- **WHEN** 一个模型响应拆成多个相同 message_id 的分块，且包含其他工具
- **THEN** 合并后只计入预算一轮，不能按分块或工具数多计，也不能因包含 Read 而整轮免计
- **AND** 无工具的模型响应（含最终答复）仍计入预算一轮；无法确认身份时不得授予免计

#### Scenario: 预算在工具执行前生效
- **WHEN** SDK 工具前置回调先于 Runtime 处理对应模型分块，或当前响应已超出计入预算预算
- **THEN** Runtime 等待有界的 tool_use_id 关联结果；超限或无法核实时在实现执行前停止，不能放行未知工具
- **AND** 所有文件工具请求均受统一工具总上限约束，包括 SDK 自动批准的原生读取

#### Scenario: SDK 有限兜底与独立统计
- **WHEN** 任务可用集合包含原生 Grep、Glob、Read
- **THEN** Runtime 使用宿主计入预算预算，并将 SDK 兜底轮次限制为 max_turns + max_tool_calls
- **AND** 安全运行审计分别保存观测轮次、计入预算的轮次、免计轮次、未结束轮次和 SDK 兜底上限，不保存源码正文
- **AND** 无文件工具的任务和连接 probe 不增加 SDK 上限；超时、取消和总工具上限独立生效
