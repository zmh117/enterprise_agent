## MODIFIED Requirements

### Requirement: 模型可以组合公开的 Capability 输入输出
Claude Tool 循环 SHALL 能读取一个受治理 MCP Tool 的规范化公开输出，并依据后续 Tool 的公开 Input Schema 组织新的结构化调用；每次调用必须独立经过当前 Job 的 Tool 可见性、schema 与执行校验，运行时不得创建隐式服务端 Handler 流水线。

#### Scenario: 顺序调用两个MCP Tool
- **WHEN** 模型使用第一个 Tool 的规范化字段构造第二个 Tool 输入
- **THEN** SDK 循环执行两个独立 Tool 调用并分别产生安全 Tool 事件

#### Scenario: 后续Tool不在当前冻结集合
- **WHEN** 模型尝试根据文本调用未注册或未冻结的 Tool
- **THEN** SDK 权限策略拒绝该调用且不发起外部请求

### Requirement: 外部规范化文本不得提升为指令
运行时 MUST 将受治理 MCP Tool 的字符串输出标记和封装为不可信业务数据，不得把它拼接进 system、developer、Tool 定义或据此修改 `allowed_tools`、MCP Server binding 和权限策略。

#### Scenario: Tool输出包含提示注入
- **WHEN** 外部字段内容声称自己是系统指令或要求调用被禁用 Tool
- **THEN** 内容保持普通 Tool 数据，系统提示、Tool 集合和权限不发生变化

### Requirement: 不可用 Capability 使用独立安全提示通道
运行时 MUST 将受治理业务 MCP Tool 的调用资格与模型解释事实分离：不满足当前发送者 Provider 身份或 Credential 前置条件的 Tool MUST 保持未注册、未批准，同时 MAY 仅在该 Tool 已属于精确 Agent/Application 发布交集时，以固定白名单文案向模型说明当前 Job 的不可用状态。提示 MUST NOT 复用原始异常，不得包含用户、Team、Credential、Principal 或认证材料，也不得被模型视为可调用 Tool。

#### Scenario: 当前发送者缺少ONES前置条件
- **WHEN** 当前应用已发布 ONES Tool，但 Job 没有可用外部主体或当前 Credential 复核失败
- **THEN** 系统提示模型说明“该能力对当前发送者暂不可用”并给出安全的本人重新验证提示
- **AND** 不得声称平台全局未注册 ONES Tool

#### Scenario: 安全提示不扩大Tool权限
- **WHEN** 系统提示中存在某个 Tool 的 `unavailable` 事实
- **THEN** 该 Tool 不进入 MCP Server、`allowed_tools` 或 Tool 自动批准集合
- **AND** 模型不得声称已经调用或验证其连通性

### Requirement: Claude Code Agent SDK is wrapped behind a client
系统 SHALL 将 Claude Agent SDK 使用隔离在 Python Runtime 的 `ClaudeSdkClient` 后，使 domain、application 和 `agent-worker` 不依赖具体 SDK API。`AgentExecutor` SHALL 只调用 application-owned `AgentRuntimeClient`，`PythonRuntimeExecutor` SHALL 只调用 `ClaudeSdkClient`，且只有 `python-agent-runtime` 镜像包含 Claude Agent SDK/CLI。

#### Scenario: AgentExecutor invokes Agent Runtime
- **WHEN** `AgentExecutor` 需要模型执行
- **THEN** 它把结构化 Runtime 请求交给 `AgentRuntimeClient`
- **AND** 不直接导入或调用 Claude Agent SDK API

#### Scenario: Python Runtime uses the SDK internally
- **WHEN** `PythonRuntimeExecutor` 使用有效模型绑定执行 attempt
- **THEN** 只有 `ClaudeSdkClient` 调用 Claude Agent SDK API
- **AND** 控制面和 Worker 不感知 SDK 类型

### Requirement: Runtime 请求必须只冻结 MCP Tool 而不包含旧平台对象
Worker 发送给 Python Runtime 的执行请求 SHALL 包含 Job 与 Publication 固定的 MCP Server code、精确 Tool identifier、schema hash 和执行标识；Runtime 只能把这些 binding 连接到部署代码注册的私网 Server。业务 MCP Principal 与 File Principal MUST 通过各自受保护 Header 传递而不进入 JSON 请求或模型上下文。请求 MUST NOT 包含 Capability Release、Handler Revision、API Connection、Resource Mapping、Resource Revision、Internal API Token、Runtime URL、任意 MCP URL 或任意 MCP 鉴权配置。

#### Scenario: Worker构造多Server Runtime请求
- **WHEN** Job 冻结了来自 `tool-mcp`、业务 MCP 或 `file-service` 的多个 Tool
- **THEN** Runtime 请求只携带每个 binding 的固定 Server code、Tool identifier 和 schema hash
- **AND** Python Runtime 使用代码注册的部署地址与对应固定身份策略

#### Scenario: 业务和文件Principal传输
- **WHEN** Runtime 调用需要业务 Principal 或 File Principal 的 Server
- **THEN** 对应短时 Token 只通过受保护的 Server 专用 Header 注入
- **AND** Token 不进入 Runtime JSON、Prompt、Tool 参数、事件或审计载荷

#### Scenario: 请求包含旧平台字段
- **WHEN** 请求包含 capability、handler、connection、resource_mapping、internal_api_token、runtime_url、任意 MCP URL 或鉴权配置
- **THEN** Runtime 合约校验失败且不启动模型调用

### Requirement: RabbitMQ queues support retry and dead letter handling
系统 SHALL 定义普通执行、版本化延迟重试和 dead-letter 队列；可重试消息 MUST 在配置延迟后自动回到普通执行队列，重试耗尽或不可重试错误 MUST 进入 dead-letter 路径。

#### Scenario: Retryable failure occurs
- **WHEN** Agent 执行因可重试 MCP、Provider、Loki、Claude、RabbitMQ、数据库 timeout 或瞬时连接错误失败
- **THEN** 系统将 Job 置为 `RETRY_WAIT`，增加 retry metadata，并调度仅包含 `job_id` 与 `correlation_id` 的延迟 retry 消息

#### Scenario: Retry delay expires
- **WHEN** retry 消息的 expiration 到期
- **THEN** RabbitMQ 将同一最小消息 dead-letter 到主队列，Worker 根据数据库 `RETRY_WAIT` 状态和 `next_retry_at` 决定是否 claim

#### Scenario: Retry limit is exceeded
- **WHEN** 可重试 Job 已使用全部配置重试次数
- **THEN** 系统将 Job 标记为 `FAILED`，路由 dead-letter，不再调度 Agent execution retry

#### Scenario: Non-retryable failure occurs
- **WHEN** Agent 执行因权限拒绝、未知资源、只读 policy 拒绝、无效 Tool 参数、明确配置错误或不支持请求失败
- **THEN** 系统将 Job 标记为 `FAILED`，不调度 retry，并路由 dead-letter

### Requirement: 规范化 Capability 结果沿用既有持久化生命周期
通过 Output Schema 和大小限制的 MCP Tool 结果以及最终回复 SHALL 按现有 Job、Tool Call、会话与制品模型正常持久化；系统 MUST 保留用户、Application Publication、MCP Server、Tool identifier、schema hash 和数据分级来源，且当前 `retention_days` MUST 只保存而不触发定时清理。

#### Scenario: 业务MCP查询完成
- **WHEN** 受治理 MCP Tool 返回合法规范化结果并由 Agent 形成最终回复
- **THEN** 系统按既有成功生命周期保存结果与 Server/Tool/schema 来源
- **AND** 不保存原始 Provider HTTP 响应或认证材料

#### Scenario: retention_days已配置
- **WHEN** 会话策略含有 `retention_days`
- **THEN** 系统继续只保存该值而不据此删除 MCP Tool 结果

### Requirement: Tool events are returned without private reasoning
The system SHALL populate `AgentRunResult.tool_events` with safe summaries of each code-registered Tool invocation, attempt outcome, result size, MCP server code, Tool identifier, schema hash and applicable classification provenance, excluding raw secrets, authentication material, raw HTTP bodies, full unbounded payloads and private model chain-of-thought including SDK thinking blocks.

#### Scenario: Successful tool loop produces events
- **WHEN** the real runtime completes after one or more MCP Tool calls
- **THEN** `AgentRunResult` includes ordered safe Tool event summaries suitable for persistence in `agent_tool_call`

#### Scenario: Business MCP call fails after Provider attempts
- **WHEN** a business MCP Tool exhausts its allowed Provider attempts
- **THEN** the event summary includes Server/Tool/schema, safe classification and attempt count
- **AND** it excludes Provider body, Token and authentication Header

## RENAMED Requirements

- FROM: `Read-only tools are exposed only through the deployment-fixed standard MCP server`
- TO: `Runtime tools are exposed only through deployment-fixed MCP Servers`
- FROM: `规范化 Capability 结果沿用既有持久化生命周期`
- TO: `规范化MCP Tool结果沿用既有持久化生命周期`
- FROM: `模型可以组合公开的 Capability 输入输出`
- TO: `模型可以组合公开的MCP Tool输入输出`
- FROM: `不可用 Capability 使用独立安全提示通道`
- TO: `不可用业务MCP Tool使用独立安全提示通道`
