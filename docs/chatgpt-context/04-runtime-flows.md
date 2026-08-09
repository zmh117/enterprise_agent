# 当前关键运行链路

> 状态：代码链路已实现；真实模型/MCP/钉钉全链验收仍受环境门禁约束。

## 钉钉到回复

```text
DingTalk Stream
→ dingtalk-runtime
→ channel_ingress_event + channel_ingress_outbox
→ RabbitMQ + channel-dispatch-worker
→ BusinessApplicationResolver（精确环境 deployment）
→ CreateAgentJobService（冻结 Application/Agent/Model/MCP/主体）
→ job_dispatch_outbox
→ RabbitMQ
→ agent-worker
→ TypeScript agent-runtime
→ Claude/DeepSeek + ONES/Data MCP
→ NDJSON Tool events + terminal
→ PostgreSQL artifact/provenance
→ delivery_outbox
→ delivery-dispatch-worker
→ DingTalk
```

群聊始终按当前发送者授权；钉钉主体映射、ONES 外部身份、个人凭据和平台 RBAC 是不同事实，不能互相替代。

## Runtime 请求

Worker 构造 `AgentExecutionRequestV1`，只包含冻结的非敏感上下文：

- Job/invocation/publication/model connection Revision；
- 固定 system prompt、模型、轮次、超时和 Tool call 上限；
- 精确 MCP Server 与 Tool Publication allowlist；
- 用户可见消息、受限附件文本和安全业务上下文；
- Runtime Grant 与 MCP Token 通过协议边界传递，不进入 Prompt。

Runtime 验证 protocol、digest、总字节、Runtime Grant audience/azp/JTI/expiry 和所有冻结 ID。相同 invocation ID + digest 只执行一次；不同 digest 冲突。

## MCP Tool 可调用集合

```text
代码安全 catalog 中存在且 schema hash 一致
∩ MCP Tool Identity/Publication 当前有效
∩ Agent Publication 最大集合
∩ Application Publication 子集
∩ 当前主体/凭据/应用授权
∩ Resource Deployment/Revision 与 Server scope 有效
∩ Job 短期 Token 未过期且未撤销
```

每次 Tool 调用前重新检查紧急撤权。拒绝记录 `DENIED` provenance 和稳定 reason code，但不记录参数、Token、Secret 或完整连接信息。

## 模型连接

Runtime 只解析 Job 固定的模型连接 Revision、config hash 和 active Secret binding；不存在全局 Key、`latest` 或共享 `process.env` fallback。每个 invocation 使用隔离 SDK env/options。

管理端只展示 Provider host、模型、版本、hash、configured/rotation 状态和安全测试结果。API Key 只在有 Secret 权限的轮换请求中提交，不回显。

## 取消、重试和恢复

- 用户/Worker 取消传播到 Runtime `AbortController`；重复取消幂等。
- timeout、429/5xx、transport 等由 Worker 依据稳定 retry class 决定，不由 Runtime自行重试 Job。
- Runtime 写 terminal 后断线，Worker 用相同 invocation ID/digest 重取，不重新执行。
- retry 沿用 Job 冻结 Runtime；不允许 TypeScript → Python 自动 fallback。
- Delivery retry 只重试投递，不重新运行 Agent。

## 排障证据

```text
Runtime client/session
→ Inbox event/outbox
→ RabbitMQ delivery
→ Job/outbox/claim
→ Runtime invocation/version/events/terminal
→ MCP Tool provenance/attempts
→ Artifact
→ Delivery outbox/attempt/chunk
→ adapter response
```

使用 correlation ID、event ID、job ID、invocation ID、tool call ID 和 delivery ID 串联；容器健康不能替代业务链闭环。

详细切换矩阵见 [TypeScript Agent Runtime 切换与运维手册](../typescript-agent-runtime-cutover.md)。
