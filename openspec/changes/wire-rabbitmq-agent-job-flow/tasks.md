## 1. Runtime 装配拆分

- [x] 1.1 重构 `backend/app/bootstrap.py`，拆出 API runtime、worker runtime 和 test runtime 装配路径。
- [x] 1.2 让 API runtime 使用 `RabbitMQPublisher`，并保留测试 runtime 使用 `InMemoryMessageBus`。
- [x] 1.3 让 worker runtime 暴露 `RabbitMQConsumer`，并复用同一个 PostgreSQL repository / AgentExecutor / retry service 装配。
- [x] 1.4 增加配置项控制本地 seed 初始化，例如 `SEED_LOCAL_CONFIG` 或等价开关。
- [x] 1.5 增加装配层测试，证明生产/Compose 默认不会使用 `InMemoryMessageBus` 作为任务通道。

## 2. FastAPI 生命周期初始化

- [x] 2.1 将 migration / seed 初始化移动到 FastAPI startup/lifespan。
- [x] 2.2 将已初始化 container 存放到 `app.state.container`。
- [x] 2.3 修改 DingTalk webhook controller，从 request app state 读取 container，不再在每次请求中调用 `build_container`。
- [x] 2.4 调整 health / ready 检查，确保能暴露 PostgreSQL 和 RabbitMQ 可用性。
- [x] 2.5 增加测试覆盖：多次请求不会重复 build container，migration/seed 保持幂等。

## 3. Agent Debug API

- [x] 3.1 新增 debug Agent job controller，注册 `POST /api/agent/jobs`。
- [x] 3.2 `POST /api/agent/jobs` 复用 `CreateAgentJobService`，执行权限、审计、持久化和 RabbitMQ 投递。
- [x] 3.3 支持请求字段 `message`、`user_id`、`conversation_id`、`project_code`、可选 `idempotency_key`。
- [x] 3.4 新增 `GET /api/agent/jobs/{job_id}` 返回 job 详情、状态、result、error 和时间戳。
- [x] 3.5 新增 `GET /api/agent/jobs/{job_id}/steps`，按创建时间返回 agent steps。
- [x] 3.6 新增 `GET /api/agent/jobs/{job_id}/tool-calls`，返回脱敏工具调用摘要。
- [x] 3.7 增加 debug API 测试：成功创建、幂等创建、未授权拒绝、查询不存在 job 返回 404。

## 4. RabbitMQ Worker 闭环

- [x] 4.1 修改 `backend/app/workers/agent_job_worker.py`，使用 `RabbitMQConsumer` 持续消费 `agent.job.queue`。
- [x] 4.2 确认 worker 成功执行后 ack 当前消息，失败时完成 retry/dead-letter 决策后 ack 当前消息。
- [x] 4.3 确认 retry/dead-letter 发布仍通过 `RabbitMQPublisher`，并记录审计事件。
- [x] 4.4 增加重复 delivery / duplicate claim 测试，证明同一 job 不会并发执行或重复回调。
- [x] 4.5 增加 worker 级测试，证明 RabbitMQ 消息能驱动 `AgentExecutor` 并更新 PostgreSQL job 状态。

## 5. Docker Compose 验证

- [x] 5.1 更新 `docker-compose.yml` 环境变量，启用 runtime RabbitMQ 装配和本地 seed。
- [x] 5.2 增加或更新 README curl 示例：创建 job、查询 job、查询 steps、查询 tool calls。
- [x] 5.3 运行 `docker compose build api-server agent-worker` 验证镜像构建。
- [ ] 5.4 运行 Docker Compose 本地闭环验证：提交问题返回 `job_id`，worker 消费后 job 变为 `SUCCEEDED`。
- [x] 5.5 记录验证命令和预期输出，便于后续接入真实 Claude / 真实工具前复用。

## 6. 最终检查

- [x] 6.1 运行 `make check`，确保格式、lint、类型检查、pytest、unittest 和 OpenSpec 校验通过。
- [x] 6.2 运行 `openspec validate wire-rabbitmq-agent-job-flow`。
- [ ] 6.3 检查新 change 的全部任务状态和文档，确认可进入 apply 阶段。
