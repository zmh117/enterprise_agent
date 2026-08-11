# claude-agent-runtime-integration Specification

## Purpose
TBD - created by archiving change connect-real-claude-code-agent-runtime. Update Purpose after archive.
## Requirements
### Requirement: Real runtime is implemented with the Claude Agent SDK
The system SHALL implement `RealClaudeCodeAgentClient` using the Claude Agent SDK (`claude_agent_sdk`) entry points (`ClaudeSDKClient` or `query` with `ClaudeAgentOptions`) instead of calling the raw Anthropic Messages API. Only the infrastructure client module SHALL import the SDK.

#### Scenario: Real client drives an agent loop
- **WHEN** `RealClaudeCodeAgentClient.run()` executes a job with a valid API key and CLI available
- **THEN** it issues the diagnostic prompt through the Claude Agent SDK and consumes the SDK message stream until a final result message is produced

#### Scenario: SDK types do not leak into application layer
- **WHEN** `AgentExecutor` invokes the client
- **THEN** it receives an `AgentRunResult` and never imports or references `claude_agent_sdk` types

### Requirement: Real runtime is selectable via feature flag
The system SHALL select `RealClaudeCodeAgentClient` when `FEATURE_REAL_CLAUDE=true` and `StubClaudeCodeAgentClient` otherwise for API and worker runtime containers. Test runtime SHALL continue to use stub by default unless a test explicitly injects a fake client.

#### Scenario: Compose worker uses real runtime when enabled
- **WHEN** `agent-worker` starts with `FEATURE_REAL_CLAUDE=true` and a valid Anthropic API key
- **THEN** the worker container injects `RealClaudeCodeAgentClient` into `AgentExecutor`

#### Scenario: Local tests keep stub runtime
- **WHEN** unit tests build the test container without overriding the Claude client
- **THEN** `AgentExecutor` uses `StubClaudeCodeAgentClient` and does not require the SDK, an API key, or the CLI

### Requirement: Anthropic credentials and CLI runtime are validated before execution
The system SHALL read `ANTHROPIC_API_KEY` from environment configuration when real Claude runtime is enabled and MAY read optional `ANTHROPIC_BASE_URL`. The system SHALL surface a clear error when the SDK or its underlying Claude Code CLI runtime is unavailable.

#### Scenario: Missing API key fails fast
- **WHEN** `FEATURE_REAL_CLAUDE=true` and `ANTHROPIC_API_KEY` is empty
- **THEN** real Claude execution fails with a non-retryable configuration error and a safe user-facing message

#### Scenario: Missing CLI runtime is not retried indefinitely
- **WHEN** the Claude Agent SDK cannot locate its CLI runtime
- **THEN** execution fails with a non-retryable error rather than being re-queued as a transient failure

### Requirement: Read-only tools are exposed only through an in-process SDK MCP server
The system SHALL expose MVP internal read-only tools and governed external API QUERY Capabilities to the SDK through in-process SDK MCP servers registered via `ClaudeAgentOptions.mcp_servers`. Internal tools SHALL continue to execute through `ToolRegistry` with the current job context; governed Capabilities SHALL execute through the governed Capability resolver/executor with the frozen job, Agent Publication, Application Publication and subject context.

#### Scenario: Model calls a registered read-only tool
- **WHEN** Claude calls `mcp__internal__query_database` with valid read-only arguments
- **THEN** the runtime routes the call through `ToolRegistry` to `ReadOnlyToolService` and returns the tool result to the model

#### Scenario: Model calls a governed Capability
- **WHEN** Claude calls an exposed `cap__ones__work_item__search` with valid public input
- **THEN** the runtime routes the call through the governed Capability executor and not through an arbitrary web fetch or model-provided URL

#### Scenario: Tool context is bound per job
- **WHEN** two different jobs run through the real runtime
- **THEN** each job's internal and governed Tool invocations use that job's own identifiers, frozen publications and requester context and do not leak context between jobs

### Requirement: Built-in mutating tools are disabled
The system SHALL prevent the SDK's built-in mutating tools such as Bash, Write, Edit, file modification, deployment or web fetch from being available or approved. The system SHALL auto-approve only the exact internal read-only and governed `cap__*` QUERY tools resolved for the current Job; it SHALL deny all other tools through `allowed_tools`, `disallowed_tools`, `permission_mode`, or `can_use_tool`.

#### Scenario: Model attempts a built-in write tool
- **WHEN** the SDK runtime would otherwise allow a built-in Bash, Write, or Edit tool
- **THEN** the tool is not available or its call is denied, so no mutation can occur

#### Scenario: Only current governed set is auto-approved
- **WHEN** the Agent runs a Job whose Application Allowlist includes one Capability Release
- **THEN** only existing permitted internal tools and that exact resolved `cap__*` Tool are pre-approved, while other Capability names and generic web fetch remain denied

#### Scenario: Application has no Capability
- **WHEN** the frozen Application Capability Allowlist is empty
- **THEN** no `cap__*` Tool is registered or auto-approved and existing internal Tool behavior remains unchanged

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

### Requirement: SDK failures are classified for retry policy
系统 SHALL 根据结构化语义分类 Claude Agent SDK/CLI 故障：网络、429/5xx、transport、CLI JSON decode 和可确认的瞬时 provider 故障映射为可重试；缺少凭据、CLI 不存在、明确无效模型配置和工具策略拒绝映射为不可重试；矛盾的 error result MUST 使用独立错误码并只允许受最大次数约束的有限重试。

#### Scenario: Transient process error triggers retry
- **WHEN** SDK 返回网络、rate limit、overloaded、transport 或 CLI JSON decode 瞬时错误
- **THEN** runtime 抛出带稳定错误码的 `RetryableExecutionError`，由 Job retry service 延迟调度

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
- **WHEN** 工具调用因为 SQL policy、只读边界或权限被拒绝
- **THEN** runtime 将安全拒绝结果返回模型或终止本次执行，不将其误分类为 SDK transport retry

### Requirement: Async SDK is bridged into synchronous execution
The system SHALL bridge the asynchronous Claude Agent SDK into the synchronous `AgentExecutor` and worker without leaking event-loop management into application code.

#### Scenario: Synchronous executor runs async SDK
- **WHEN** the synchronous `AgentExecutor.execute()` calls `RealClaudeCodeAgentClient.run()`
- **THEN** the client manages its own event loop (e.g. `asyncio.run`) and returns a plain `AgentRunResult`

### Requirement: Tool events are returned without private reasoning
The system SHALL populate `AgentRunResult.tool_events` with safe summaries of each internal or governed Tool invocation, attempt outcome, result size and applicable Capability Release/classification provenance, excluding raw secrets, authentication material, raw HTTP bodies, full unbounded payloads and private model chain-of-thought including SDK thinking blocks.

#### Scenario: Successful tool loop produces events
- **WHEN** the real runtime completes after one or more internal or governed Tool calls
- **THEN** `AgentRunResult` includes ordered safe Tool event summaries suitable for persistence in `agent_tool_call`

#### Scenario: Governed call fails after HTTP attempts
- **WHEN** a QUERY Capability exhausts its allowed attempts
- **THEN** the event summary includes safe classification and attempt count without including external body, Token or authentication Header

### Requirement: Health endpoints report runtime mode without invoking Claude
The system SHALL expose whether real Claude is enabled, whether an API key is configured, and whether the SDK CLI runtime is detected, without making live Claude API calls during health or readiness checks.

#### Scenario: Ready check with stub mode
- **WHEN** `/api/ready` is called with `FEATURE_REAL_CLAUDE=false`
- **THEN** the response indicates Claude is not invoked and real runtime is disabled

#### Scenario: Ready check with missing key
- **WHEN** `/api/ready` is called with `FEATURE_REAL_CLAUDE=true` and no API key
- **THEN** the response reports real runtime enabled but not configured

### Requirement: 失败路径必须保留真实运行时工具事件
系统 SHALL 在真实 Claude SDK 执行失败、超时或达到最大轮次时，保留失败前已经发生的工具调用安全摘要，并将这些摘要交给应用层持久化。工具事件 MUST 不包含私有推理、密钥、未脱敏 raw payload 或不受限响应正文。

#### Scenario: 最大轮次耗尽后保留工具轨迹
- **WHEN** `RealClaudeCodeAgentClient.run()` 在一个已经调用过内部工具的 job 中收到 `Reached maximum number of turns` 类错误
- **THEN** 系统持久化失败前已收集的工具调用摘要，并在 job step 中记录安全失败原因

#### Scenario: SDK timeout 后保留工具轨迹
- **WHEN** 真实 SDK 会话超时且超时前已经调用过内部工具
- **THEN** 系统持久化已完成或已失败的工具调用摘要，并继续按 timeout 错误分类处理 job

### Requirement: 最大轮次耗尽必须区别于瞬时传输故障
系统 SHALL 将明确的工具循环最大轮次耗尽识别为诊断循环收敛失败，而不是普通网络、CLI transport 或上游 5xx 瞬时故障。该错误 MUST 带有安全错误码或等价分类，供 retry 策略避免立即重复消耗同一无效工具循环。

#### Scenario: 最大轮次耗尽不作为普通 transient 重试
- **WHEN** Claude SDK 返回明确的 `Reached maximum number of turns` 错误
- **THEN** job 不得仅因为该错误被当作普通 transient transport failure 立即重复重试

#### Scenario: 网络错误仍可重试
- **WHEN** Claude SDK 返回网络超时、429、502、503、transport connection 或 CLI JSON decode transient 错误
- **THEN** 系统仍按现有 retryable 语义处理该故障

### Requirement: Claude runtime can load model settings from DB-backed runtime config
系统 SHALL 允许真实 Claude/DeepSeek runtime 从 DB-backed runtime config 加载 base URL、model、默认模型、effort level、max turns 和 timeout，并保留 env fallback。

#### Scenario: DB config selects DeepSeek model
- **WHEN** runtime config 配置 `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic` 和 `ANTHROPIC_MODEL=deepseek-v4-pro[1m]`
- **THEN** RealClaudeCodeAgentClient 使用 DB-backed 配置构造 SDK runtime

#### Scenario: DB config missing
- **WHEN** DB-backed Claude runtime config 不存在
- **THEN** runtime 使用现有 env/default 逻辑，并在 ready 输出中标记来源

### Requirement: Claude runtime API key can use Web-managed secret
系统 SHALL 允许 `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` 通过 Web-managed secret ref 配置，并且 ready/health 只能报告是否 configured，不能泄漏 key。

#### Scenario: API key is stored as secret ref
- **WHEN** runtime config 将 `ANTHROPIC_API_KEY` 指向 `secret://platform/deepseek_api_key`
- **THEN** RealClaudeCodeAgentClient 仅在调用 SDK 前解析 secret，日志和 ready 输出不包含明文 key

#### Scenario: API key secret is missing
- **WHEN** `FEATURE_REAL_CLAUDE=true` 但 API key secret 无法解析
- **THEN** ready 或执行前校验返回安全配置错误，不调用外部模型 API

### Requirement: Claude runtime DB-backed settings shall be smoke-verifiable
系统 SHALL 提供 smoke 流程，验证 Claude/DeepSeek runtime 的 base URL、model、max turns 和 API key secret ref 可从 DB-backed runtime config 进入 `agent-worker`。

#### Scenario: Stub runtime validates config overlay without external API
- **WHEN** 默认 smoke 使用 `FEATURE_REAL_CLAUDE=false`
- **THEN** 流程 SHALL 仍能验证 DB-backed runtime config 被 `api-server` 和 `agent-worker` 读取，而不调用外部模型 API

#### Scenario: Optional real DeepSeek runtime uses secret ref
- **WHEN** 开发者显式启用 `FEATURE_REAL_CLAUDE=true` 并配置 `ANTHROPIC_API_KEY=secret://platform/deepseek_api_key`
- **THEN** `agent-worker` SHALL 在执行前通过 SecretResolver 解析 key，并且 ready/job/debug 输出 MUST 不包含明文 key

### Requirement: Real-model smoke shall fail safely when credentials are invalid
系统 SHALL 在真实 DeepSeek/Claude smoke 中，当 API key 缺失、禁用或仍为占位符时，返回安全配置错误并避免无限重试。

#### Scenario: API key secret is disabled before job execution
- **WHEN** `FEATURE_REAL_CLAUDE=true` 且 runtime config 指向 disabled secret
- **THEN** Agent job SHALL 失败为安全配置错误，且 debug API SHALL 提供可排查的 job/error 信息但不泄漏 key

### Requirement: Claude runtime consumes the job-fixed Agent publication
系统 SHALL 在执行 job 时读取 job 固定的不可变 Agent publication snapshot，并 MUST 使用其中的业务指令、模型策略、执行限制、Skill 和允许工具配置。runtime MUST NOT 读取活动草稿或执行时重新选择当前发布版本。

#### Scenario: Job executes published configuration
- **WHEN** worker 执行固定了默认诊断 Agent publication 的 job
- **THEN** AgentContextBuilder 和 RealClaudeCodeAgentClient 使用该 snapshot 构建运行上下文

#### Scenario: Publication changes during execution
- **WHEN** 管理员在 job 运行期间发布新版本
- **THEN** 当前 job 继续使用固定 snapshot，新版本不改变本次 prompt、工具或执行限制

### Requirement: 可编辑业务指令不能覆盖强制安全规则
系统 SHALL 把 publication 中的业务指令作为受控配置层，并 MUST 在其外层强制叠加平台安全规则、只读工具限制、数据权限和 SDK 内置写工具禁用。

#### Scenario: 业务指令包含越权文本
- **WHEN** 已发布业务指令要求忽略权限、执行 Bash、修改数据库或泄漏 secret
- **THEN** runtime 拒绝无效 publication 或保持平台安全规则优先，且不执行越权动作

### Requirement: Agent publication 只能引用已注册模型策略
系统 SHALL 允许 Agent publication 选择已注册且启用的模型策略与执行参数，但 MUST NOT 在 Agent snapshot 中保存 API key、认证 token、任意 secret 明文或不受管 provider URL。

#### Scenario: 默认 Agent 选择模型策略
- **WHEN** 管理员为默认 Agent 选择一个引用 DB-backed runtime config/secret 的模型策略
- **THEN** publication 保存非敏感策略引用，runtime 在基础设施层解析实际凭证

### Requirement: Claude 错误诊断元数据必须有界、脱敏且可关联
系统 SHALL 为真实 Claude/DeepSeek 失败记录可关联 Job 的安全诊断元数据，至少包括稳定错误码、异常类、SDK/CLI 版本、模型策略引用、provider host 安全摘要、脱敏 subtype/errors 和有界 stderr；系统 MUST NOT 持久化凭据、完整敏感 URL、完整 prompt、未受限工具结果或私有推理。

#### Scenario: Inconsistent SDK result is audited
- **WHEN** runtime 识别 `claude_inconsistent_result`
- **THEN** 审计记录 Job、correlation ID、SDK/CLI 版本、模型策略引用、脱敏错误标志和稳定错误码，不记录 API key、认证 token 或 chain-of-thought

#### Scenario: CLI stderr contains credentials
- **WHEN** CLI stderr 包含 API key、authorization header、token 或带 secret/query 的 URL
- **THEN** 系统在写入 Job step、error message 或审计前屏蔽凭据并截断到配置上限

### Requirement: 真实模型兼容性 smoke 必须显式启用且使用安全输入
系统 SHALL 提供显式 opt-in 的真实模型 smoke，用合成或已脱敏问题对照 provider/model/SDK 组合；常规单元测试、Compose 启动和 readiness MUST NOT 自动调用外部模型。

#### Scenario: 常规测试运行
- **WHEN** 开发者运行默认测试或启动 readiness
- **THEN** 系统使用 fake/stub 或仅报告配置状态，不产生外部模型请求和费用

#### Scenario: 开发者显式运行对照 smoke
- **WHEN** 开发者提供明确开关和凭据并选择当前 DeepSeek 配置与基线配置
- **THEN** smoke 使用 synthetic prompt，分别记录成功或安全错误分类，不输出凭据和完整 provider 响应

### Requirement: 真实Runtime必须使用Job固定的模型连接
系统 SHALL 让 `AgentExecutor` 和 `RealClaudeCodeAgentClient` 从 Job 固定的 Agent Publication 获取模型连接 revision、config hash、Base URL、模型映射、Subagent 模型、effort 和 Credential 绑定。Worker MUST NOT 为包含模型连接快照的新 Publication 重新读取 Agent 当前发布指针或用进程启动时的全局模型 URL、模型和 Key 覆盖该快照。

#### Scenario: Job排队后发布新模型连接
- **WHEN** Job 已固定 Agent Publication 后管理员发布使用不同 Base URL 或模型的新 Agent Publication
- **THEN** 已排队 Job 和其重试继续使用原固定模型连接 revision
- **AND** 新 Job 才使用新 Agent Publication 的模型连接

#### Scenario: Publication模型连接hash不匹配
- **WHEN** Worker 读取到的模型连接 revision 与 Agent Publication 固定的 config hash 不一致
- **THEN** Job 在调用 Claude Agent SDK 前以不可重试完整性错误失败
- **AND** 不解析 Key、不启动 CLI、不调用模型或工具

### Requirement: Runtime必须安全解析并隔离每次执行的模型环境
系统 MUST 在每次 Agent attempt 开始时解析固定模型连接绑定的 active Secret，并把规范化字段映射为 Claude Agent SDK/CLI 所需的 Anthropic Base URL、API Key/Auth Token、主模型、默认模型、Subagent 模型和 effort。不同 Job 的模型环境 MUST 隔离，MUST NOT 通过无保护的进程全局环境产生跨 Job URL、模型或 Key 串用。

#### Scenario: 两个Job使用不同模型连接
- **WHEN** 同一 Worker 先后或并发处理固定到不同模型连接的 Job
- **THEN** 每个 SDK session 只继承自己的 Base URL、模型映射、effort 和 Key
- **AND** 任一 Job 的配置不会残留到另一个 Job

#### Scenario: Active Key被轮换
- **WHEN** Job 已固定 Credential 绑定，但该 Credential 在 attempt 开始前完成安全轮换
- **THEN** Worker 使用新的 active Secret 版本
- **AND** Job 的 Base URL、模型映射和 Agent Publication provenance 保持不变

### Requirement: 旧Agent Publication保留受控兼容路径
系统 SHALL 允许迁移前没有模型连接 revision 的现有 Agent Publication 继续使用既有 DB-backed runtime config/env fallback，并 MUST 在管理 API 和 Web 将其标记为 legacy global connection。所有本变更实施后新建的 Agent Publication MUST 固定模型连接，不得继续创建新的隐式全局连接 Publication。

#### Scenario: 现有业务应用引用旧Publication
- **WHEN** 已激活 Business Application 仍引用迁移前 Agent Publication
- **THEN** Runtime 继续使用现有 DB-backed 全局模型配置执行该 Job
- **AND** 管理端提示需要重新发布 Agent 并在业务应用中显式切换

#### Scenario: 发布新Agent草稿
- **WHEN** 管理员在本变更上线后发布 Agent 草稿
- **THEN** 发布校验要求草稿引用有效模型连接 revision
- **AND** 缺失连接时不得退回全局配置创建新 Publication

### Requirement: 模型运行记录必须只展示安全Provenance
系统 SHALL 在 Agent Job、运行记录和安全诊断中保存 Agent Publication、模型连接 revision/config hash、模型、effort 和脱敏 Provider Host，并 MUST NOT 持久化 API Key、Auth Token、Secret ref、完整 Base URL 查询参数、Prompt 或模型原始响应。

#### Scenario: 查看成功Job
- **WHEN** 管理员查看由新 Agent Publication 执行成功的 Job
- **THEN** 运行记录展示模型、Provider Host、模型连接 revision 和 Agent Publication
- **AND** 不提供任何能够恢复 Credential 的字段

#### Scenario: Provider认证失败
- **WHEN** Claude Agent SDK 因 Key 无效返回认证错误
- **THEN** Job 记录稳定安全错误码和脱敏 Provider Host
- **AND** 日志、审计和原会话失败投递不包含 Key、请求头或上游响应正文

### Requirement: 模型可以组合公开的 Capability 输入输出
Claude Tool循环 SHALL 能读取一个受治理Capability的规范化公开输出，并依据后续Capability的公开Input Schema组织新的结构化调用；每次调用必须独立经过当前Job的Tool可见性与执行校验，运行时不得创建隐式服务端Handler流水线。

#### Scenario: 顺序调用两个测试 Capability
- **WHEN** 模型使用第一个Tool的规范化字段构造第二个Tool输入
- **THEN** SDK循环执行两个独立Tool调用并分别产生安全Tool事件

#### Scenario: 后续 Tool 不在当前目录
- **WHEN** 模型尝试根据文本调用未注册的 `cap__*` Tool
- **THEN** SDK权限策略拒绝该调用且不发起外部请求

### Requirement: 外部规范化文本不得提升为指令
运行时 MUST 将受治理 Capability 的字符串输出标记和封装为不可信业务数据，不得把它拼接进 system/developer/Tool定义或据此修改 `allowed_tools` 和权限策略。

#### Scenario: Tool 输出包含提示注入
- **WHEN** 外部字段内容声称自己是系统指令或要求调用被禁用Tool
- **THEN** 内容保持普通Tool数据，系统提示、Tool集合和权限不发生变化

### Requirement: 不可用 Capability 使用独立安全提示通道
运行时 MUST 将受治理 Capability 的调用资格与模型解释事实分离：不满足当前发送者 Provider 身份前置条件的 Capability MUST 保持未注册、未批准，同时 MAY 仅在该 Capability 已属于精确 Agent/Application 发布交集时，以固定白名单文案向模型说明当前 Job 的不可用状态。提示 MUST NOT 复用原始异常，不得包含用户、Team、Connection、Credential、Release 或认证材料，也不得被模型视为可调用 Tool。

#### Scenario: 当前发送者缺少 ONES 前置条件
- **WHEN** 当前应用已发布 ONES Capability，但 Job 没有可用外部主体快照或当前绑定复核失败
- **THEN** 系统提示模型说明“该能力对当前发送者暂不可用”并给出“我的外部身份”自助绑定、重新验证、选择 default Team 和重新发送请求的安全操作提示，且不得声称平台全局未注册 ONES Tool

#### Scenario: 安全提示不扩大 Tool 权限
- **WHEN** 系统提示中存在某个 Capability 的 `unavailable` 事实
- **THEN** 该 Capability 不进入 MCP Server、`allowed_tools` 或 Tool 自动批准集合，模型也不得声称已经调用或验证其连通性

