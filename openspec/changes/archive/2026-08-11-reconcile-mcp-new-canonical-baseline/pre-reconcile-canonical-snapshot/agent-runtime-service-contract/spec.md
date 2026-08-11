# agent-runtime-service-contract Specification

## Purpose
定义纯编排 Worker 与 Python、TypeScript Agent Runtime 的服务边界、版本化执行协议、幂等恢复、取消、健康检查、镜像依赖和标准 MCP 调用约束。

## Requirements

### Requirement: Python与TypeScript Runtime必须是独立服务
系统 SHALL 提供 `python-v1` 与 `typescript-v1` 两个独立 Agent Runtime 服务；每个服务只执行一次 Agent attempt，不得消费 RabbitMQ、claim Job、决定 retry、写 Job/Delivery 业务状态或直接投递结果。

#### Scenario: Worker调用Python Runtime
- **WHEN** Job 固定的 runtime kind 为 `python-v1`
- **THEN** Worker 通过内部 Runtime client 调用 `python-agent-runtime`
- **AND** Python Runtime 使用 Python Claude Agent SDK 完成本次 attempt

#### Scenario: Worker调用TypeScript Runtime
- **WHEN** Job 固定的 runtime kind 为 `typescript-v1`
- **THEN** Worker 通过内部 Runtime client 调用 `typescript-agent-runtime`
- **AND** TypeScript Runtime 使用 TypeScript Claude Agent SDK 完成本次 attempt

#### Scenario: Runtime尝试拥有业务状态
- **WHEN** 检查任一 Runtime 的队列订阅、数据库角色和容器配置
- **THEN** Runtime 不具备 RabbitMQ consumer 或 Job/Delivery 写权限

### Requirement: 双Runtime必须实现同一版本化执行协议
两个 Runtime MUST 实现同一份版本化执行、事件、取消、终态恢复和错误 schema。协议 SHALL 固定 runtime kind、invocation、attempt、request digest、Publication/hash、模型连接、执行限制、Tool allowlist 和 correlation ID；Runtime URL 不得来自 Agent、Application、外部请求或模型输出。

#### Scenario: 相同合约用例运行于两个Runtime
- **WHEN** contract suite 对 Python 与 TypeScript Runtime 执行同一 accepted、tool、completed、failed 和 cancel fixture
- **THEN** 两端均返回 schema 合法、sequence 单调且唯一终态的结果

#### Scenario: Runtime协议版本不受支持
- **WHEN** Worker 或 Runtime 收到不受支持的协议版本、未知 runtime kind 或超限事件
- **THEN** 调用以稳定协议错误失败关闭且不执行模型

#### Scenario: 请求尝试指定任意Runtime地址
- **WHEN** Agent/Application 配置或外部 payload 包含自定义 Runtime URL
- **THEN** 系统忽略或拒绝该字段，只使用平台固定的 Runtime client registry

### Requirement: Runtime执行必须支持幂等终态恢复
Runtime MUST 以 `invocation_id + request_digest` 标识一次逻辑执行，并 SHALL 保存有界、脱敏的终态以支持 Worker 断线或本地事务失败后的恢复。相同 invocation 与不同 digest 的请求 MUST 被拒绝，恢复不得启动第二次模型执行。

#### Scenario: Runtime完成后Worker提交失败
- **WHEN** Runtime 已产生 completed 终态但 Worker 的本地 Job 事务回滚
- **THEN** Worker 使用相同 invocation/digest 获取既有终态并重新提交本地事务
- **AND** Runtime 不再次调用模型

#### Scenario: 重复请求摘要冲突
- **WHEN** 相同 invocation ID 携带不同 request digest 到达 Runtime
- **THEN** Runtime 返回不可重试的 digest conflict 且不复用或覆盖旧终态

#### Scenario: Runtime在模型执行中重启
- **WHEN** 新 Runtime 进程收到相同 invocation/digest，且持久化 claim 表明旧进程已开始该 invocation 但尚未保存终态
- **THEN** Runtime 保存并返回 `runtime_orphaned_invocation` 不可自动重试终态，且不得再次调用模型
- **AND** 该失败只能由操作者创建新的 Job/invocation 显式重试，不得在原 Job attempt 内自动重放

### Requirement: Runtime取消与超时必须产生确定终态
Worker SHALL 能通过版本化协议取消运行中的 attempt；Runtime MUST 将取消、墙钟超时、最大轮次和最大 Tool Call 映射为稳定错误码和 retry class，并最终只产生一个终态。

#### Scenario: Worker取消运行中attempt
- **WHEN** Job 被取消、Worker shutdown 或 attempt 超过固定墙钟时间
- **THEN** Worker 向原 Runtime 发送取消请求
- **AND** Runtime 中止 SDK 会话并返回或保存一个规范取消/超时终态

#### Scenario: 取消与完成并发
- **WHEN** cancel 与 SDK completed 几乎同时发生
- **THEN** invocation ledger 只接受一个终态且后续读取返回同一结果

### Requirement: Runtime健康与模型探测必须语言对等
两个 Runtime SHALL 提供 health、readiness、version 和无 Tool 模型连接 probe。health/readiness MUST NOT 调用模型或 MCP Tool；probe MUST 使用固定模型连接 revision/hash、单轮、安全合成输入和短超时，并返回脱敏结果。

#### Scenario: 平台聚合双Runtime readiness
- **WHEN** 管理员读取平台 readiness
- **THEN** 响应分别展示 `python-v1` 与 `typescript-v1` 的协议、SDK/CLI 和配置状态
- **AND** 检查不产生外部模型费用

#### Scenario: 显式测试模型连接
- **WHEN** 授权管理员对任一 Runtime 兼容的模型连接发起 probe
- **THEN** 对应 Runtime 禁用 Tool 并返回版本、脱敏 provider host、model、耗时和稳定错误码

### Requirement: Runtime镜像必须隔离SDK依赖
`agent-worker` 镜像 MUST 不包含 Python/TypeScript Agent SDK 或 Claude Code CLI。Python SDK 与其所需 CLI SHALL 只安装在 Python Runtime 镜像；TypeScript SDK SHALL 只安装在 TypeScript Runtime 镜像。

#### Scenario: 检查Worker镜像内容
- **WHEN** CI 对最终 `agent-worker` 镜像执行依赖和可执行文件检查
- **THEN** Python Claude Agent SDK、TypeScript Claude Agent SDK 和 Claude Code CLI 均不存在

#### Scenario: 检查Runtime镜像内容
- **WHEN** CI 分别检查两个 Runtime 镜像
- **THEN** 每个镜像只包含其实现所需的 SDK/CLI 和协议产物

### Requirement: 双Runtime必须共享无专用密钥的标准MCP工具服务
系统 SHALL 使用官方 MCP SDK 提供单一标准 MCP Tool Server，供 Python 与 TypeScript Runtime 调用。系统 MUST 删除 `runtime-tool-mcp`、其 HS256 signing key、access token issuer/verifier 和专用 claims；标准 MCP Tool Server MUST NOT 引入替代 Token、签名密钥、治理控制面或任意 Server URL。

#### Scenario: Python与TypeScript调用相同工具
- **WHEN** 两个 Runtime 分别执行包含同一冻结 Tool 的 Job
- **THEN** 两端通过同一标准 MCP Tool Server 和 Tool schema 获得等价安全结果

#### Scenario: MCP服务部署边界
- **WHEN** 检查 Compose、端口和网络配置
- **THEN** 标准 MCP Tool Server 只在固定私有网络可达且不映射宿主机端口
- **AND** 服务不挂载 Runtime Tool signing key 或要求 MCP Bearer Token

#### Scenario: 请求提供任意MCP地址
- **WHEN** Agent、Application、用户 payload 或模型输出包含自定义 MCP Server URL
- **THEN** 两个 Runtime 均拒绝该地址，只使用平台部署时固定的标准 MCP Tool Server

#### Scenario: 旧Runtime Tool配置残留
- **WHEN** 部署或代码扫描发现 `runtime-tool-mcp` 服务、`RUNTIME_TOOL_MCP_*` 配置、HS256 issuer/verifier 或 signing key secret
- **THEN** 发布检查失败，直到旧服务及密钥链路被完全删除

### Requirement: Runtime Grant不得扩展为MCP认证
Worker→Runtime 的 Runtime Grant SHALL 继续只绑定执行、取消和终态恢复请求。Runtime Grant 的私钥、公钥或 Bearer Token MUST NOT 传递给标准 MCP Tool Server，也不得作为替代的 MCP signing key。

#### Scenario: Runtime调用MCP工具
- **WHEN** Python 或 TypeScript Runtime 调用标准 MCP Tool Server
- **THEN** 请求不携带 Runtime Grant，MCP Tool Server 也不读取 Runtime Grant key pair

#### Scenario: Worker调用Runtime
- **WHEN** Worker 创建或取消一次 Runtime invocation
- **THEN** 对应 Runtime 仍校验绑定该 Job、Publication、invocation 和 request digest 的短期 Runtime Grant
