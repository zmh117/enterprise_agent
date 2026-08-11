## Why

Worker 的 Job 编排、数据库事务和投递不能与高频变化的模型 SDK 放在同一进程。平台需要在保留 Python Runtime 的同时提供隔离的 TypeScript Claude Agent SDK Runtime，并由 Agent Publication 固定选择。

## What Changes

- Worker 保持 RabbitMQ、Job claim、授权、重试、审计、结果和 Delivery 的唯一事实所有权。
- Python 与 TypeScript Runtime 分别承载对应 Claude Agent SDK，通过同一版本化执行协议返回规范事件。
- Runtime Grant 只保护 Worker 到 Runtime 的单次 attempt，绑定 Job、Publication、digest、JTI 和过期时间。
- 两个 Runtime 都只连接固定标准 `tool-mcp`，使用 Agent/Application/Job 冻结的 tool identifier 与 schema hash；MCP 不新增 Token、RBAC 或动态 Server URL。
- 模型连接测试使用无 Tool、单轮、短超时 probe，并保留 SSRF、RBAC、Secret 和 revision/hash 校验。
- 默认 Runtime 为 `python-v1`；每个 Agent Definition 的 Runtime kind 创建后不可修改，单次 attempt/retry 不跨 Runtime fallback。

## Capabilities

### New Capabilities

- `typescript-agent-runtime-service`

### Modified Capabilities

- `claude-agent-runtime-integration`
- `agent-profile-model-connection-management`
- `rabbitmq-agent-job-execution`

## Impact

新增独立 TypeScript Runtime workspace、协议、容器和探针；Worker 通过内部 HTTP 流式协议调用两个 Runtime。旧 API Platform 与工具治理不属于本变更事实源，当前工具边界以标准 `tool-mcp` 主规格为准。
