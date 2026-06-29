# 企业级只读诊断 Agent 平台

这是一个企业内部只读诊断 Agent 平台 MVP。当前目标是先跑通诊断执行链路，而不是做“大而全 Agent 平台”。

```text
钉钉 / Debug API
  -> FastAPI api-server
  -> PostgreSQL 16 持久化任务
  -> RabbitMQ 投递 agent.job.queue
  -> agent-worker 消费任务
  -> Claude Agent Runtime
  -> 只读内部工具
  -> 生成诊断报告
  -> 持久化 steps / tool-calls / artifact / audit
```

## 当前能力

- 真实 PostgreSQL / RabbitMQ / worker 闭环。
- Debug API 创建和查询 Agent job。
- 钉钉 webhook 接入。
- 只读工具策略：ER、业务流、Loki、数据库、Redis。
- 审计、重试、死信队列。
- `FEATURE_REAL_CLAUDE=false` 默认 stub runtime。
- `FEATURE_REAL_CLAUDE=true` 可切换真实 Claude Agent SDK runtime。

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
make check
```

启动本地服务：

```bash
docker compose up --build
```

创建调试任务：

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
curl -s http://127.0.0.1:8000/api/agent/jobs/job_xxx/steps
curl -s http://127.0.0.1:8000/api/agent/jobs/job_xxx/tool-calls
```

## 真实 Claude Runtime

默认不启用真实 Claude。启用时需要：

```bash
cp .env.example .env
# 编辑 .env，把 your-deepseek-api-key 换成真实 DeepSeek API Key
docker compose up --build
```

Docker 镜像会安装 Node.js 和 Claude Code CLI。本机直跑 worker 时，需要本机可执行：

```bash
which claude
```

更多后端细节见 [backend/README.md](/Users/mhz/Develop/enterprise_agent/backend/README.md)。
