## ADDED Requirements

### Requirement: Python Runtime内部职责必须静态组装并保持行为等价
系统 SHALL 通过代码拥有的显式端口和静态装配分离 Runtime 请求边界、单次 attempt 编排、Claude Agent SDK 调用、SDK 事件规范化、固定 MCP 配置、Tool Policy、错误映射、文件桥与 Job Sandbox 生命周期。重构 MUST 保持现有版本化协议、request digest、invocation、事件顺序、唯一终态、取消/恢复、稳定错误码、retry 分类、审计字段、MCP Tool identifier/schema/scope、Principal JWT、Runtime Grant、模型凭据隔离和文件沙盒行为不变。系统 MUST NOT 因内部模块化引入动态插件扫描、运行时 client/Server 注册、任意 Runtime/MCP URL、通用执行器或 Worker 进程内 SDK。

#### Scenario: 控制面使用单一Runtime端口
- **WHEN** `agent-worker` 为固定 `python-v1` 的 Job 调用 Runtime
- **THEN** `AgentExecutor` 只依赖 application-owned `AgentRuntimeClient` 端口并委托平台静态装配的唯一 Python Runtime client
- **AND** 未知、退役或协议不受支持的 Job 在模型调用前继续返回原稳定错误

#### Scenario: SDK事件和错误逻辑被提取
- **WHEN** 同一组成功、工具调用、API retry、最大轮次、超时、Provider 错误和矛盾终态 fixture 在重构前后执行
- **THEN** 事件 sequence、计量、tool event、terminal、错误码、retryable 分类、safe message 和有界脱敏 diagnostics 保持等价

#### Scenario: 固定MCP与工具策略被提取
- **WHEN** Python Runtime 构造 Tool MCP、ONES MCP 或 File MCP 会话并处理允许或拒绝的 Tool Call
- **THEN** Server code、Tool identifier/schema/scope、Principal 绑定、禁止字段、调用次数、文件路由和审计关联保持不变
- **AND** 自定义 URL、未冻结 Tool、危险工具或越界参数继续在调用前失败关闭

#### Scenario: 文件与沙盒生命周期跨重构保持一致
- **WHEN** Job 成功、失败、取消、超时或恢复并涉及自动物化、提交或文件冲突
- **THEN** 精确版本/哈希校验、受控流式传输、路径/符号链接/容量守卫、唯一终态和 finally 清理保持不变

#### Scenario: 模块装配拒绝动态扩展
- **WHEN** 部署或测试检查 Python Runtime 的依赖图与启动装配
- **THEN** 不存在运行时插件发现、动态 client/Server registry、任意 MCP/Runtime URL 或 Worker 进程内 Claude SDK
- **AND** Claude SDK client 不拥有数据库、RabbitMQ、Job、retry、Outbox 或 Delivery 业务状态

## MODIFIED Requirements

### Requirement: 失败路径必须保留真实运行时工具事件
系统 SHALL 在真实 Claude SDK 执行失败、超时或达到最大轮次时，保留失败前已经发生的工具调用安全摘要，并将这些摘要交给应用层持久化。工具事件 MUST 不包含私有推理、密钥、未脱敏 raw payload 或不受限响应正文。

#### Scenario: 最大轮次耗尽后保留工具轨迹
- **WHEN** `ClaudeSdkClient.run()` 在一个已经调用过内部工具的 job 中收到 `Reached maximum number of turns` 类错误
- **THEN** 系统持久化失败前已收集的工具调用摘要，并在 job step 中记录安全失败原因

#### Scenario: SDK timeout 后保留工具轨迹
- **WHEN** 真实 SDK 会话超时且超时前已经调用过内部工具
- **THEN** 系统持久化已完成或已失败的工具调用摘要，并继续按 timeout 错误分类处理 job

### Requirement: Claude runtime can load model settings from DB-backed runtime config
系统 SHALL 允许真实 Claude/DeepSeek runtime 从 DB-backed runtime config 加载 base URL、model、默认模型、effort level、max turns 和 timeout，并保留 env fallback。

#### Scenario: DB config selects DeepSeek model
- **WHEN** runtime config 配置 `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic` 和 `ANTHROPIC_MODEL=deepseek-v4-pro[1m]`
- **THEN** `PythonRuntimeExecutor` 和 `ClaudeSdkClient` 使用 DB-backed 配置构造 SDK runtime

#### Scenario: DB config missing
- **WHEN** DB-backed Claude runtime config 不存在
- **THEN** runtime 使用现有 env/default 逻辑，并在 ready 输出中标记来源

### Requirement: Claude runtime API key can use Web-managed secret
系统 SHALL 允许 `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` 通过 Web-managed secret ref 配置，并且 ready/health 只能报告是否 configured，不能泄漏 key。

#### Scenario: API key is stored as secret ref
- **WHEN** runtime config 将 `ANTHROPIC_API_KEY` 指向 `secret://platform/deepseek_api_key`
- **THEN** `ClaudeSdkClient` 仅在调用 SDK 前解析 secret，日志和 ready 输出不包含明文 key

#### Scenario: API key secret is missing
- **WHEN** 真实模型执行已启用但 API key secret 无法解析
- **THEN** ready 或执行前校验返回安全配置错误，不调用外部模型 API

### Requirement: Claude runtime consumes the job-fixed Agent publication
系统 SHALL 在执行 job 时读取 job 固定的不可变 Agent publication snapshot，并 MUST 使用其中的业务指令、模型策略、执行限制、Skill 和允许工具配置。runtime MUST NOT 读取活动草稿或执行时重新选择当前发布版本。

#### Scenario: Job executes published configuration
- **WHEN** worker 执行固定了默认诊断 Agent publication 的 job
- **THEN** `AgentContextBuilder`、`PythonRuntimeExecutor` 和 `ClaudeSdkClient` 使用该 snapshot 构建运行上下文

#### Scenario: Publication changes during execution
- **WHEN** 管理员在 job 运行期间发布新版本
- **THEN** 当前 job 继续使用固定 snapshot，新版本不改变本次 prompt、工具或执行限制

### Requirement: 真实Runtime必须使用Job固定的模型连接
系统 SHALL 让 `AgentExecutor`、`PythonRuntimeExecutor` 和 `ClaudeSdkClient` 从 Job 固定的 Agent Publication 获取模型连接 revision、config hash、Base URL、模型映射、Subagent 模型、effort 和 Credential 绑定。Worker MUST NOT 为包含模型连接快照的新 Publication 重新读取 Agent 当前发布指针或用进程启动时的全局模型 URL、模型和 Key 覆盖该快照。

#### Scenario: Job排队后发布新模型连接
- **WHEN** Job 已固定 Agent Publication 后管理员发布使用不同 Base URL 或模型的新 Agent Publication
- **THEN** 已排队 Job 和其重试继续使用原固定模型连接 revision
- **AND** 新 Job 才使用新 Agent Publication 的模型连接

#### Scenario: Publication模型连接hash不匹配
- **WHEN** Runtime 读取到的模型连接 revision 与 Agent Publication 固定的 config hash 不一致
- **THEN** Job 在调用 Claude Agent SDK 前以不可重试完整性错误失败
- **AND** 不解析 Key、不启动 CLI、不调用模型或工具

### Requirement: Claude Code Agent SDK is wrapped behind a client
系统 SHALL 将 Claude Agent SDK 使用隔离在 Python Runtime 的 `ClaudeSdkClient` 后，使 domain、application 和 `agent-worker` 不依赖具体 SDK API。`AgentExecutor` SHALL 只调用 application-owned `AgentRuntimeClient`，`PythonRuntimeExecutor` SHALL 调用 `ClaudeSdkClient`，且只有 `python-agent-runtime` 镜像包含 Claude Agent SDK/CLI。

#### Scenario: AgentExecutor invokes Agent Runtime
- **WHEN** `AgentExecutor` 需要模型执行
- **THEN** 它把结构化 Runtime 请求交给 `AgentRuntimeClient`，而不是调用 Claude SDK API

#### Scenario: Python Runtime uses the SDK internally
- **WHEN** `PythonRuntimeExecutor` 使用有效模型绑定执行 attempt
- **THEN** 只有 `ClaudeSdkClient` 调用 Claude Agent SDK API，控制面和 Worker 不感知 SDK 类型

### Requirement: Skills are loaded as explicit diagnostic workflows
The system SHALL load only configured diagnostic Skills for MVP, including bug analysis, SQL diagnosis, Redis diagnosis, and Loki log analysis. The real runtime SHALL inject loaded skill guidance into the SDK system prompt (or equivalent settings) so the agent follows the configured diagnostic workflows.

#### Scenario: Skills are registered
- **WHEN** the Agent runtime starts a diagnostic job
- **THEN** it passes configured Skills through `PythonRuntimeExecutor` to `ClaudeSdkClient` and makes their workflow guidance available to the Agent

### Requirement: Private model reasoning is not persisted
The system SHALL persist user-visible execution steps and evidence summaries, not private model chain-of-thought. `AgentExecutor` SHALL persist tool call summaries from `AgentRunResult.tool_events` and SHALL NOT persist raw SDK thinking blocks or hidden reasoning content.

#### Scenario: Agent records progress
- **WHEN** the Agent reasons internally during diagnosis
- **THEN** the system persists only safe step summaries, tool calls, tool results, artifacts, and final answer content

#### Scenario: Tool events are persisted after real execution
- **WHEN** `ClaudeSdkClient` returns tool events for a completed job through `PythonRuntimeExecutor`
- **THEN** `AgentExecutor` writes corresponding `agent_tool_call` rows with desensitized summaries
