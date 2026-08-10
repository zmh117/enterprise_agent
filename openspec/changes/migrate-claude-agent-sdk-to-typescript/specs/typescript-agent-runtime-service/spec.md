## ADDED Requirements

### Requirement: 系统必须提供独立TypeScript Agent Runtime
系统 SHALL 通过独立 TypeScript 服务执行官方 `@anthropic-ai/claude-agent-sdk`，并 MUST 精确锁定 SDK 和 Node 版本。Runtime MUST NOT 直接消费业务 RabbitMQ 队列、写 Agent Job/授权/Delivery 表或在启动时安装依赖。

#### Scenario: Worker调用TypeScript Runtime
- **WHEN** Python Worker 执行固定为 `typescript-v1` 的 Job attempt
- **THEN** Worker 通过版本化内部协议调用 TypeScript Runtime
- **AND** Runtime 返回规范事件和唯一终态，不直接修改 Job 状态

#### Scenario: Runtime镜像启动
- **WHEN** Compose 启动 `agent-runtime`
- **THEN** 服务以非 root、只读文件系统和精确 lockfile 依赖启动
- **AND** 镜像不包含 Python Claude Agent SDK

### Requirement: 执行协议必须严格版本化且有界
Runtime MUST 校验执行请求 protocol version、invocation、attempt、Job/Publication/model revision 与 hash、执行限制、Tool allowlist 和 request digest。流式响应 MUST 使用单调 sequence、受支持事件类型、字段及总字节上限，并且 MUST 只有一个 completed 或 failed 终态。

#### Scenario: 合法请求返回规范事件流
- **WHEN** Worker 提交 schema 合法且授权匹配的执行请求
- **THEN** Runtime 先返回 accepted，再返回零个或多个安全事件，最后返回唯一终态

#### Scenario: 请求摘要或协议不匹配
- **WHEN** 请求的 protocol、digest、Publication hash 或字段上限无效
- **THEN** Runtime 在调用模型和 MCP 前失败关闭并返回稳定协议错误码

### Requirement: Runtime Grant必须绑定单次执行
Worker SHALL 为每个 attempt 签发短期 Runtime Grant，至少绑定 issuer、audience、authorized party、Job、invocation、Publication/hash、request digest、JTI 和 expiry。Runtime MUST 验证全部 claims 和重放状态，不得仅依赖私有网络位置。

#### Scenario: 有效Grant启动执行
- **WHEN** Grant 的 audience、Job、invocation、digest 和有效期与请求完全一致
- **THEN** Runtime 允许该 invocation 进入执行

#### Scenario: Grant被重放或篡改
- **WHEN** JTI 已被不同摘要使用、Grant 已过期或任一绑定不一致
- **THEN** Runtime 在读取 Secret、调用模型或连接 MCP 前拒绝请求

### Requirement: Runtime必须隔离SDK配置和工具权限
每次 SDK 调用 MUST 使用独立 options/env，显式设置 `settingSources: []`，仅注册请求固定的远程 MCP Server，并以精确 `allowedTools` 和 deny-by-default `canUseTool` 限制 Tool。Bash、Write、Edit、NotebookEdit、WebFetch、WebSearch、Shell 和文件修改能力 MUST 被禁用。

#### Scenario: 模型调用允许的只读Tool
- **WHEN** Job 请求固定了一个合法 MCP Server、Tool、schema hash 和 scope
- **THEN** Runtime 只允许对应 `mcp__<server>__<tool>` 调用，并由 MCP 服务再次复核 Job 和 scope

#### Scenario: 模型尝试调用未授权工具
- **WHEN** 模型请求内置写工具、Web 工具或不在精确集合中的 MCP Tool
- **THEN** Runtime 拒绝调用且不向任何 Tool backend 发出请求

### Requirement: Runtime不得泄漏凭据和私有推理
模型 Key、MCP Token、Runtime Grant、Master Key、Secret value、完整 Prompt、原始 Provider/MCP payload 和 private thinking MUST NOT 出现在 RabbitMQ、Job 快照、Runtime 日志、事件、terminal ledger 或响应中。Runtime 只可输出有界脱敏诊断和安全 Tool provenance。

#### Scenario: Provider错误包含凭据
- **WHEN** SDK、CLI 或 MCP 错误文本包含 Token、Authorization Header 或带凭据 URL
- **THEN** Runtime 在记录或返回前屏蔽并截断敏感内容

#### Scenario: SDK产生thinking消息
- **WHEN** SDK 流包含 thinking 或其他私有推理 block
- **THEN** Runtime 丢弃该内容，不写入事件、日志或 Job provenance

### Requirement: Runtime执行必须可取消且可幂等恢复
Runtime SHALL 支持取消进行中的 invocation，并把取消传播到 SDK AbortController 和 MCP 请求。相同 `invocation_id + request_digest` MUST 不重复启动模型执行；已终态调用 SHALL 可返回既有安全终态，不同 digest MUST 冲突失败。

#### Scenario: Worker超时后取消
- **WHEN** Job attempt 超时、被撤销或 Worker 连接断开
- **THEN** Worker 请求取消，Runtime 终止 SDK/MCP 活动并返回稳定 cancel/timeout 分类

#### Scenario: Worker在终态后断线
- **WHEN** Runtime 已完成但 Worker 尚未提交本地事务即断线
- **THEN** Worker 使用相同 invocation 和 digest 读取既有终态，而不重复调用模型

### Requirement: Runtime必须提供无副作用健康与模型探针
Runtime SHALL 提供 health、ready、version 和受服务授权保护的模型 probe。健康检查 MUST NOT 调用模型或业务 MCP；模型 probe MUST 固定连接 revision/config hash、禁止 Tool、单轮、短超时且只返回脱敏结果。

#### Scenario: Readiness检查
- **WHEN** 编排系统调用 Runtime readiness
- **THEN** Runtime 报告协议、SDK、配置、Secret/DB 依赖的脱敏状态且不产生模型费用

#### Scenario: 模型连接Probe
- **WHEN** Python 服务提交通过 RBAC/SSRF 校验的固定模型连接 probe
- **THEN** Runtime 使用 active Secret 完成无 Tool 探测并只返回版本、脱敏 host/model、耗时和稳定错误码
