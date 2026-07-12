# 企业级只读诊断 Agent 平台

这是一个企业内部只读诊断 Agent 平台 MVP。当前目标是先跑通诊断执行链路，而不是做“大而全 Agent 平台”。

钉钉群聊/私聊连续会话、MinIO附件存储和现代Office/Markdown受限提取说明见[连续对话与多模态附件MVP](docs/continuous-multimodal-conversations.md)。

本地多数据库测试数据环境见 [docs/agent-test-data.md](/Users/mhz/Develop/enterprise_agent/docs/agent-test-data.md)，入口：

```bash
scripts/agent_test_data.sh up
scripts/agent_test_data.sh verify
scripts/agent_test_data.sh reset --yes
```

```text
钉钉 / Debug API
  -> FastAPI api-server
  -> PostgreSQL 18 持久化任务
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
- Web-managed secrets：`/api/platform/secrets` 支持管理员输入密钥后加密保存，并返回 `secret://platform/<code>`。
- DB-backed runtime config：`/api/platform/runtime-config/*` 支持把 DeepSeek、Internal API、Loki、DingTalk 默认路由和 Agent limits 逐步迁入 PostgreSQL。

## Web 管理配置与密钥

平台配置分为 `bootstrap-only`、`db-configurable` 和 `secret-managed` 三类。最小 bootstrap env 仍保留 `DATABASE_DSN`、`APP_CONFIG_MASTER_KEY`、`APP_ENV`、`APP_STARTUP_MIGRATE`、`SEED_LOCAL_CONFIG`；Claude/DeepSeek、Internal API、Loki、DingTalk 默认路由和 Agent limits 可逐步通过 PostgreSQL runtime config 管理。

Web 管理端后续可以调用 `/api/platform/secrets` 保存 API key、password、token，后端只返回 `secret://platform/<code>`，不会回显明文。运行参数通过 `/api/platform/runtime-config/*` 管理，第一版修改后重启服务生效。

详细说明见 [docs/web-managed-secrets-and-env-config.md](/Users/mhz/Develop/enterprise_agent/docs/web-managed-secrets-and-env-config.md)。

## 快速开始

PostgreSQL 18 / RabbitMQ 4 的全新启动、已有数据迁移与回滚步骤见
[Compose 基础设施升级手册](docs/compose-postgres18-rabbitmq4-upgrade.md)。已有 PostgreSQL 16
数据时不要直接执行 `docker compose up`，必须先按手册备份和排空队列。

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

### local-tools / local-loki 模式

使用本地开发用 `local-internal-api-platform` 查询宿主机 Loki。它只用于快速验证
容器到宿主机 Loki 的链路，不是正式拓扑化平台。

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

只验证真实 Loki 工具链、不调用外部模型时，把 `FEATURE_REAL_CLAUDE=false`。

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

### real-tools 模式

使用正式拓扑化 `internal-api-platform`。这是当前真实工具平台主线，支持
environment/base/workshop 寻址、平台侧访问控制、多方言只读数据库网关、
Redis/Loki 基地级路由和 Loki 诊断。

```env
FEATURE_REAL_INTERNAL_TOOLS=true
INTERNAL_API_BASE_URL=http://internal-api-platform:9000
INTERNAL_API_AUTH_TOKEN=
INTERNAL_API_TIMEOUT_SECONDS=10
INTERNAL_API_MAX_RESPONSE_CHARS=4000
INTERNAL_PLATFORM_TOPOLOGY_FILE=/app/backend/config/internal_platform_topology.example.yaml
SECRET_SANJIU_GUANLAN_LOKI_URL=http://host.docker.internal:3100
```

启动：

```bash
FEATURE_REAL_CLAUDE=false \
FEATURE_REAL_INTERNAL_TOOLS=true \
INTERNAL_API_BASE_URL=http://internal-api-platform:9000 \
SECRET_SANJIU_GUANLAN_LOKI_URL=http://host.docker.internal:3100 \
docker compose --profile real-tools up -d --build internal-api-platform api-server agent-worker
```

real-tools endpoint：

```text
POST /tools/context/er
POST /tools/context/business-flow
POST /tools/schema/directory
POST /tools/loki/query
POST /tools/loki/labels
POST /tools/loki/label-values
POST /tools/loki/probe
POST /tools/database/query
POST /tools/redis/get
POST /tools/redis/scan
```

DB-backed platform config 验证：

```bash
curl --noproxy '*' -s -X POST http://127.0.0.1:8000/api/platform/import/topology-yaml \
  -H 'content-type: application/json' \
  -H 'x-admin-user-id: local-user' \
  -d '{"path":"config/internal_platform_topology.example.yaml"}'

curl --noproxy '*' -s http://127.0.0.1:8000/api/platform/topology-snapshot

docker compose --profile real-tools restart internal-api-platform
docker compose --profile real-tools exec internal-api-platform python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9000/health').read().decode())"
```

预期 `health.config.source=database`。只有 PostgreSQL 没有启用 topology 时才允许
YAML fallback；如果 DB 中已有启用 topology 但配置无效，必须显示
`config.source=database-invalid`，不能静默回退 YAML。当前 runtime 使用启动时
snapshot，修改平台配置后需要重启 `internal-api-platform`，后续可再做 reload endpoint。
完整步骤见 `docs/db-backed-platform-config-runtime-test.md`。

先验证平台 health、拓扑和 Loki 诊断，再提交 Agent job：

```bash
docker compose --profile real-tools exec agent-worker printenv INTERNAL_API_BASE_URL
docker compose --profile real-tools exec internal-api-platform python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9000/health').read().decode())"
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; payload={'environment':'sanjiu','base':'guanlan','workshop':'GL001','limit':20}; req=urllib.request.Request('http://127.0.0.1:9000/tools/loki/labels', data=json.dumps(payload).encode(), headers={'content-type':'application/json','X-Agent-User-Id':'local-user'}, method='POST'); print(urllib.request.urlopen(req).read().decode())"
```

Schema directory 验证：

```bash
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; payload={'environment':'sanjiu','base':'guanlan','workshop':'GL001','limit':20}; req=urllib.request.Request('http://127.0.0.1:9000/tools/schema/directory', data=json.dumps(payload).encode(), headers={'content-type':'application/json','X-Agent-User-Id':'local-user'}, method='POST'); print(urllib.request.urlopen(req).read().decode())"
```

如果使用外部/生产 Internal API Platform，把 `INTERNAL_API_BASE_URL` 改为实际 HTTPS 地址，
并设置 `INTERNAL_API_AUTH_TOKEN`。

真实 Claude/DeepSeek 联调时，必须默认使用合成问题、合成日志或已脱敏工具摘要：

```bash
FEATURE_REAL_CLAUDE=true \
FEATURE_REAL_INTERNAL_TOOLS=true \
INTERNAL_API_BASE_URL=http://internal-api-platform:9000 \
docker compose --profile real-tools up -d --build internal-api-platform api-server agent-worker
```

不要在未确认前把真实业务日志、密钥、个人信息或内部敏感内容发送到外部模型。

提交安全 debug job 示例：

```bash
curl --noproxy '*' -s -X POST http://127.0.0.1:8000/api/agent/jobs \
  -H 'content-type: application/json' \
  -d '{
    "message": "使用合成日志检查 sanjiu/guanlan/GL001 的 order-service selector 是否能命中 synthetic-test-error",
    "user_id": "local-user",
    "conversation_id": "debug-conversation",
    "project_code": "default",
    "idempotency_key": "real-tools-safe-smoke-001"
  }'
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

导入数据库环境信息
curl --noproxy '\*' -s -X POST http://127.0.0.1:8000/api/platform/import/topology-yaml \
 -H 'content-type: application/json' \
 -H 'x-admin-user-id: local-user' \
 -d '{"path":"config/internal_platform_topology.example.yaml"}'

docker compose --profile dingtalk-stream --profile internal-tools up -d
docker compose --profile attachments --profile dingtalk-stream up -d --build
docker compose --profile attachments ps
docker compose --profile attachments logs --tail=100 attachment-worker
