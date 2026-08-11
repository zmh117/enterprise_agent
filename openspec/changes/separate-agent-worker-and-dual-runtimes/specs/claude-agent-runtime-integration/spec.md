## MODIFIED Requirements

### Requirement: Real runtime is implemented with the Claude Agent SDK
系统 SHALL 在独立 `python-agent-runtime` 中使用 Python `claude-agent-sdk` 执行 `python-v1` Agent loop，并在独立 `typescript-agent-runtime` 中使用官方 `@anthropic-ai/claude-agent-sdk` 执行 `typescript-v1` Agent loop。公共 Worker 编排层 SHALL 只依赖语言无关的 Runtime client 与 `AgentRunResult`/协议事件；两种 SDK 类型均不得泄漏到 Worker、Job 或 Delivery 应用层。

#### Scenario: Python Runtime驱动Agent loop
- **WHEN** Worker 执行固定为 `python-v1` 且配置有效的 Job
- **THEN** Runtime client 调用 Python Runtime，由其消费 Python SDK message stream 并返回规范终态

#### Scenario: TypeScript Runtime驱动Agent loop
- **WHEN** Worker 执行固定为 `typescript-v1` 且配置有效的 Job
- **THEN** Runtime client 调用 TypeScript Runtime，由其消费 TypeScript SDK message stream 并返回规范终态

#### Scenario: SDK类型不泄漏到编排层
- **WHEN** Worker 调用任一 Runtime
- **THEN** 公共编排逻辑只处理版本化请求、事件和领域结果，不 import 或引用任一 SDK 消息类型

### Requirement: Real runtime is selectable via feature flag
系统 SHALL 仅根据 Job 固定的 Agent Publication runtime kind 选择 `python-v1` 或 `typescript-v1`。Runtime enablement 配置只能决定对应服务是否可部署/就绪，MUST NOT 覆盖 Job 选择；同一 attempt 和 retry MUST 使用冻结 Runtime，故障时 MUST NOT 自动跨实现 fallback。测试可以显式注入 fake Runtime client，但不得依赖环境/Application migration gate 推导生产 Runtime。

#### Scenario: Python Agent选择Python Runtime
- **WHEN** Application 选择固定 `python-v1` 的 Agent Publication
- **THEN** 新 Job 与其所有 retry 均调用 Python Runtime

#### Scenario: TypeScript Agent选择TypeScript Runtime
- **WHEN** Application 选择固定 `typescript-v1` 的 Agent Publication
- **THEN** 新 Job 与其所有 retry 均调用 TypeScript Runtime

#### Scenario: 固定Runtime不可用
- **WHEN** 固定 Runtime 无法连接或未就绪
- **THEN** 系统按稳定错误分类进入本地 retry/终态流程，不自动调用另一 SDK

#### Scenario: 本地测试使用Fake Runtime
- **WHEN** 单元测试显式注入 fake Runtime client
- **THEN** 测试不需要模型凭据、Runtime 服务或外部网络

### Requirement: Anthropic credentials and CLI runtime are validated before execution
系统 SHALL 在所选 Runtime 内按 Job 固定模型连接解析 Anthropic 兼容凭据，并验证该 Runtime 所需 SDK/CLI；`agent-worker` MUST 不持有 provider 明文凭据或 Claude Code CLI。缺少凭据、SDK 或 CLI MUST 返回安全、不可重试的配置错误。

#### Scenario: 缺少API key
- **WHEN** 所选 Runtime 无法解析 Job 固定 Credential binding 的 active Secret
- **THEN** 执行在调用模型前以不可重试配置错误失败且安全通知不包含 Secret

#### Scenario: Python Runtime缺少CLI
- **WHEN** Python Claude Agent SDK 无法定位其所需 CLI runtime
- **THEN** Python Runtime 返回不可重试依赖错误而不无限重试

#### Scenario: Worker镜像检查
- **WHEN** 部署检查纯 Worker 镜像
- **THEN** 其中不存在 provider 明文凭据注入、任一 Agent SDK 或 Claude Code CLI

### Requirement: Read-only tools are exposed only through an in-process SDK MCP server
系统 SHALL 删除 `runtime-tool-mcp` 及其专用 HS256 Token/签名密钥，并让两个独立 Runtime 通过一个直接使用官方 MCP SDK 的标准 MCP Tool Server 访问 Job 冻结的只读 Tool。Runtime MUST NOT 自动发现平台全部 Tool、接受任意 Server URL、向 MCP 发送 Runtime Grant 或在 Tool 不可用时跨 Runtime fallback。MCP transport 不新增 Token、签名、RBAC 或治理层；现有业务权限与只读边界继续在 Job/Worker 和底层工具实现中生效。

#### Scenario: Python Runtime调用允许Tool
- **WHEN** Python SDK 调用 Job 精确允许的 MCP Tool
- **THEN** 调用通过标准 MCP SDK 服务进入现有只读实现并把安全结果返回 Python Runtime
- **AND** 请求不携带 `runtime-tool-mcp` access token 或 Runtime Grant

#### Scenario: TypeScript Runtime调用允许Tool
- **WHEN** TypeScript SDK 调用 Job 精确允许的 MCP Tool
- **THEN** 调用通过同一标准 MCP SDK 服务进入现有只读实现并把安全结果返回 TypeScript Runtime
- **AND** 请求不携带 `runtime-tool-mcp` access token 或 Runtime Grant

#### Scenario: Tool上下文按Job隔离
- **WHEN** 两个 Runtime 并发调用相同 Tool
- **THEN** 每次调用使用各自 Job、Publication 和 invocation 上下文，不共享模型凭据、Runtime Grant 或可变全局上下文

#### Scenario: 模型提供任意MCP地址
- **WHEN** 请求内容或模型输出尝试注册未冻结的 MCP Server URL 或 Tool
- **THEN** Runtime 与服务端均失败关闭且不执行该调用

#### Scenario: 旧MCP密钥被配置
- **WHEN** 启动配置仍包含 `RUNTIME_TOOL_MCP_*`、旧 HS256 signing key 或专用 access token
- **THEN** 部署预检失败并要求删除旧配置，不启动兼容模式

### Requirement: Health endpoints report runtime mode without invoking Claude
系统 SHALL 分别聚合纯 Worker、Python Runtime 与 TypeScript Runtime 的 readiness、协议/SDK/CLI 版本和必要依赖的脱敏状态。health/readiness MUST NOT 调用 Claude、模型 Provider 或业务 MCP Tool；单一 Runtime 未就绪 MUST 阻止依赖它的新 Job/应用激活，但不得伪装另一 Runtime 可替代它。

#### Scenario: 双Runtime均就绪
- **WHEN** `/api/ready` 在两个 Runtime 配置有效且协议兼容时被调用
- **THEN** 响应分别报告 `python-v1` 与 `typescript-v1` 可用且不调用模型

#### Scenario: TypeScript Runtime缺少配置
- **WHEN** TypeScript Runtime 缺少模型连接读取条件、SDK 或必要内部配置
- **THEN** readiness 返回 `typescript-v1` 的脱敏失败原因，依赖它的应用激活/新 Job 失败关闭
- **AND** 系统不自动改用 Python Runtime

### Requirement: Claude runtime DB-backed settings shall be smoke-verifiable
系统 SHALL 提供 smoke 流程，分别验证 Python 与 TypeScript Runtime 的 base URL、model、max turns 和 API key Secret ref 能从 Job 固定模型连接进入所选 Runtime，而不是进入 `agent-worker`。

#### Scenario: Fake Runtime验证配置投影
- **WHEN** 默认 smoke 使用 fake provider 且不启用真实外部调用
- **THEN** 流程仍能验证 Job 固定模型连接被正确投影到两个 Runtime 请求，并确认 Worker 不接收明文 Key

#### Scenario: 可选真实Runtime使用Secret ref
- **WHEN** 开发者显式选择一个 Runtime、提供有效 Secret ref 并启用真实 smoke
- **THEN** 对应 Runtime 在执行前解析 active Secret，ready/job/debug 输出不包含明文 Key

## REMOVED Requirements

### Requirement: Async SDK is bridged into synchronous execution
**Reason**: Worker 不再进程内调用 Python SDK；异步 SDK 生命周期由各自独立 Runtime 服务内部管理，跨服务边界统一为版本化流式协议。

**Migration**: 将 `AgentExecutor -> RealClaudeCodeAgentClient` 的进程内桥替换为 `AgentExecutor -> RuntimeClientRegistry -> selected Runtime`，并用双 Runtime contract test 验证事件与终态。
