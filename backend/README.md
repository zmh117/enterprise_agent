# Enterprise Agent 后端 MVP

这个后端实现企业级只读诊断 Agent 的 MVP。当前阶段重点是跑通真实执行链路：

```text
DingTalk / Debug API
  -> FastAPI api-server
  -> PostgreSQL 16 持久化 Agent 任务
  -> RabbitMQ agent.job.queue
  -> agent-worker 消费任务
  -> Claude Code Agent Runtime 包装层
  -> 只读内部工具
  -> 生成诊断报告
  -> 持久化 steps / tool-calls / artifact / audit
```

默认 Claude runtime 使用 stub，设置 `FEATURE_REAL_CLAUDE=true` 后可切换到真实 Claude Agent SDK。内部工具平台当前仍使用 fake client，下一步再接真实内网工具平台。

## 模块边界

- `dingding`：钉钉 webhook、签名校验、消息解析、结果回调。
- `job`：Agent 任务生命周期、状态流转、重试策略、调试 API。
- `message_bus`：消息发布和消费接口，RabbitMQ 是基础设施实现。
- `agent`：构造上下文、加载 skill、调用 Claude Runtime、保存结果。
- `internal_tools`：只读工具到内部 API 平台的适配，不直连真实数据库/Redis/Loki。
- `permission`：用户、项目、工具白名单。
- `audit`：任务、权限、工具调用、失败和最终报告审计。

## 只读边界

MVP 工具：

- `get_er_context`
- `get_business_flow_context`
- `query_loki`
- `query_database`
- `query_redis_get`
- `query_redis_scan`

安全限制：

- SQL 只允许 `SELECT` / `WITH`。
- Redis 只允许 `get` 和有限制的 `scan`。
- Loki 必须限制服务、时间范围和返回行数。
- 不暴露改代码、提交 PR、重启服务、执行更新 SQL、删除 Redis key、发版、沙盒执行。

## 本地命令

安装依赖：

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

运行检查：

```bash
make check
```

启动 Compose：

```bash
docker compose up --build
```

本地启动 API：

```bash
.venv/bin/python -m uvicorn app.main:create_app --factory --app-dir backend --host 0.0.0.0 --port 8000
```

本地启动 worker：

```bash
PYTHONPATH=backend .venv/bin/python -m app.workers.agent_job_worker
```

## 调试 API

创建任务：

```bash
curl -s -X POST http://127.0.0.1:8000/api/agent/jobs \
  -H 'content-type: application/json' \
  -d '{
    "message": "帮我查一下订单 MO20260627001 为什么一直待领料",
    "user_id": "local-user",
    "conversation_id": "debug-conversation",
    "project_code": "default",
    "idempotency_key": "demo-order-001"
  }'
```

查询任务：

```bash
curl -s http://127.0.0.1:8000/api/agent/jobs/job_xxx
```

查询步骤：

```bash
curl -s http://127.0.0.1:8000/api/agent/jobs/job_xxx/steps
```

查询工具调用：

```bash
curl -s http://127.0.0.1:8000/api/agent/jobs/job_xxx/tool-calls
```

## 环境变量

- `DATABASE_DSN`：PostgreSQL DSN。
- `RABBITMQ_URL`：RabbitMQ URL。
- `APP_STARTUP_MIGRATE`：启动时执行 migration，默认 `true`。
- `SEED_LOCAL_CONFIG`：启动时写入本地工具、数据源和权限 seed。
- `DEBUG_AGENT_USER_ID`：调试 API 默认用户。
- `DINGTALK_SECRET`：钉钉机器人签名密钥。
- `DINGTALK_CALLBACK_URL`：结果回调地址。
- `DINGTALK_CALLBACK_HOST_ALLOWLIST`：回调 host 白名单。
- `INTERNAL_API_BASE_URL`：内部 API 平台地址。
- `CLAUDE_MODEL`：Claude 模型名。
- `FEATURE_REAL_CLAUDE`：是否启用真实 Claude。
- `ANTHROPIC_API_KEY`：真实 Claude runtime 的 Anthropic API key，启用时必填。
- `ANTHROPIC_BASE_URL`：可选 Anthropic 兼容网关地址。
- `AGENT_MAX_RETRY_COUNT`：最大重试次数。
- `AGENT_RETRY_DELAY_SECONDS`：重试延迟秒数。
- `AGENT_TIMEOUT_SECONDS`：Agent 执行超时时间。
- `AGENT_MAX_TURNS`：Claude Agent SDK 最大轮次，默认 `12`。
- `MAX_TOOL_RESPONSE_CHARS`：工具响应摘要最大长度。
- `MAX_LOKI_MINUTES` / `MAX_LOKI_LINES` / `REDIS_SCAN_LIMIT`：只读工具边界。

## 真实 Claude Runtime

真实 runtime 使用 Python 包 `claude-agent-sdk`，导入名为 `claude_agent_sdk`。SDK 底层需要 Node.js 和 Claude Code CLI。Docker 镜像会安装：

```text
nodejs
npm
@anthropic-ai/claude-code
```

启用方式：

```bash
cp .env.example .env
# 编辑 .env，把 your-deepseek-api-key 换成真实 DeepSeek API Key
docker compose up --build
```

本机直跑 worker 时需要本机能找到 CLI：

```bash
which claude
```

手动验证路径：

```bash
curl -s -X POST http://127.0.0.1:8000/api/agent/jobs \
  -H 'content-type: application/json' \
  -d '{
    "message": "帮我查一下订单 MO20260627001 为什么一直待领料",
    "user_id": "local-user",
    "conversation_id": "debug-conversation",
    "project_code": "default",
    "idempotency_key": "real-claude-demo-001"
  }'
```

然后查询：

```bash
curl -s http://127.0.0.1:8000/api/agent/jobs/job_xxx
curl -s http://127.0.0.1:8000/api/agent/jobs/job_xxx/steps
curl -s http://127.0.0.1:8000/api/agent/jobs/job_xxx/tool-calls
```

预期：

- job 最终变为 `SUCCEEDED`。
- `result` 不是 stub 模板中的 `read-only diagnostic analysis completed`。
- steps 包含 `Model execution completed`。
- tool calls 只包含 `mcp__internal__*` 对应的只读工具摘要。

## 队列

- `agent.job.queue`：正常 Agent 任务。
- `agent.job.retry.queue`：可重试失败。
- `agent.job.dead.queue`：最终失败死信。

应用服务只依赖 `MessagePublisher` / `MessageConsumer`，RabbitMQ 细节在 `modules/message_bus/infrastructure`。

## 数据表

执行链路：

- `agent_session`
- `agent_job`
- `agent_message`
- `agent_step`
- `agent_tool_call`
- `agent_artifact`
- `audit_event`

配置表：

- `tool_definition`
- `integration_connector`
- `datasource_registry`
- `permission_policy`

迁移文件在 `backend/migrations`，本地 seed 在 `backend/seeds/local_seed.sql`。

## 当前测试覆盖

- 钉钉签名成功 / 失败。
- 重复消息幂等。
- 未授权用户拒绝。
- debug API 创建、幂等创建、查询 job、steps、tool calls。
- Compose runtime 使用 RabbitMQPublisher / RabbitMQConsumer，不使用内存队列。
- startup 只初始化一次 container，请求不重复 build。
- worker 消费消息后更新 job 状态，重复 delivery 不重复回调。
- feature flag 开启时生产 runtime 注入 `RealClaudeCodeAgentClient`，测试 runtime 仍使用 stub。
- fake SDK 覆盖真实 runtime 的权限配置、工具循环、错误映射、timeout 和 tool event 解析。
- opt-in integration 测试默认 skip，只有配置真实 key 和 CLI 时运行。
- 只读 SQL / Redis / Loki 策略。
- 工具调用审计和报告产物持久化。
