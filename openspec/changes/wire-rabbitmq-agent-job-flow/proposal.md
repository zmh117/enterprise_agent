## Why

当前 MVP 已经有模块边界、持久化表、RabbitMQ 适配器、Agent worker 和测试，但运行时仍默认使用内存队列、fake 工具和 stub Agent，导致 Docker Compose 启动后不能形成真实跨进程任务闭环。现在最重要的是先把“提交问题 -> PostgreSQL 落库 -> RabbitMQ 投递 -> worker 消费 -> 保存报告 -> 查询结果”跑通，形成后续接入真实 Claude 和真实内部工具前的稳定基线。

## What Changes

- 将 `api-server` 的 Agent job 创建路径切换到 `RabbitMQPublisher`，不再把生产/Compose 路径投递到 `InMemoryMessageBus`。
- 将 `agent-worker` 切换到 `RabbitMQConsumer`，真正消费 `agent.job.queue` 并驱动 `AgentExecutor`。
- 调整应用启动装配：数据库 migration / seed 在应用生命周期初始化时执行，不在每次 DingTalk webhook 请求中重新 `build_container`。
- 增加调试 API，用于本地和 Docker Compose 环境直接验证 Agent job 闭环：
  - `POST /api/agent/jobs`
  - `GET /api/agent/jobs/{job_id}`
  - `GET /api/agent/jobs/{job_id}/steps`
  - `GET /api/agent/jobs/{job_id}/tool-calls`
- 保留 stub Claude 和 fake internal tools 作为本次闭环的可控依赖；本 change 不接真实 Claude Code Agent SDK，也不接真实 ER / Loki / Redis / 数据库工具平台。
- 增加 Docker Compose 级验证路径，能用 `curl` 证明：提交问题返回 `job_id`，worker 消费后 job 变为 `SUCCEEDED`，查询结果可看到诊断报告。

非目标：

- 不实现真实 Claude Code Agent SDK 调用。
- 不实现真实内部 API 平台、Loki、Redis、数据库或 ER / 业务图查询。
- 不实现 Web 管理后台。
- 不扩展自动改代码、审批、沙盒、PR 等写操作能力。

## Capabilities

### New Capabilities
- `rabbitmq-agent-job-execution`: 真实 RabbitMQ Agent job 投递、消费、重试/死信路由、跨进程 worker 执行和 Docker Compose 闭环。
- `agent-job-debug-api`: 面向本地调试和验证的 Agent job 创建、状态查询、步骤查询、工具调用查询 API。

### Modified Capabilities
- None.

## Impact

- 影响 `backend/app/bootstrap.py` 的依赖装配方式，需要区分生产 RabbitMQ 装配和测试内存装配。
- 影响 `backend/app/main.py` 的应用启动生命周期、migration / seed 初始化和 router 注册。
- 影响 `backend/app/workers/agent_job_worker.py`，worker 需要使用 `RabbitMQConsumer` 持续消费真实队列。
- 新增 Agent debug API controller / application service / repository 查询方法。
- 影响 Docker Compose 验证方式，需要确保 `api-server`、`agent-worker`、`postgres`、`rabbitmq` 能真实协同。
- 测试需要覆盖内存单元测试和 Docker/集成验证说明；真实外部 Claude 和内部工具仍由后续 change 处理。
