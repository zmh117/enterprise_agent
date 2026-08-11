## Why

当前 `agent-worker` 同时承担 RabbitMQ/Job 编排和 Python Claude Agent SDK 执行，而 TypeScript SDK 运行在独立服务中，导致两个 Agent Runtime 的部署边界、选择规则和故障语义不一致。现有 `runtime-tool-mcp` 又为 Runtime 工具调用增加了专用适配服务和 HS256 signing key。需要先把 Worker 收敛为语言无关的纯编排服务，把 Python、TypeScript 都变成可独立部署的 Runtime，并用官方 MCP SDK 的标准服务替代该专用适配层；更大范围的 MCP 平台迁移继续作为后续变更。

## What Changes

- **BREAKING**：`agent-worker` 不再进程内执行 Python Claude Agent SDK，也不再安装任一 Agent SDK 或 Claude Code CLI；它只消费队列、claim Job、调用固定 Runtime、处理重试/终态、持久化结果与 Tool 事件并创建 Delivery Outbox。
- 新增独立 `python-agent-runtime` 服务与镜像，封装 Python `claude-agent-sdk` 及其所需 Claude Code CLI；保留独立 `typescript-agent-runtime` 服务与镜像，封装 `@anthropic-ai/claude-agent-sdk`。
- 两个 Runtime 实现相同的版本化内部执行契约，覆盖执行、流式事件、取消、超时、错误分类、幂等终态恢复、health/readiness/version 和模型连接探测。
- Agent Definition/Publication 增加不可变 `runtime_kind`；内置并开放两个可独立编辑、校验和发布的 Agent：现有 Python Agent 与新增 TypeScript Agent。
- Business Application 继续选择精确的 Agent Publication；Job 从该不可变 Publication 派生并冻结 Runtime，retry 保持原 Runtime，Runtime 故障不得自动跨实现 fallback。
- **BREAKING**：移除以环境变量或 Application allowlist 直接选择 Runtime 的迁移门禁；Application 不再维护与 Agent Publication 重复的 Runtime 选择项。
- **BREAKING**：永久删除 `runtime-tool-mcp` 服务、专用协议适配、HS256 access token 签发/校验、`RUNTIME_TOOL_MCP_*` 配置和 signing key；不得保留兼容服务或双写路径。
- 新增一个直接使用官方 MCP SDK 的轻量标准 MCP Tool Server，Python/TypeScript Runtime 共用；它只部署在固定私有网络、不暴露宿主机端口，不引入 MCP Token、签名密钥、服务发现或新的治理/授权层。
- 保留 Worker→Runtime 的 Runtime Grant；它只认证和绑定 Agent 执行请求，与已经删除的 MCP signing key 无关。
- 保留现有 DingTalk ingress、Application 路由、RabbitMQ、Job、Delivery Outbox 与配置交付渠道闭环。
- 本变更不退役 API Capability、Handler、Connection、Resource Mapping 或 Internal API Platform；这些控制面能力的永久退役统一进入后续 MCP 专项变更。新标准 MCP Tool Server 不得继续依赖 `runtime-tool-mcp` 专用 claims 或把这些控制面模型复制为新的 MCP 治理层。

## Capabilities

### New Capabilities

- `agent-runtime-service-contract`: 定义 Python 与 TypeScript Agent Runtime 的统一版本化协议、独立服务边界、幂等恢复、就绪、模型探测及共享标准 MCP Tool Server 边界。

### Modified Capabilities

- `claude-agent-runtime-integration`: 将 Python/TypeScript Claude Agent SDK 都收敛到独立 Runtime 服务，由 Agent Publication 决定 Runtime，并以官方 MCP SDK 标准服务替代带专用密钥的 `runtime-tool-mcp`。
- `rabbitmq-agent-job-execution`: 明确纯编排 Worker 对 Runtime 调用、本地终态提交、消息确认、retry 和重复消息恢复的责任边界。
- `multi-agent-configuration`: 增加不可变 Runtime 类型、两个内置 Agent 及其独立编辑/校验/发布能力。
- `business-application-publication`: 要求应用选择精确且可部署的 Agent Publication，并从中派生 Runtime，不维护第二个 Runtime 选择项。

## Impact

- 后端：Job 创建/快照、Agent Definition/Publication schema、Worker 装配、Runtime client、标准 MCP Tool Server、重试与终态事务、Agent/Application 管理 API；删除 `runtime-tool-mcp` 模块及 Token 签发/校验代码。
- 前端：Agent 发布页支持 Python 与 TypeScript 两个 Agent；Application 编辑页展示并选择带 Runtime 标识的 Agent Publication。
- 部署：新增 `python-agent-runtime` 与标准 MCP Tool Server 服务/镜像，调整 `agent-worker` 镜像依赖，继续使用现有 TypeScript Runtime 服务并增加双 Runtime readiness；删除 `runtime-tool-mcp` 服务、secret 和环境变量。
- 依赖：Python SDK/CLI 从公共后端/Worker 依赖移入 Python Runtime 镜像；TypeScript SDK 只保留在 TypeScript Runtime 镜像。
- 数据：需要迁移 Agent/Publication Runtime 字段并为两个内置 Agent 建立可重复执行的 seed；历史 Publication 和在途 Job 需要确定性回填与兼容检查。
- 运行链路：`DingTalk -> Application Publication -> Agent Publication -> Job -> agent-worker -> selected Runtime -> Job result -> Delivery Outbox -> configured channel`。
- 规格关系：本变更取代 `migrate-claude-agent-sdk-to-typescript` 中“Python SDK 长期保留在 Worker”和“环境/Application 灰度门禁选择 Runtime”的拓扑决策；实施前必须协调未完成任务，避免并存冲突。
