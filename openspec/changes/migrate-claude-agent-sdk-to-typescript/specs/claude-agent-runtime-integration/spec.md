## MODIFIED Requirements

### Requirement: Real runtime is implemented with the Claude Agent SDK
系统 SHALL 在独立 TypeScript `agent-runtime` 服务中使用官方 `@anthropic-ai/claude-agent-sdk` 执行 `typescript-v1` Agent loop，并 SHALL 长期保留现有 Python Claude Agent SDK 作为 `python-v1` 执行路径。公共编排层 SHALL 只依赖语言无关的 `AgentRunResult`/Runtime client 契约；每条 Runtime 的 SDK 类型不得泄漏到公共 Job 编排逻辑。

#### Scenario: TypeScript Runtime驱动Agent loop
- **WHEN** `AgentExecutor` 执行一个固定为 `typescript-v1` 且配置有效的 Job
- **THEN** Python Runtime client 调用 TypeScript Runtime，由 Runtime 消费 SDK message stream 并返回规范最终结果

#### Scenario: SDK类型不泄漏到Python应用层
- **WHEN** Python `AgentExecutor` 调用路由 Runtime client
- **THEN** 公共编排逻辑只处理 Runtime client 契约和 `AgentRunResult`，不直接处理 TypeScript SDK 类型或 Python `claude_agent_sdk` 消息类型

#### Scenario: Python Runtime长期保留
- **WHEN** 新 Job 未命中任何显式 TypeScript 环境或 Application Publication 门禁
- **THEN** Job 固定为 `python-v1` 并由现有 Python Claude Agent SDK 路径执行
- **AND** TypeScript 灰度或 E2E 完成不得自动删除、禁用或降级 Python Runtime

### Requirement: Real runtime is selectable via feature flag
系统 SHALL 通过显式环境/Application 门禁与不可变 Job Runtime 快照选择 `python-v1` 或 `typescript-v1`。未命中 TypeScript 门禁时 MUST 默认选择 `python-v1`；同一 attempt 和 retry MUST 使用冻结 Runtime，且在 Runtime 故障时 MUST NOT 自动跨实现 fallback。测试容器默认继续使用 stub，除非测试显式注入 Runtime client。

#### Scenario: 默认选择Python Runtime
- **WHEN** 新 Job 没有命中显式 TypeScript 门禁
- **THEN** 系统把 `python-v1` 和协议版本固定到 Job

#### Scenario: 指定Application使用TypeScript Runtime
- **WHEN** 测试 Application 的已发布配置固定 `typescript-v1`
- **THEN** 新 Job 和其所有 retry 均调用 TypeScript Runtime

#### Scenario: TypeScript Runtime不可用
- **WHEN** 固定为 `typescript-v1` 的 attempt 无法连接 Runtime
- **THEN** 系统按稳定错误分类进入本地 retry/终态流程，不自动改用 Python SDK

#### Scenario: 本地测试保持Stub
- **WHEN** 单元测试构建测试 Container 且未覆盖客户端
- **THEN** `AgentExecutor` 使用 stub，不需要模型凭据、Node 服务或外部网络

### Requirement: Read-only tools are exposed only through governed MCP servers
系统 SHALL 通过受治理的远程 MCP 服务向 TypeScript SDK 暴露当前 Job 精确允许的内部只读 Tool 和业务查询能力。MCP 服务 MUST 在每次调用复核短期 Token、Job 状态、主体、Application、Tool schema hash、scope 和资源绑定；Runtime MUST NOT 自动发现平台全部 Tool 或接受模型提供的 Server URL。

#### Scenario: 模型调用注册的只读Tool
- **WHEN** Claude 调用当前 Job 冻结的 `mcp__<server>__<tool>` 且服务端复核通过
- **THEN** 请求进入现有受治理只读 Tool 实现并把安全结果返回模型

#### Scenario: Tool上下文按Job隔离
- **WHEN** 两个 Job 并发调用相同 MCP Tool
- **THEN** 每次调用使用各自 Job、Publication、主体、scope 和资源绑定，不共享认证材料或上下文

#### Scenario: Tool尚无远程等价实现
- **WHEN** Application 依赖的当前 Tool 未完成受治理远程 MCP 映射
- **THEN** 该 Application 不得发布或切换到 `typescript-v1`
- **AND** 系统不得以任意 HTTP 执行或静默 Python fallback 代替

### Requirement: Health endpoints report runtime mode without invoking Claude
系统 SHALL 聚合所选 Runtime 模式、TypeScript Runtime readiness、协议/SDK 版本和必要依赖的脱敏状态。健康与就绪检查 MUST NOT 调用 Claude、模型 Provider 或业务 MCP Tool。

#### Scenario: Python默认模式
- **WHEN** `/api/ready` 在默认双 Runtime 配置下被调用
- **THEN** 响应报告默认 Runtime 为 `python-v1` 及 TypeScript Runtime 可用性，但不调用模型

#### Scenario: TypeScript Runtime缺少配置
- **WHEN** TypeScript Runtime 被启用但 Grant、模型连接、Master Key 文件或依赖未就绪
- **THEN** readiness 失败关闭并返回脱敏原因
