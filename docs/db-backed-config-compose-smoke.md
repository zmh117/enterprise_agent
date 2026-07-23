# DB-backed Config Compose Smoke

目标：用真实 Docker Compose、真实 PostgreSQL、真实 RabbitMQ、真实 `api-server` 和真实 `agent-worker`，验证从 Web-managed secret 到 DB-backed runtime config，再到 Agent job 执行完成的闭环。

默认流程不调用真实 DeepSeek/Claude：

```env
FEATURE_REAL_CLAUDE=false
FEATURE_REAL_INTERNAL_TOOLS=false
APP_CONFIG_MASTER_KEY=local-dev-config-master-key
```

这能验证配置链路和 worker 消费链路，同时避免外部模型数据出境。

## 1. 启动基础服务

```bash
APP_CONFIG_MASTER_KEY=local-dev-config-master-key \
FEATURE_REAL_CLAUDE=false \
FEATURE_REAL_INTERNAL_TOOLS=false \
docker compose up -d --build postgres rabbitmq api-server agent-worker
```

检查：

```bash
docker compose ps postgres rabbitmq api-server agent-worker
```

必须看到：

```text
postgres      healthy
rabbitmq      healthy
api-server    running
agent-worker  running
```

`APP_CONFIG_MASTER_KEY` 是 bootstrap-only 配置，用于解密 `secret://platform/<code>`。它不能存到同一个 PostgreSQL 配置库里。

## 2. 检查 API Ready

```bash
curl --noproxy '*' -s http://127.0.0.1:8000/api/ready
```

首次启动时可能还是 env/default fallback。关键是数据库和 RabbitMQ 可用：

```text
database = true
rabbitmq = true
```

## 3. 创建 Web-managed Secret

默认 smoke 可以使用合成 key，不会调用外部模型：

```bash
export DEEPSEEK_API_KEY_FOR_SMOKE='smoke-local-secret-not-real'
```

创建 secret：

```bash
curl --noproxy '*' -s -X POST http://127.0.0.1:8000/api/platform/secrets \
  -H 'content-type: application/json' \
  -H 'x-admin-user-id: local-user' \
  -d "{
    \"code\": \"deepseek_api_key\",
    \"value\": \"${DEEPSEEK_API_KEY_FOR_SMOKE}\",
    \"purpose\": \"compose-smoke\"
  }"
```

关键预期：

```text
secret.secret_ref = secret://platform/deepseek_api_key
secret.configured = true
secret.active_version >= 1
```

响应不得包含：

```text
${DEEPSEEK_API_KEY_FOR_SMOKE}
```

## 4. 写入 DB-backed Runtime Config

`FEATURE_REAL_CLAUDE` 是部署安全闸门，只能在启动环境中设置。数据库只写模型地址、
模型名和 Secret 引用：

```bash
curl --noproxy '*' -s -X POST http://127.0.0.1:8000/api/platform/runtime-config/values \
  -H 'content-type: application/json' \
  -H 'x-admin-user-id: local-user' \
  -d '{"key":"ANTHROPIC_BASE_URL","value":"https://api.deepseek.com/anthropic"}'

curl --noproxy '*' -s -X POST http://127.0.0.1:8000/api/platform/runtime-config/values \
  -H 'content-type: application/json' \
  -H 'x-admin-user-id: local-user' \
  -d '{"key":"ANTHROPIC_MODEL","value":"deepseek-v4-pro[1m]"}'

curl --noproxy '*' -s -X POST http://127.0.0.1:8000/api/platform/runtime-config/values \
  -H 'content-type: application/json' \
  -H 'x-admin-user-id: local-user' \
  -d '{"key":"ANTHROPIC_API_KEY","secret_ref":"secret://platform/deepseek_api_key"}'

curl --noproxy '*' -s -X POST http://127.0.0.1:8000/api/platform/runtime-config/values \
  -H 'content-type: application/json' \
  -H 'x-admin-user-id: local-user' \
  -d '{"key":"AGENT_MAX_TURNS","value":12}'
```

查看 agent-worker effective snapshot：

```bash
curl --noproxy '*' -s \
  'http://127.0.0.1:8000/api/platform/runtime-config/snapshot?service_name=agent-worker'
```

关键预期：

```text
snapshot.effective_masked.ANTHROPIC_API_KEY.secret_ref = secret://platform/deepseek_api_key
snapshot.effective_masked.AGENT_MAX_TURNS.value = 12
snapshot.config_hash 存在
```

不允许出现真实 API key。

## 5. 重启服务使 Overlay 生效

第一版 runtime config 是启动时 overlay，不是热更新。写入 DB 后必须重启相关服务：

```bash
APP_CONFIG_MASTER_KEY=local-dev-config-master-key \
docker compose restart api-server agent-worker
```

再次检查 ready：

```bash
curl --noproxy '*' -s http://127.0.0.1:8000/api/ready
```

关键预期：

```text
runtime_config.source = database
runtime_config.degraded = false
runtime_config.revision > 0
runtime_config.config_hash 存在
anthropic_api_key_configured = true
```

`/api/ready` 只允许显示是否 configured，不得显示 key。

## 6. 提交 Agent Job

```bash
curl --noproxy '*' -s -X POST http://127.0.0.1:8000/api/agent/jobs \
  -H 'content-type: application/json' \
  -d '{
    "message": "合成测试：请生成一份只读诊断 smoke 报告，不要访问真实业务数据。",
    "user_id": "local-user",
    "conversation_id": "smoke-db-backed-config",
    "project_code": "default",
    "idempotency_key": "smoke-db-backed-config-compose"
  }'
```

记录返回：

```text
job_id = job_xxx
status = PENDING
```

## 7. 轮询 Job

```bash
JOB_ID=job_xxx

curl --noproxy '*' -s "http://127.0.0.1:8000/api/agent/jobs/${JOB_ID}"
```

关键预期：

```text
job.status = SUCCEEDED
job.result 存在
```

如果长时间是 `PENDING`，先看 worker：

```bash
docker compose logs --tail=200 agent-worker
```

## 8. 查询 Steps 和 Tool Calls

```bash
curl --noproxy '*' -s "http://127.0.0.1:8000/api/agent/jobs/${JOB_ID}/steps"

curl --noproxy '*' -s "http://127.0.0.1:8000/api/agent/jobs/${JOB_ID}/tool-calls"
```

关键预期：

```text
steps 至少包含最终回答或执行步骤
tool_calls 返回数组，stub 模式下可以为空
```

输出不得包含：

```text
DEEPSEEK_API_KEY_FOR_SMOKE 的值
数据库密码
Redis 密码
Anthropic/DeepSeek token
未脱敏 raw payload
```

## 9. 一键 Smoke 脚本

脚本会使用 `docker compose` 当前解析到的 `APP_CONFIG_MASTER_KEY`，不会覆盖 `.env`。同一个 Postgres 数据卷内不要随意切换 `APP_CONFIG_MASTER_KEY`；如果切换了，需要重新 rotate Web-managed secrets，否则会出现：

```text
Platform secret decrypt failed
```

默认 stub 模式：

```bash
scripts/smoke_db_backed_config.sh
```

复用已有镜像快速复测：

```bash
SMOKE_BUILD=false scripts/smoke_db_backed_config.sh
```

脚本默认每次使用新的 `SMOKE_RUN_ID`，避免复用旧的 `idempotency_key` 和旧 job。需要复现同一次请求时可以显式指定：

```bash
SMOKE_RUN_ID=20260707120000 scripts/smoke_db_backed_config.sh
```

可选真实 DeepSeek 模式：

```bash
export DEEPSEEK_API_KEY='真实 DeepSeek API Key'
REAL_CLAUDE=true scripts/smoke_db_backed_config.sh
```

真实模式会调用外部模型 API。只能使用合成问题或已脱敏上下文，不要把真实订单、日志、数据库结果发给外部模型。

## 10. 常见失败排查

### secret 创建失败

检查 `APP_CONFIG_MASTER_KEY`：

```bash
docker compose exec api-server env | grep APP_CONFIG_MASTER_KEY
docker compose logs --tail=100 api-server
```

### runtime_config.degraded = true

查看 snapshot：

```bash
curl --noproxy '*' -s \
  'http://127.0.0.1:8000/api/platform/runtime-config/snapshot?service_name=agent-worker'
```

常见原因：

```text
secret_ref 指向不存在的 secret
secret 已禁用
value 类型错误
APP_CONFIG_MASTER_KEY 不一致
```

### job 一直 PENDING

```bash
docker compose ps agent-worker rabbitmq
docker compose logs --tail=200 agent-worker
```

### job FAILED

```bash
curl --noproxy '*' -s "http://127.0.0.1:8000/api/agent/jobs/${JOB_ID}"
curl --noproxy '*' -s "http://127.0.0.1:8000/api/agent/jobs/${JOB_ID}/steps"
curl --noproxy '*' -s "http://127.0.0.1:8000/api/agent/jobs/${JOB_ID}/tool-calls"
```

根据 `error_message` 判断是 Claude runtime、secret resolver、RabbitMQ、权限还是 internal tools 问题。

### 默认 smoke 不依赖真实 Internal API Platform

默认配置：

```text
FEATURE_REAL_INTERNAL_TOOLS=false
```

因此不会依赖 Loki、Redis、真实业务数据库或 `internal-api-platform` profile。real-tools 验证应作为后续单独步骤执行。

## 11. 本次验证记录

```text
date: 2026-07-07
command: SMOKE_BUILD=false scripts/smoke_db_backed_config.sh
mode: stub-claude
run_id: 20260707160859
runtime_config: source=database revision=9 hash=dfe08a502dbf
job_id: job_98cb9539c9884031bb2e27537f21b19e
job_status: SUCCEEDED
steps: > 0
tool_calls: 2
secret_leak_check: passed
```
