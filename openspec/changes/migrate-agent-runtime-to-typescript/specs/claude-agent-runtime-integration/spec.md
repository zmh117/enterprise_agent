## MODIFIED Requirements

### Requirement: Real runtime is implemented with the Claude Agent SDK
系统 SHALL 使用独立 TypeScript `agent-runtime` 服务中的官方 `@anthropic-ai/claude-agent-sdk` 实现真实 Agent loop；Python Worker MUST 只通过版本化内部协议调用该服务，并在最终切换后 MUST NOT import、安装或执行 Python `claude-agent-sdk`。

#### Scenario: Real runtime executes a job
- **WHEN** 一个 Job 固定了有效 Agent/Application Publication、模型连接和 MCP Tool Binding
- **THEN** Python Worker 委托 TypeScript Runtime 执行真实 SDK loop，并持久化其规范结果和安全 Tool 事件

#### Scenario: Python SDK path is removed
- **WHEN** TypeScript 迁移门禁已经通过且生产默认切换完成
- **THEN** Worker 镜像不再包含 Python Claude Agent SDK、Python SDK 适配器或全局 Claude CLI 安装层

### Requirement: Real runtime is selectable via feature flag
系统 SHALL 在迁移期通过部署侧受控 runtime gate 为测试环境或精确 Application Publication 选择 Python 基线或 `typescript-v1`，并 MUST 在 Job 创建时冻结选择。单次 attempt MUST NOT 因 TypeScript 失败自动回退 Python；最终验收后系统 MUST 删除 Python 选择并使 TypeScript 成为唯一真实 Runtime。

#### Scenario: Stub mode is selected
- **WHEN** `FEATURE_REAL_CLAUDE=false`
- **THEN** 系统使用 deterministic stub，且不调用 Python 或 TypeScript 真实 SDK

#### Scenario: TypeScript canary is selected
- **WHEN** 测试环境的 Application Publication 显式选择 `typescript-v1`
- **THEN** 其 Job 和 retry 均使用同一 Runtime，不因传输或模型错误切换实现

#### Scenario: Migration gate is retired
- **WHEN** TypeScript 生产观察窗口和删除门禁通过
- **THEN** 新 Job 只使用 TypeScript Runtime，旧 gate 不能重新启用 Python SDK路径

### Requirement: Anthropic credentials and CLI runtime are validated before execution
系统 MUST 在 TypeScript Runtime 中按 Job 固定模型连接验证 SDK/CLI、Provider host、模型和 active Secret；凭据缺失、Secret 无效、SDK/CLI 不可用或完整性不匹配时 MUST 在模型调用前返回安全不可重试错误。验证 MUST 不把 Key、Secret ref、完整 Base URL 或 CLI stderr 原文返回 Worker、日志或健康端点。

#### Scenario: Real runtime is missing a credential
- **WHEN** 真实 Runtime 已启用但固定模型 Credential 缺失、禁用或无法解密
- **THEN** invocation 在调用模型和 MCP 前失败，Job 获得稳定安全配置错误

#### Scenario: SDK runtime is unavailable
- **WHEN** 精确锁定的 SDK/CLI 无法启动或版本与镜像声明不一致
- **THEN** Runtime 返回不可重试 runtime-unavailable 错误和脱敏版本诊断

### Requirement: Built-in mutating tools are disabled
系统 SHALL 禁止 SDK 内置的 Bash、Write、Edit、NotebookEdit、文件修改、部署、任意 Web、脚本或 Shell Tool 可见或获批。Runtime SHALL 只自动批准 Job 固定的精确代码定义 MCP Tool，并 MUST 同时通过 `allowedTools`、`disallowedTools`、deny-by-default permission hook 和 MCP Server scope 校验拒绝其他 Tool。

#### Scenario: Model attempts a built-in write tool
- **WHEN** SDK 模型尝试调用 Bash、Write 或 Edit
- **THEN** Tool 不可见或调用被拒绝，且系统不产生修改

#### Scenario: Only the current MCP set is auto-approved
- **WHEN** Job 只固定一个 ONES MCP Tool
- **THEN** 只有该 Tool 获批，Data MCP、其他 ONES Tool 和通用 Web 均不可用

#### Scenario: Job has no eligible MCP Tool
- **WHEN** Publication 允许 Tool 但当前身份、凭据、资源或撤权复核失败
- **THEN** Runtime 不注册对应 Server/Tool，并且安全提示不扩大权限

### Requirement: Execution is bounded by turns and wall-clock time
系统 SHALL 使用 Job 固定的有效执行策略限制 TypeScript SDK 最大轮次、单次 attempt 墙钟时间和 MCP Tool 调用次数。Runtime MUST 用 AbortController 传播 timeout/cancel，Worker MUST NOT 对缺失或不支持的执行策略使用进程环境或当前 Publication fallback。

#### Scenario: Execution exceeds configured timeout
- **WHEN** SDK session 超过 Job 有效 `timeout_seconds`
- **THEN** Runtime 中止 SDK 和当前 MCP 请求，返回已有安全 Tool 事件及稳定 timeout 终态

#### Scenario: Execution reaches maximum turns
- **WHEN** SDK session 达到 Job 有效 `max_turns` 且没有有效最终结果
- **THEN** Runtime 返回最大轮次耗尽分类，不把它仅作为普通 transport transient

#### Scenario: Execution reaches maximum tool calls
- **WHEN** attempt 已执行 Job 有效 `max_tool_calls` 次 MCP Tool 调用
- **THEN** permission hook 拒绝下一次调用并返回稳定策略耗尽错误

#### Scenario: Job 缺少执行策略
- **WHEN** Job 策略缺失、schema 不支持或字段不完整
- **THEN** Worker 在调用 Runtime 前以不可重试完整性错误停止

### Requirement: SDK failures are classified for retry policy
系统 SHALL 由 TypeScript Runtime 将 SDK/CLI 故障映射为稳定错误码和 retry class，再由 Python Job retry policy 作最终决定。网络、429/5xx、transport 和可确认的瞬时 Provider 故障可重试；凭据、模型配置、权限、Publication 完整性和协议错误不可重试；矛盾 result 与最大轮次 MUST 使用独立有界分类。

#### Scenario: Transient process error triggers retry
- **WHEN** Runtime 返回 rate limit、overloaded、transport 或可确认 CLI decode transient
- **THEN** Worker 按固定 Job policy 延迟重试且继续使用相同 Publication 与 Runtime 版本

#### Scenario: Contradictory result exhausts retries
- **WHEN** 同一 Job 持续收到 `claude_inconsistent_result` 并达到最大次数
- **THEN** Job 进入终态失败且只发送一次安全失败通知

#### Scenario: Configuration failure does not retry
- **WHEN** Runtime 确认缺少凭据、SDK/CLI 不可用、模型无效或请求完整性失败
- **THEN** Worker 不进入延迟 retry queue

#### Scenario: Policy violation does not retry as transport error
- **WHEN** MCP Tool 因只读边界、Publication、scope 或权限被拒绝
- **THEN** 系统记录安全拒绝，不把它误分类为 SDK transport retry

### Requirement: Tool events are returned without private reasoning
系统 SHALL 从 TypeScript Runtime 接收并持久化按 sequence 排序的安全 Tool invocation、结果分类、大小和 MCP Publication/Resource provenance；系统 MUST 排除原始 Secret、认证材料、完整 HTTP/Provider body、不受限 payload、SDK thinking block 和私有 chain-of-thought。

#### Scenario: Successful tool loop produces events
- **WHEN** TypeScript Runtime 在一个或多个 MCP Tool 后完成
- **THEN** `AgentRunResult` 包含可写入 `agent_tool_call`/MCP provenance 的有界顺序摘要

#### Scenario: Runtime fails after Tool calls
- **WHEN** SDK 在已执行 Tool 后 timeout、取消或失败
- **THEN** Worker 仍持久化失败前收到的安全 Tool 事件和稳定终态

### Requirement: Health endpoints report runtime mode without invoking Claude
系统 SHALL 在 API readiness 中聚合 TypeScript Runtime process/readiness，并报告启用模式、协议版本、SDK/CLI 精确版本和模型配置状态；检查 MUST NOT 调用真实 Claude/DeepSeek 或业务 MCP Tool，也不得报告 Key、Secret ref 或完整 Provider URL。

#### Scenario: Ready check with stub mode
- **WHEN** `/api/ready` 在真实模型禁用时被调用
- **THEN** 响应显示 stub 模式且不会请求 TypeScript Runtime 执行模型

#### Scenario: TypeScript Runtime unavailable
- **WHEN** 真实 Runtime 已启用但服务、协议或 SDK readiness 不满足
- **THEN** API readiness 失败关闭并返回安全原因码

### Requirement: 真实Runtime必须使用Job固定的模型连接
系统 SHALL 让 Python Worker 和 TypeScript Runtime只使用 Job 固定 Agent Publication 中的模型连接 revision、config hash、Base URL、模型映射、Subagent 模型、effort 和 Credential 绑定。两端 MUST 校验相同摘要，MUST NOT 用进程启动时全局 URL、模型或 Key 覆盖固定快照。

#### Scenario: Job排队后发布新模型连接
- **WHEN** Job 已固定旧 Agent Publication 后管理员发布新模型连接
- **THEN** 已排队 Job 和 retry 继续使用原固定配置，新 Job 才使用新 Publication

#### Scenario: Publication模型连接hash不匹配
- **WHEN** Worker 或 Runtime 读取到的 revision 与固定 config hash 不一致
- **THEN** invocation 在解析 Key、启动 SDK或调用 MCP 前以不可重试完整性错误失败

### Requirement: Runtime必须安全解析并隔离每次执行的模型环境
系统 MUST 在每次 TypeScript invocation 开始时构造独立模型环境，并按固定模型绑定的 active Secret 映射 Base URL、API Key/Auth Token、主模型、默认模型、Subagent 模型和 effort。并发 Job MUST 不通过 `process.env` mutation、共享 SDK options 或全局缓存产生跨 Job URL、模型、Token 或权限串用。

#### Scenario: 两个Job使用不同模型连接
- **WHEN** Runtime 并发处理固定到不同模型连接的 Job
- **THEN** 每个 SDK session 只看到自己的模型环境、MCP Token 和 Tool allowlist

#### Scenario: Active Key被轮换
- **WHEN** 固定 Credential 在 attempt 开始前轮换
- **THEN** Runtime 使用新 active Secret version，而 Publication 配置和 provenance 不变

## REMOVED Requirements

### Requirement: Async SDK is bridged into synchronous execution
**Reason**: 异步 Claude SDK 已迁移到独立 TypeScript 服务，不再需要 Python 线程和 event-loop bridge。

**Migration**: Python `AgentExecutor` 通过流式 Runtime client 接收规范事件和终态；删除 `asyncio.run`/thread bridge 及其测试。
