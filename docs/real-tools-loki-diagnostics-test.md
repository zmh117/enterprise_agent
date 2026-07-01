# real-tools Loki 诊断链路测试记录

测试目标：验证正式 `internal-api-platform` 主线，而不是 `local-internal-api-platform`。

```text
api-server / agent-worker
  -> internal-api-platform
  -> topology resolve + access policy
  -> Loki diagnostics / query
```

默认先不调用真实 Claude/DeepSeek：

```env
FEATURE_REAL_CLAUDE=false
```

## 1. 启动 real-tools

如果本机 Loki 在 `localhost:3100`：

```bash
FEATURE_REAL_CLAUDE=false \
FEATURE_REAL_INTERNAL_TOOLS=true \
INTERNAL_API_BASE_URL=http://internal-api-platform:9000 \
SECRET_SANJIU_GUANLAN_LOKI_URL=http://host.docker.internal:3100 \
docker compose --profile real-tools up -d --build internal-api-platform api-server agent-worker
```

如果 Loki 需要 tenant，在 topology YAML 中配置对应 `tenant`，或复制
`backend/config/internal_platform_topology.example.yaml` 为真实配置后再设置：

```env
INTERNAL_PLATFORM_TOPOLOGY_FILE=/app/backend/config/internal_platform_topology.example.yaml
```

## 2. 服务与配置检查

```bash
docker compose --profile real-tools ps
docker compose --profile real-tools exec agent-worker printenv INTERNAL_API_BASE_URL
docker compose --profile real-tools exec agent-worker printenv FEATURE_REAL_INTERNAL_TOOLS
docker compose --profile real-tools exec agent-worker printenv FEATURE_REAL_CLAUDE
```

预期：

```text
internal-api-platform Up
api-server            Up
agent-worker          Up
postgres              Up, healthy
rabbitmq              Up, healthy
INTERNAL_API_BASE_URL=http://internal-api-platform:9000
FEATURE_REAL_INTERNAL_TOOLS=true
FEATURE_REAL_CLAUDE=false
```

平台 health：

```bash
docker compose --profile real-tools exec internal-api-platform python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9000/health').read().decode())"
```

预期：

```json
{"status":"ok","mode":"internal-api-platform"}
```

## 3. 拓扑解析

```bash
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; payload={'environment':'sanjiu','base':'guanlan','workshop':'GL001','kind':'loki'}; req=urllib.request.Request('http://127.0.0.1:9000/tools/resolve', data=json.dumps(payload).encode(), headers={'content-type':'application/json','X-Agent-User-Id':'local-user'}, method='POST'); print(urllib.request.urlopen(req).read().decode())"
```

预期 summary 包含：

```json
{
  "environment": "sanjiu",
  "base": "guanlan",
  "workshop": "GL001",
  "kind": "loki"
}
```

## 4. Loki labels 诊断

```bash
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; payload={'environment':'sanjiu','base':'guanlan','workshop':'GL001','minutes':15,'limit':20}; req=urllib.request.Request('http://127.0.0.1:9000/tools/loki/labels', data=json.dumps(payload).encode(), headers={'content-type':'application/json','X-Agent-User-Id':'local-user'}, method='POST'); print(urllib.request.urlopen(req).read().decode())"
```

预期：

```text
metadata.source = internal-api-platform-loki-diagnostics
summary.labels 只包含允许 label：cluster/container/region/service/service_name/workshop
```

查询某个 label 的候选值：

```bash
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; payload={'environment':'sanjiu','base':'guanlan','workshop':'GL001','label':'service','minutes':15,'limit':20}; req=urllib.request.Request('http://127.0.0.1:9000/tools/loki/label-values', data=json.dumps(payload).encode(), headers={'content-type':'application/json','X-Agent-User-Id':'local-user'}, method='POST'); print(urllib.request.urlopen(req).read().decode())"
```

如果 `service` 没有值，继续检查：

```text
label=service_name
label=container
label=cluster
```

## 5. Loki selector probe

```bash
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; payload={'environment':'sanjiu','base':'guanlan','workshop':'GL001','selector':{'service':'order-service'},'query':'synthetic-test-error','minutes':15,'limit':20}; req=urllib.request.Request('http://127.0.0.1:9000/tools/loki/probe', data=json.dumps(payload).encode(), headers={'content-type':'application/json','X-Agent-User-Id':'local-user'}, method='POST'); print(urllib.request.urlopen(req).read().decode())"
```

如果返回：

```json
{
  "line_count": 0,
  "empty_result_hints": []
}
```

按顺序排查：

```text
1. topology 中 Loki tenant 是否正确。
2. Loki 中是否存在 workshop="GL001" 的日志流。
3. service 是否应该换成 service_name/container/job。
4. 时间窗口 minutes 是否太短。
5. query 关键字是否真的存在于日志行。
```

## 6. Debug Agent job

只验证工具链，不调用外部模型：

```bash
curl --noproxy '*' -s -X POST http://127.0.0.1:8000/api/agent/jobs \
  -H 'content-type: application/json' \
  -d '{
    "message": "使用合成日志检查 sanjiu/guanlan/GL001 的 order-service selector 是否能命中 synthetic-test-error",
    "user_id": "local-user",
    "conversation_id": "debug-conversation",
    "project_code": "default",
    "idempotency_key": "real-tools-loki-diagnostics-001"
  }'
```

查询：

```bash
curl --noproxy '*' -s http://127.0.0.1:8000/api/agent/jobs/<job_id>
curl --noproxy '*' -s http://127.0.0.1:8000/api/agent/jobs/<job_id>/steps
curl --noproxy '*' -s http://127.0.0.1:8000/api/agent/jobs/<job_id>/tool-calls
```

预期 `/tool-calls` 中可以看到工具调用摘要，并能通过 `metadata.source` 判断是否来自
`internal-api-platform`。

## 7. 真实 Claude/DeepSeek 安全测试

启用真实模型前必须满足至少一个条件：

```text
1. 使用合成日志。
2. 使用已脱敏工具摘要。
3. 已明确确认当前测试数据允许发送到外部模型 API。
```

启动：

```bash
FEATURE_REAL_CLAUDE=true \
FEATURE_REAL_INTERNAL_TOOLS=true \
INTERNAL_API_BASE_URL=http://internal-api-platform:9000 \
docker compose --profile real-tools up -d --build internal-api-platform api-server agent-worker
```

不要在未确认前发送真实业务日志、密钥、个人信息或内部敏感内容。
