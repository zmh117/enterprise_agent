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
- `FEATURE_REAL_INTERNAL_TOOLS=false` 默认 fake 内部工具。
- `FEATURE_REAL_INTERNAL_TOOLS=true` 可切换 HTTP Internal API Platform、本地 mock 平台或本地 Loki 平台。

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
curl --noproxy '*' -s -X POST http://127.0.0.1:8000/api/agent/jobs \
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
curl --noproxy '*' -s http://127.0.0.1:8000/api/agent/jobs/job_xxx
curl --noproxy '*' -s http://127.0.0.1:8000/api/agent/jobs/job_xxx/steps
curl --noproxy '*' -s http://127.0.0.1:8000/api/agent/jobs/job_xxx/tool-calls
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

## 内部工具平台模式

### fake 模式

默认 fake，不访问网络：

```env
FEATURE_REAL_INTERNAL_TOOLS=false
```

### mock 模式

使用本地 mock HTTP 平台验证工具链路，不依赖 DeepSeek 或真实 Loki：

```env
FEATURE_REAL_CLAUDE=false
FEATURE_REAL_INTERNAL_TOOLS=true
INTERNAL_API_BASE_URL=http://mock-internal-api-platform:9000
INTERNAL_API_AUTH_TOKEN=
```

启动：

```bash
docker compose --profile mock-tools up -d --build
```

### local-loki 模式

使用真实 Claude/DeepSeek，加本地开发用 Internal API Platform 查询宿主机 Loki。

宿主机 Loki 地址：

```text
http://localhost:3100
```

容器内访问宿主机 Loki 要使用：

```env
LOKI_BASE_URL=http://host.docker.internal:3100
```

启动：

```bash
FEATURE_REAL_CLAUDE=true \
FEATURE_REAL_INTERNAL_TOOLS=true \
INTERNAL_API_BASE_URL=http://local-internal-api-platform:9000 \
LOKI_BASE_URL=http://host.docker.internal:3100 \
docker compose --profile local-tools up -d --build local-internal-api-platform api-server agent-worker
```

local-loki 第一版只真实查询 Loki：

```text
POST /tools/loki/query -> Loki /loki/api/v1/query_range
```

其它工具行为：

```text
POST /tools/context/er            -> local placeholder
POST /tools/context/business-flow -> local placeholder
POST /tools/database/query        -> tool_not_configured
POST /tools/redis/get             -> tool_not_configured
POST /tools/redis/scan            -> tool_not_configured
```

### 真实 Internal API Platform 模式

接生产或内网真实 Internal API Platform：

```env
FEATURE_REAL_INTERNAL_TOOLS=true
INTERNAL_API_BASE_URL=https://internal-api.example.com
INTERNAL_API_AUTH_TOKEN=真实内部平台token
INTERNAL_API_TIMEOUT_SECONDS=10
INTERNAL_API_MAX_RESPONSE_CHARS=4000
```

MVP 只读 endpoint：

```text
POST /tools/context/er
POST /tools/context/business-flow
POST /tools/schema/directory
POST /tools/loki/query
POST /tools/database/query
POST /tools/redis/get
POST /tools/redis/scan
```

本地 topology-aware 平台可先验证 schema directory，再提交 Agent job：

```bash
curl --noproxy '*' -s -X POST http://127.0.0.1:9000/tools/schema/directory \
  -H 'content-type: application/json' \
  -H 'X-Agent-User-Id: local-user' \
  -d '{"environment":"sanjiu","base":"guanlan","workshop":"GL001","limit":20}'
```

Agent 只允许查询 schema directory 中列出的表和字段。如果本地样例库只有
`GL001_EBR_PI(ID)` 这类不足以按订单号诊断的数据结构，最终报告应说明
`不具备诊断证据`，而不是反复猜测 `mo`、`order`、`production_order` 等不存在的表。
即使真实 Claude runtime 因 timeout 或 max turns 失败，`/tool-calls` 也应保留失败前
已经发生的工具调用摘要，便于判断是 schema 不足、策略拒绝还是上游不可达。

响应建议统一为：

```json
{
  "summary": {},
  "raw": {},
  "truncated": false,
  "metadata": {
    "request_id": "corr-1",
    "source": "database-gateway",
    "duration_ms": 12
  }
}
```

更多后端细节见 [backend/README.md](/Users/mhz/Develop/enterprise_agent/backend/README.md)。
