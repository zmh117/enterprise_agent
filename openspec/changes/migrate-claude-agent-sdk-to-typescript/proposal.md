## Why

当前 `agent-worker` 在 Python 进程内直接加载 `claude_agent_sdk`，把 Job 编排、数据库事务、授权复核与高频变化的 Node/Claude SDK 执行耦合在同一镜像和故障域中。现有 `mcp_dev` 已验证独立 TypeScript Runtime 的主要技术路径，应将其中的执行面以受控方式移植到当前 `mcp_new`，同时保留当前分支的治理、Job 和投递事实源。

## What Changes

- 新增独立 `agent-runtime` TypeScript 服务，精确锁定官方 `@anthropic-ai/claude-agent-sdk`，负责单次模型执行、SDK 事件归一化、MCP 会话、超时和取消。
- Python `agent-worker` 继续负责 RabbitMQ 消费、Job claim、业务授权、不可变 Publication、重试、审计、结果事务和 Delivery Outbox，并通过版本化内部协议调用 TypeScript Runtime。
- 使用短期、绑定 Job/attempt/request digest 的 Runtime Grant；模型 Key、MCP Token 和 Secret 明文不得进入 RabbitMQ、Job 快照、Prompt、日志、Runtime ledger 或响应。
- 增加显式 Runtime 选择：系统长期保留 Python 与 TypeScript 两条执行路径；未命中显式 TypeScript 门禁的新 Job 默认使用 `python-v1`，单次 attempt 不允许自动跨 Runtime fallback。
- 将模型连接测试委托给 TypeScript Runtime 的无 Tool、单轮、短超时 probe，并保持现有 SSRF、RBAC、Secret 和版本固定约束。
- 增加跨语言契约、错误分类、敏感字段、重启恢复、Compose 健康和完整钉钉链路验证。
- 不合并 `mcp_dev` 的前端裁剪、控制面退役或其他平台重构。
- Python `claude-agent-sdk`、进程内真实执行路径和 Worker 镜像中的 Claude CLI 作为正式受支持的 `python-v1` Runtime 长期保留；本变更不得以灰度完成为由删除它们。

## Capabilities

### New Capabilities

- `typescript-agent-runtime-service`: 独立 TypeScript Runtime 的内部执行协议、服务授权、SDK/MCP 执行、事件归一化、健康检查、部署和迁移门禁。

### Modified Capabilities

- `claude-agent-runtime-integration`: 在现有 Python Runtime 旁新增独立 TypeScript Runtime，同时保持只读工具、执行策略、失败分类和安全 provenance，并固定 Python 为默认选择。
- `agent-profile-model-connection-management`: 模型连接真实测试改由 TypeScript Runtime 执行，并继续固定连接 revision/config hash、加密 Secret 和 SSRF 防护。
- `rabbitmq-agent-job-execution`: 明确 Python Worker 仍是 Job 状态、重试和 Delivery 事实源，TypeScript Runtime 不直接消费业务队列或写业务表。

## Impact

- 新增 `agent-runtime/` TypeScript workspace、协议 schema、lockfile、Dockerfile、Compose 服务和内部认证配置。
- 调整 Python Runtime client、`AgentExecutor`、Worker 装配、模型连接 probe、readiness、配置和测试。
- Worker/Runtime 间增加内部流式 HTTP 调用，但不改变外部 API、RabbitMQ Job 消息、PostgreSQL Job schema 和钉钉投递契约。
- 长期同时维护受显式 gate 控制的 Python/TypeScript 路径；真实 E2E 和安全扫描是启用 TypeScript Application 的前置条件，不改变 Python 默认值，也不授权删除 Python 路径。
