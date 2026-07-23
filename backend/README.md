# Enterprise Agent 后端 MVP

这个后端实现企业级只读诊断 Agent 的 MVP。当前阶段重点是跑通真实执行链路：

```text
DingTalk Stream / Grafana webhook / Debug API
  -> Stream ingress worker 或 FastAPI api-server
  -> PostgreSQL 16 持久化 Agent 任务
  -> RabbitMQ agent.job.queue
  -> agent-worker 消费任务
  -> Claude Code Agent Runtime 包装层
  -> 只读内部工具
  -> 生成诊断报告
  -> 持久化 steps / tool-calls / artifact / audit
```

默认 Claude runtime 使用 stub，设置 `FEATURE_REAL_CLAUDE=true` 后可切换到真实 Claude Agent SDK。默认内部工具使用 fake client，设置 `FEATURE_REAL_INTERNAL_TOOLS=true` 后可切换到 HTTP Internal API Platform 或本地 mock 平台。

## 模块边界

- `dingding`：钉钉 Stream 入口适配、兼容 HTTP webhook、消息解析、结果投递客户端。
- `job`：Agent 任务生命周期、状态流转、重试策略、调试 API。
- `message_bus`：消息发布和消费接口，RabbitMQ 是基础设施实现。
- `agent`：构造上下文、加载 skill、调用 Claude Runtime、保存结果。
- `internal_tools`：只读工具到内部 API 平台的适配，不直连真实数据库/Redis/Loki。
- `permission`：用户、项目、工具白名单。
- `audit`：任务、权限、工具调用、失败和最终报告审计。
- `platform_config`：平台拓扑、资源绑定、密钥引用、访问授权和配置审计，供后续 Web 配置平台使用。
- `workflow`：只读诊断 Agent 的拖拽流程模板、节点、边和发布快照配置。

平台配置 API、同库/分库策略、表设计和拖拽编排模型见 [platform-config-api.md](../docs/platform-config-api.md)。

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

本地启动钉钉 Stream 入口：

```bash
DINGTALK_STREAM_ENABLED=true \
DINGTALK_CLIENT_ID=your-client-id \
DINGTALK_CLIENT_SECRET=your-client-secret \
PYTHONPATH=backend .venv/bin/python -m app.workers.dingtalk_stream_ingress_worker
```

Docker Compose 启动 Stream 入口：

```bash
DINGTALK_CLIENT_ID=your-client-id \
DINGTALK_CLIENT_SECRET=your-client-secret \
docker compose --profile dingtalk-stream up --build
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

查询结果投递：

```bash
curl -s http://127.0.0.1:8000/api/agent/jobs/job_xxx/delivery-attempts
```

## Channel / Delivery 契约

入口请求统一拆成 `from`、`delivery`、`routing`、`message`：

```json
{
  "from": {
    "type": "grafana_alert",
    "connector_id": "connector-grafana-default",
    "event_id": "order-service-alert",
    "actor_id": "grafana"
  },
  "delivery": {
    "type": "dingtalk_webhook_robot",
    "connector_id": "connector-dingtalk-webhook-default",
    "target": {"webhook_id": "ops-alerts"}
  },
  "routing": {
    "project_code": "default",
    "environment": "prod",
    "base": "guanlan",
    "workshop": "GL001",
    "service": "order-service"
  },
  "message": "order-service error rate high"
}
```

Debug API 默认映射为 `from.type=debug_api` 和 `delivery.type=none`，因此本地调试结果通过查询接口读取，不默认回调钉钉。需要显式投递时可在请求体增加 `delivery` 对象。

通用 Channel endpoint：

```bash
curl -s -X POST http://127.0.0.1:8000/webhooks/channel/agent \
  -H 'content-type: application/json' \
  -d '{
    "from": {
      "type": "debug_api",
      "connector_id": "connector-debug-api",
      "event_id": "generic-demo-001",
      "actor_id": "local-user"
    },
    "delivery": {"type": "none"},
    "routing": {"project_code": "default"},
    "message": "帮我查一下订单 MO20260627001 为什么一直待领料"
  }'
```

Grafana webhook 只处理 `status=firing`；`resolved` 会返回 ignored acknowledgement，不创建 Agent job。必填专用 labels：

- `ea_project_code`
- `ea_environment`
- `ea_base`
- `ea_workshop`
- `ea_service`

可选投递 labels：

- `ea_delivery_type`
- `ea_delivery_connector_id`
- `ea_delivery_target`

Grafana firing 示例：

```bash
curl -s -X POST http://127.0.0.1:8000/webhooks/grafana/alert \
  -H 'content-type: application/json' \
  -H 'x-grafana-token: test-grafana-token' \
  -d '{
    "status": "firing",
    "groupKey": "order-service-alert",
    "commonLabels": {
      "ea_project_code": "default",
      "ea_environment": "prod",
      "ea_base": "guanlan",
      "ea_workshop": "GL001",
      "ea_service": "order-service",
      "ea_delivery_type": "dingtalk_webhook_robot",
      "ea_delivery_connector_id": "connector-dingtalk-webhook-default"
    },
    "commonAnnotations": {
      "summary": "order-service error rate high"
    }
  }'
```

本地 seed 包含这些 connector：

- `connector-debug-api`：ingress only。
- `connector-dingtalk-stream-default`：ingress only，钉钉企业 App Stream 长连接入口。
- `connector-dingtalk-enterprise-default`：delivery only，钉钉企业 App 结果出口。
- `connector-dingtalk-webhook-default`：delivery only，只发送消息到群，不接收用户问题。
- `connector-grafana-default`：ingress only。
- `connector-email-default`：delivery only。
- `connector-webhook-default`：delivery only。
- `connector-none`：none route。

Delivery 支持 `none`、`dingtalk_conversation`、`dingtalk_webhook_robot`、`dingtalk_enterprise_robot`、`email`、`webhook`。长报告会按 `DELIVERY_CHUNK_MAX_CHARS` 分片发送，并记录每个 delivery attempt 和 chunk；投递失败不会重新执行 Agent job。

### DingTalk Stream 入口配置

正式钉钉用户消息入口使用 DingTalk Stream，不需要把本地服务暴露成公网 HTTPS webhook。系统主动用企业 App Client ID/Secret 连接钉钉，收到用户消息后归一化为 Channel event，再创建 Agent job。

```env
DINGTALK_STREAM_ENABLED=true
DINGTALK_CLIENT_ID=your-client-id
DINGTALK_CLIENT_SECRET=your-client-secret
DINGTALK_STREAM_CONNECTOR_ID=connector-dingtalk-stream-default
DINGTALK_DEFAULT_SOURCE_CONNECTOR_ID=connector-dingtalk-stream-default
DINGTALK_DEFAULT_PROJECT_CODE=default
DINGTALK_DEFAULT_ENVIRONMENT=sanjiu
DINGTALK_DEFAULT_BASE=guanlan
DINGTALK_DEFAULT_WORKSHOP=GL001
DINGTALK_DEFAULT_SERVICE=order-service
```

Stream SDK 使用 `dingtalk-stream` 包。当前实现通过独立 worker 封装 SDK，fake 测试不依赖真实钉钉网络。若 Stream 连接断开，worker 会按 `DINGTALK_STREAM_RECONNECT_INITIAL_SECONDS` 到 `DINGTALK_STREAM_RECONNECT_MAX_SECONDS` 退避重连。同一个 connector 默认单活运行，重复投递通过 `dingding_stream:<connector_id>:<event_id>` 幂等键去重。

兼容 HTTP webhook 路由 `/webhooks/dingding/agent` 默认禁用。只有显式设置 `DINGTALK_HTTP_WEBHOOK_ENABLED=true` 时才作为本地测试/迁移兼容入口使用；正式钉钉用户消息不要再配置公网 HTTPS 回调地址。

### DingTalk delivery 配置

钉钉企业 App 出口使用 `connector-dingtalk-enterprise-default`。Client ID / Client Secret 不写入数据库明文，本地 seed 使用 `env:` 引用：

```env
DINGTALK_CLIENT_ID=your-client-id
DINGTALK_CLIENT_SECRET=your-client-secret
DINGTALK_DEFAULT_DELIVERY_TYPE=dingtalk_enterprise_robot
DINGTALK_DEFAULT_DELIVERY_CONNECTOR_ID=connector-dingtalk-enterprise-default
DINGTALK_DEFAULT_OPEN_CONVERSATION_ID=your-open-conversation-id
DINGTALK_DEFAULT_ROBOT_CODE=your-robot-code
```

钉钉 Stream 入口默认使用企业 App 出口。若 Stream 消息没有携带 `routing`，可以用环境变量配置默认诊断范围：

```env
DINGTALK_DEFAULT_PROJECT_CODE=default
DINGTALK_DEFAULT_ENVIRONMENT=sanjiu
DINGTALK_DEFAULT_BASE=guanlan
DINGTALK_DEFAULT_WORKSHOP=GL001
DINGTALK_DEFAULT_SERVICE=order-service
```

默认目标在 connector metadata 中配置：

```json
{
  "client_id_ref": "env:DINGTALK_CLIENT_ID",
  "default_open_conversation_id": "test-open-conversation",
  "default_robot_code": "test-robot-code"
}
```

也可以在请求的 `delivery.target` 中显式指定：

```json
{
  "type": "dingtalk_enterprise_robot",
  "connector_id": "connector-dingtalk-enterprise-default",
  "target": {
    "open_conversation_id": "cidxxx",
    "robot_code": "dingxxx"
  }
}
```

钉钉 webhook 群机器人出口使用 `connector-dingtalk-webhook-default`，只支持发送群消息，不支持作为入口接收用户问题：

```env
DINGTALK_WEBHOOK_ROBOT_URL=https://oapi.dingtalk.com/robot/send?access_token=xxx
DINGTALK_WEBHOOK_ROBOT_SECRET=your-robot-sign-secret
```

Debug API 指定投递到 webhook 群机器人：

```bash
curl -s -X POST http://127.0.0.1:8000/api/agent/jobs \
  -H 'content-type: application/json' \
  -d '{
    "message": "帮我查一下订单 MO20260627001 为什么一直待领料",
    "user_id": "local-user",
    "conversation_id": "debug-conversation",
    "project_code": "default",
    "idempotency_key": "debug-webhook-delivery-001",
    "delivery": {
      "type": "dingtalk_webhook_robot",
      "connector_id": "connector-dingtalk-webhook-default",
      "target": {"is_at_all": false}
    }
  }'
```

Grafana firing alert 指定投递到 webhook 群机器人时，设置 labels：

```json
{
  "ea_delivery_type": "dingtalk_webhook_robot",
  "ea_delivery_connector_id": "connector-dingtalk-webhook-default"
}
```

## 环境变量

### Web-managed secrets 与 DB runtime config

后端现在支持把大部分 `.env` 运行参数逐步迁移到 PostgreSQL：

- `bootstrap-only`：`DATABASE_DSN`、`RABBITMQ_URL`、`APP_CONFIG_MASTER_KEY`、`APP_ENV`、`APP_STARTUP_MIGRATE`、`SEED_LOCAL_CONFIG`。
- `deployment-safety-gate`：`FEATURE_WEB_ADMIN`、`FEATURE_PUBLISHED_AGENT_RUNTIME`、`FEATURE_REAL_CLAUDE`、`FEATURE_REAL_INTERNAL_TOOLS`；数据库不能越过关闭的部署闸门。
- `db-configurable`：`PERMISSION_SHADOW_MODE`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、`INTERNAL_API_BASE_URL`、`LOKI_MAX_LINES`、`AGENT_MAX_TURNS`、DingTalk 默认路由等。
- `secret-managed`：`ANTHROPIC_API_KEY`、`DINGTALK_CLIENT_SECRET`、数据库密码、Redis 密码、Loki token 等。

管理 API：

- `POST /api/platform/secrets`
- `POST /api/platform/secrets/{code}/rotate`
- `POST /api/platform/secrets/{code}/disable`
- `GET /api/platform/runtime-config/definitions`
- `POST /api/platform/runtime-config/values`
- `GET /api/platform/runtime-config/snapshot`
- `GET /api/platform/runtime-config/env-migration`

第一版 runtime config 在服务启动时叠加到 `Settings`；修改后重启对应服务生效。DB 不可用或配置解析失败时使用 env/default fallback，并在 `/api/ready` 的 `runtime_config` 字段标记 degraded。

完整流程见 [../docs/web-managed-secrets-and-env-config.md](/Users/mhz/Develop/enterprise_agent/docs/web-managed-secrets-and-env-config.md)。

- `DATABASE_DSN`：PostgreSQL DSN。
- `RABBITMQ_URL`：RabbitMQ URL。
- `APP_STARTUP_MIGRATE`：启动时执行 migration，默认 `true`。
- `SEED_LOCAL_CONFIG`：启动时写入本地工具、数据源和权限 seed。
- `DEBUG_AGENT_USER_ID`：调试 API 默认用户。
- `DINGTALK_SECRET`：钉钉机器人签名密钥。
- `DINGTALK_HTTP_WEBHOOK_ENABLED`：是否启用兼容 HTTP webhook 入口，默认 `false`。
- `DINGTALK_CALLBACK_URL`：结果回调地址。
- `DINGTALK_CALLBACK_HOST_ALLOWLIST`：回调 host 白名单。
- `DINGTALK_CLIENT_ID`：钉钉企业 App Client ID，不要提交真实值。
- `DINGTALK_CLIENT_SECRET`：钉钉企业 App Client Secret，不要提交真实值。
- `DINGTALK_STREAM_ENABLED`：是否启用钉钉 Stream 入口 worker，默认 `false`。
- `DINGTALK_STREAM_CONNECTOR_ID`：钉钉 Stream 入口 connector，默认 `connector-dingtalk-stream-default`。
- `DINGTALK_STREAM_RECONNECT_INITIAL_SECONDS`：Stream 断线后首次重连等待秒数，默认 `5`。
- `DINGTALK_STREAM_RECONNECT_MAX_SECONDS`：Stream 重连最大等待秒数，默认 `60`。
- `DINGTALK_WEBHOOK_ROBOT_URL`：钉钉 webhook 群机器人 URL，不要提交真实值。
- `DINGTALK_WEBHOOK_ROBOT_SECRET`：钉钉 webhook 群机器人加签密钥，不要提交真实值。
- `INTERNAL_API_BASE_URL`：内部 API 平台地址。
- `FEATURE_REAL_INTERNAL_TOOLS`：是否启用 HTTP Internal API Platform，默认 `false`。
- `INTERNAL_API_AUTH_TOKEN`：内部 API 平台 Bearer token，不要提交真实值。
- `INTERNAL_API_TIMEOUT_SECONDS`：内部平台单次请求超时时间，默认 `10`。
- `INTERNAL_API_MAX_RESPONSE_CHARS`：内部平台响应解析和安全摘要上限，默认 `4000`。
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
- `DELIVERY_CHUNK_MAX_CHARS`：结果投递单片最大字符数，默认 `3500`。
- `DELIVERY_TIMEOUT_SECONDS`：外部 delivery 请求超时秒数，默认 `5`。

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

## 内部工具平台

### fake 模式

默认模式：

```env
FEATURE_REAL_INTERNAL_TOOLS=false
```

此模式使用 `FakeInternalApiClient`，不访问网络，适合单元测试和基础 MQ / DB / worker 闭环验证。

### mock HTTP 模式

本地验证 HTTP 工具链路：

```env
FEATURE_REAL_INTERNAL_TOOLS=true
INTERNAL_API_BASE_URL=http://mock-internal-api-platform:9000
INTERNAL_API_AUTH_TOKEN=
```

启动：

```bash
docker compose --profile mock-tools up -d --build
```

验证：

```bash
curl --noproxy '*' -s -X POST http://127.0.0.1:8000/api/agent/jobs \
  -H 'content-type: application/json' \
  -d '{
    "message": "帮我查一下订单 MO20260627001 为什么一直待领料",
    "user_id": "local-user",
    "conversation_id": "debug-conversation",
    "project_code": "default",
    "idempotency_key": "mock-tools-demo-001"
  }'
```

预期：

- job 最终 `SUCCEEDED`。
- `/tool-calls` 中可以看到 context 工具调用的 `metadata.source` 来自 mock 平台。
- Agent runtime 仍不直连数据库、Redis、Loki、ER 或业务图存储。

### local-loki 模式

本地验证真实 Claude/DeepSeek + 真实 Loki，但仍保持 Agent 只调用 Internal API Platform。

适用场景：

```text
真实 Claude/DeepSeek
  -> agent-worker
  -> local-internal-api-platform
  -> Loki query_range
```

要求宿主机 Loki 可访问：

```bash
curl -s http://localhost:3100/ready
```

容器内访问宿主机 Loki 使用：

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

本地平台 endpoint：

```text
GET  /health
POST /tools/context/er
POST /tools/context/business-flow
POST /tools/schema/directory
POST /tools/loki/query
POST /tools/database/query
POST /tools/redis/get
POST /tools/redis/scan
```

第一版行为：

- `query_loki` 真实请求 Loki `/loki/api/v1/query_range`。
- `get_er_context` 和 `get_business_flow_context` 返回明确的 local placeholder。
- `query_database`、`query_redis_get`、`query_redis_scan` 默认返回 `tool_not_configured`，不会访问真实数据库或 Redis。

Loki 相关配置：

```env
LOKI_BASE_URL=http://host.docker.internal:3100
LOKI_MAX_MINUTES=60
LOKI_MAX_LINES=500
LOKI_MAX_RESPONSE_CHARS=4000
LOKI_TENANT_ID=
```

当前 LogQL 构造策略：

```text
selector + keyword -> {cluster="<cluster>"} |= "<keyword>"
service + keyword  -> {service="<service>"} |= "<keyword>"
selector only      -> {cluster="<cluster>"}
```

第一版不允许 Agent 传完整任意 LogQL，避免真实联调时生成无界或高成本查询。`selector`
只允许 `cluster`、`container`、`region`、`service`、`service_name` 这些精确匹配 label。

### real-tools：正式 Internal API Platform 模式

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

Oracle Instant Client（旧版 Oracle / thick 模式）仅打入 `internal-api-platform` 镜像。将官方 Instant Client 放到 `backend/vendor/oracle/` 后重建该服务；说明见 `backend/vendor/oracle/README.md`。未放入客户端时镜像仍可构建，运行时保持 thin；`oracle_client_mode: thick` 的基地会明确失败。`api-server` / `agent-worker` 不包含 Instant Client。

配置一致性检查：

```bash
docker compose --profile real-tools ps
docker compose --profile real-tools exec agent-worker printenv INTERNAL_API_BASE_URL
docker compose --profile real-tools exec agent-worker printenv FEATURE_REAL_INTERNAL_TOOLS
docker compose --profile real-tools exec agent-worker printenv FEATURE_REAL_CLAUDE
docker compose --profile real-tools exec internal-api-platform python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9000/health').read().decode())"
```

MVP endpoint：

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

通用 headers：

```text
Authorization: Bearer <INTERNAL_API_AUTH_TOKEN>
X-Agent-Job-Id: <job_id>
X-Agent-User-Id: <user_id>
X-Agent-Project-Code: <project_code>
X-Correlation-Id: <correlation_id>
Content-Type: application/json
```

响应 envelope：

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

错误约定：

- `429`、`502`、`503`、`504`、连接超时：可重试错误。
- `400`、`401`、`403`、`404`：不可重试错误。
- body 中 `code` / `type` / `error.code` 为 `policy_denied`：工具策略拒绝。

平台返回的 `raw` 默认只保留在内存的 `ToolResult.raw`，持久化只写 bounded summary。

Schema directory 验证：

```bash
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; payload={'environment':'sanjiu','base':'guanlan','workshop':'GL001','limit':20}; req=urllib.request.Request('http://127.0.0.1:9000/tools/schema/directory', data=json.dumps(payload).encode(), headers={'content-type':'application/json','X-Agent-User-Id':'local-user'}, method='POST'); print(urllib.request.urlopen(req).read().decode())"
```

Loki 诊断验证：

```bash
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; payload={'environment':'sanjiu','base':'guanlan','workshop':'GL001','minutes':15,'limit':20}; req=urllib.request.Request('http://127.0.0.1:9000/tools/loki/labels', data=json.dumps(payload).encode(), headers={'content-type':'application/json','X-Agent-User-Id':'local-user'}, method='POST'); print(urllib.request.urlopen(req).read().decode())"
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; payload={'environment':'sanjiu','base':'guanlan','workshop':'GL001','label':'service','minutes':15,'limit':20}; req=urllib.request.Request('http://127.0.0.1:9000/tools/loki/label-values', data=json.dumps(payload).encode(), headers={'content-type':'application/json','X-Agent-User-Id':'local-user'}, method='POST'); print(urllib.request.urlopen(req).read().decode())"
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; payload={'environment':'sanjiu','base':'guanlan','workshop':'GL001','selector':{'service':'order-service'},'query':'synthetic-test-error','minutes':15,'limit':20}; req=urllib.request.Request('http://127.0.0.1:9000/tools/loki/probe', data=json.dumps(payload).encode(), headers={'content-type':'application/json','X-Agent-User-Id':'local-user'}, method='POST'); print(urllib.request.urlopen(req).read().decode())"
```

DB-backed platform config runtime 验证：

```bash
curl --noproxy '*' -s -X POST http://127.0.0.1:8000/api/platform/import/topology-yaml \
  -H 'content-type: application/json' \
  -H 'x-admin-user-id: local-user' \
  -d '{"path":"config/internal_platform_topology.example.yaml"}'

curl --noproxy '*' -s http://127.0.0.1:8000/api/platform/topology-snapshot

docker compose --profile real-tools restart internal-api-platform
docker compose --profile real-tools exec internal-api-platform python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9000/health').read().decode())"
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; payload={'environment':'sanjiu','base':'guanlan','workshop':'GL001','kind':'database'}; req=urllib.request.Request('http://127.0.0.1:9000/tools/resolve', data=json.dumps(payload).encode(), headers={'content-type':'application/json','X-Agent-User-Id':'local-user'}, method='POST'); print(urllib.request.urlopen(req).read().decode())"
```

关键判断：

```text
/api/platform/topology-snapshot: source = database, valid = true
/health: config.source = database, config.resource_count > 0
/tools/resolve: metadata.source = internal-api-platform
```

只有数据库没有启用 topology 且设置了 `INTERNAL_PLATFORM_TOPOLOGY_FILE` 时才走 YAML
fallback。数据库已有启用 topology 但配置不完整时，必须显示
`config.source=database-invalid` 和 degraded health。当前 `internal-api-platform` 使用启动时
snapshot，修改 platform config 后需要重启服务；完整步骤见
`docs/db-backed-platform-config-runtime-test.md`。

真实诊断前，Agent 会使用 schema directory 约束 SQL。若目标 schema 为空、只有
`GL001_EBR_PI(ID)` 这类不足字段，或缺少订单号/状态/物料相关字段，Agent 必须停止
扩散式试错并输出 `不具备诊断证据`。失败或 retry-pending job 仍可通过：

```bash
curl -s http://127.0.0.1:8000/api/agent/jobs/job_xxx/tool-calls
```

查看失败前已经持久化的工具调用摘要。

真实 Claude/DeepSeek 联调必须默认使用合成问题、合成 Loki 日志或已脱敏工具摘要。
只验证 real-tools/Loki 链路时使用 `FEATURE_REAL_CLAUDE=false`；启用
`FEATURE_REAL_CLAUDE=true` 会调用外部模型 API，未确认前不要发送真实业务日志、
密钥、个人信息或内部敏感内容。

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
- `delivery_attempt`
- `delivery_chunk`
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
- Channel 泛入口、Grafana firing/ignored、缺失 label 拒绝。
- Delivery none、钉钉分片、adapter 失败、connector 方向校验。
- DingTalk 企业 App token/message client、webhook 群机器人签名发送、host allowlist 和敏感摘要屏蔽。
- feature flag 开启时生产 runtime 注入 `RealClaudeCodeAgentClient`，测试 runtime 仍使用 stub。
- feature flag 开启时生产 runtime 注入 `HttpInternalApiClient`，测试 runtime 仍使用 fake internal tools。
- HTTP Internal API client 的 headers、payload、envelope、legacy body、错误分类和脱敏。
- mock Internal API Platform 的本地 HTTP 工具链路。
- fake SDK 覆盖真实 runtime 的权限配置、工具循环、错误映射、timeout 和 tool event 解析。
- opt-in integration 测试默认 skip，只有配置真实 key 和 CLI 时运行。
- 只读 SQL / Redis / Loki 策略。
- 工具调用审计和报告产物持久化。
