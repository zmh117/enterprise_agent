## Context

上一轮 MVP 已经建立了 Agent 平台的模块骨架：FastAPI、PostgreSQL 迁移、RabbitMQ 适配器、Agent worker、只读工具、审计权限和测试。但当前运行时仍存在一个关键断点：

```text
api-server 创建 job
  -> 默认发布到 InMemoryMessageBus
  -> agent-worker 是另一个进程
  -> worker 看不到 api-server 内存里的消息
  -> Docker Compose 下 job 不会真实执行
```

因此本 change 的重点不是继续扩展能力，而是把本地可运行闭环打通：

```text
POST /api/agent/jobs
  -> PostgreSQL: agent_session / agent_job / agent_message
  -> RabbitMQ: agent.job.queue
  -> agent-worker: RabbitMQConsumer
  -> AgentExecutor: stub Claude + fake tools
  -> PostgreSQL: result / steps / tool calls / artifact
  -> GET /api/agent/jobs/{job_id}
```

## Goals / Non-Goals

**Goals:**

- Docker Compose 启动后，`api-server` 和 `agent-worker` 通过真实 RabbitMQ 完成跨进程任务执行。
- `api-server` 在生产/Compose 装配中使用 `RabbitMQPublisher`，测试可继续使用 `InMemoryMessageBus`。
- `agent-worker` 在生产/Compose 装配中使用 `RabbitMQConsumer` 持续消费 `agent.job.queue`。
- migration / seed 在应用启动时初始化一次，不在每次请求中重建 container。
- 提供调试 API，允许不依赖钉钉也能提交问题、查询状态、查看步骤和工具调用。
- 保持 stub Claude 和 fake internal tools，确保闭环问题只聚焦在 API / DB / MQ / worker。

**Non-Goals:**

- 不接真实 Claude Code Agent SDK。
- 不接真实 ER / 业务图 / Loki / Redis / 数据库内部工具平台。
- 不实现 Web 管理后台。
- 不实现写操作、审批、沙盒、代码修复或 PR。

## Decisions

### 1. 将依赖装配拆成运行模式

当前 `build_container(settings, migrate=True, seed=False)` 同时用于测试、API 和 worker，且默认使用内存总线。需要把装配拆出明确模式：

```text
test/local-unit:
  InMemoryMessageBus
  FakeInternalApiClient
  StubClaudeCodeAgentClient

compose/runtime:
  RabbitMQPublisher for api-server
  RabbitMQConsumer for agent-worker
  FakeInternalApiClient
  StubClaudeCodeAgentClient
```

建议新增或调整为：

```text
build_api_container(settings)
build_worker_container(settings)
build_test_container(settings)
```

或保留 `build_container`，但显式传入 `message_publisher` / `message_consumer`，避免默认行为误用于生产。

替代方案：继续使用一个 `build_container` 自动判断环境变量。这个方案容易隐藏行为，后续排查困难，因此不推荐。

### 2. 应用启动时初始化数据库

当前 DingTalk controller 每次请求都执行 `build_container(settings, migrate=True, seed=True)`，这会造成重复初始化、连接生命周期混乱，也让 API 依赖装配散落在请求路径里。

目标形态：

```text
FastAPI startup/lifespan
  -> 创建 container
  -> run migrations
  -> seed local config when enabled
  -> app.state.container = container

request handler
  -> request.app.state.container
  -> service.execute(...)
```

这样所有 router 都使用同一个 container，生产行为和测试行为也更可控。

### 3. 调试 API 直接复用 job application service

调试 API 不应该绕过权限、审计、持久化或队列投递。`POST /api/agent/jobs` 应该构造与 DingTalk 类似的 command，只是 source 使用 `debug_api`，默认用户使用配置中的本地调试用户。

建议请求：

```json
{
  "message": "帮我查订单 MO20260627001 为什么一直待领料",
  "user_id": "local-user",
  "conversation_id": "debug-conversation",
  "project_code": "default",
  "idempotency_key": "optional-client-key"
}
```

响应：

```json
{
  "job_id": "...",
  "status": "PENDING",
  "message": "Task accepted, analysis is starting."
}
```

查询接口：

```text
GET /api/agent/jobs/{job_id}
  -> job 基本信息、状态、result、error_message、created_at、started_at、finished_at

GET /api/agent/jobs/{job_id}/steps
  -> agent_step 列表

GET /api/agent/jobs/{job_id}/tool-calls
  -> agent_tool_call 列表，返回摘要，不返回未脱敏 raw payload
```

### 4. Worker 使用 RabbitMQConsumer 持续消费

worker 入口应当装配：

```text
RabbitMQConsumer(settings.rabbitmq_url, settings.queue)
AgentJobWorker.handle(message)
```

消费语义：

- 成功执行：ack。
- 可重试失败：记录 retry metadata，发布 retry 消息或重新路由，然后 ack 当前消息。
- 不可重试或超限：标记失败，发布 dead-letter，ack 当前消息。
- handler 抛出未处理异常时不应无限吞掉消息，需要清晰记录日志和审计。

当前 `RabbitMQConsumer` 只消费 `job_queue` 并在 handler 返回后 ack。实现时要确认 handler 内部完成 retry/dead-letter 决策，避免 RabbitMQ 自动重复投递造成同一 job 乱序重试。

### 5. 本 change 不扩大模型和工具范围

本次闭环仍使用：

```text
StubClaudeCodeAgentClient
FakeInternalApiClient
```

这是有意为之。否则一旦 Docker 验证失败，会同时混入 Claude 凭证、SDK 行为、内部工具网络、Loki/Redis/DB 策略等不确定性。

## Risks / Trade-offs

- [Risk] migration / seed 在多个进程同时启动时重复执行或冲突 -> 使用幂等 SQL，启动失败要清晰暴露，测试覆盖重复启动。
- [Risk] API 和 worker 使用不同配置导致查不到同一数据库 -> Docker Compose 中统一 `DATABASE_DSN`，ready 检查暴露 DB/RabbitMQ 状态。
- [Risk] RabbitMQ 消息被重复投递 -> 依赖 job claim 幂等锁，重复 delivery 不应重复执行或重复回调。
- [Risk] retry queue 只是发布但没有消费策略 -> 本 change 至少要明确当前 retry 行为；如果不实现 delayed retry 消费，也必须让 dead/retry 状态可查询并记录。
- [Risk] 调试 API 绕过权限 -> 调试 API 必须复用 `CreateAgentJobService` 和 `PermissionService`。
- [Risk] 容器内 migration 路径或 Skill 路径不正确 -> Docker Compose 验证必须覆盖实际容器路径。

## Migration Plan

1. 调整 container 装配，区分 API publisher、worker consumer、测试内存总线。
2. 调整 FastAPI lifespan，在启动时初始化 DB migration / seed 和 app container。
3. 调整 DingTalk controller，从 `request.app.state.container` 获取服务，不在请求中重新 build。
4. 新增 debug Agent job API controller 和查询服务。
5. 调整 worker，使用 `RabbitMQConsumer` 持续消费真实 `agent.job.queue`。
6. 增加 repository 查询方法：job detail、steps、tool calls。
7. 更新 Docker Compose 验证文档和 curl 示例。
8. 运行本地检查和 Docker Compose 端到端验证。

Rollback：如果 RabbitMQ 闭环出现问题，可以保留测试内存装配，临时关闭 debug API 或 worker 服务；数据库中的 job 仍可查询，失败任务可重新投递。

## Open Questions

- retry queue 是否在本 change 中实现延迟再消费，还是先只验证 normal queue 闭环并保留 retry/dead-letter 记录？
- 调试 API 是否允许外部传 `user_id`，还是固定使用 `DEBUG_AGENT_USER_ID`，避免本地误绕权限？
- Docker Compose 验证是否要求真实启动服务并执行 curl，还是以构建和自动化测试为准？
