# local-tools 真实 Loki 工具链测试记录

测试时间：2026-07-01 10:59:28 CST

## 测试目标

验证 `local-tools` 模式下的真实 Loki 工具链：

```text
agent-worker
  -> local-internal-api-platform
  -> host.docker.internal:3100
  -> Loki /loki/api/v1/query_range
```

本次测试不触发真实 DeepSeek/Claude 调用，因此启动时设置：

```env
FEATURE_REAL_CLAUDE=false
```

## 启动命令

```bash
FEATURE_REAL_CLAUDE=false \
FEATURE_REAL_INTERNAL_TOOLS=true \
INTERNAL_API_BASE_URL=http://local-internal-api-platform:9000 \
LOKI_BASE_URL=http://host.docker.internal:3100 \
LOKI_TENANT_ID=tenant1 \
docker compose --profile local-tools up -d --force-recreate local-internal-api-platform api-server agent-worker
```

启动结果：

```text
Container enterprise_agent-local-internal-api-platform-1 Started
Container enterprise_agent-agent-worker-1 Started
Container enterprise_agent-api-server-1 Started
```

## 服务状态检查

命令：

```bash
docker compose --profile local-tools ps
```

结果摘要：

```text
enterprise_agent-agent-worker-1                  Up
enterprise_agent-api-server-1                    Up, 0.0.0.0:8000->8000/tcp
enterprise_agent-local-internal-api-platform-1   Up, 9000/tcp
enterprise_agent-postgres-1                      Up, healthy
enterprise_agent-rabbitmq-1                      Up, healthy
```

## Worker 指向检查

命令：

```bash
docker compose exec agent-worker printenv INTERNAL_API_BASE_URL
docker compose exec agent-worker printenv FEATURE_REAL_CLAUDE
```

结果：

```text
http://local-internal-api-platform:9000
false
```

说明：

- `agent-worker` 已指向本地工具平台。
- 真实 Claude 已关闭，本次只测试真实 Loki 工具链。

## Local Platform 健康检查

命令：

```bash
docker compose exec local-internal-api-platform python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:9000/health', timeout=5).read().decode())"
```

结果：

```json
{
  "status": "ok",
  "mode": "local-internal-api-platform",
  "loki": {
    "base_url_configured": true,
    "base_url": "http://host.docker.internal:3100",
    "max_minutes": 60,
    "max_lines": 500,
    "max_response_chars": 4000,
    "tenant_configured": true
  }
}
```

## 宿主机 Loki 可达性检查

命令：

```bash
curl --noproxy '*' -s -o /tmp/enterprise_agent_loki_buildinfo.txt -w "%{http_code}" \
  http://localhost:3100/loki/api/v1/status/buildinfo
```

结果：

```text
200
```

命令：

```bash
curl --noproxy '*' -s -H 'X-Scope-OrgID: tenant1' \
  -o /tmp/enterprise_agent_loki_labels.txt \
  -w "%{http_code}" \
  http://localhost:3100/loki/api/v1/labels
```

结果：

```text
200
```

说明：

- Loki HTTP API 可达。
- 当前 Loki 查询 API 需要 `X-Scope-OrgID`，本次使用 `LOKI_TENANT_ID=tenant1`。

## 从 agent-worker 访问 local platform 查询 Loki

命令：

```bash
docker compose exec agent-worker python -c "import json, urllib.request; payload={'service':'order-service','query':'MaterialNotEnoughException','minutes':15,'limit':20}; req=urllib.request.Request('http://local-internal-api-platform:9000/tools/loki/query', data=json.dumps(payload).encode(), headers={'content-type':'application/json','x-correlation-id':'doc-test-worker-to-local-loki'}, method='POST'); print(urllib.request.urlopen(req, timeout=20).read().decode())"
```

结果：

```json
{
  "summary": {
    "service": "order-service",
    "query": "MaterialNotEnoughException",
    "logql": "{service=\"order-service\"} |= \"MaterialNotEnoughException\"",
    "minutes": 15,
    "line_count": 0,
    "highlights": [],
    "streams": [],
    "truncated": false
  },
  "raw": {
    "result_type": "streams",
    "result_count": 0
  },
  "truncated": false,
  "metadata": {
    "source": "local-loki",
    "duration_ms": 28,
    "request_id": "doc-test-worker-to-local-loki"
  }
}
```

## 从 local platform 容器内自测 Loki 查询

命令：

```bash
docker compose exec local-internal-api-platform python -c "import json, urllib.request; payload={'cluster':'mes-cluster','query':'info','minutes':15,'limit':20}; req=urllib.request.Request('http://127.0.0.1:9000/tools/loki/query', data=json.dumps(payload).encode(), headers={'content-type':'application/json','x-correlation-id':'doc-test-local-platform'}, method='POST'); print(urllib.request.urlopen(req, timeout=20).read().decode())"
```

<!-- {cluster="mes-cluster"} |= `Alloy` -->

结果：

```json
{
  "summary": {
    "service": "order-service",
    "query": "MaterialNotEnoughException",
    "logql": "{service=\"order-service\"} |= \"MaterialNotEnoughException\"",
    "minutes": 15,
    "line_count": 0,
    "highlights": [],
    "streams": [],
    "truncated": false
  },
  "raw": {
    "result_type": "streams",
    "result_count": 0
  },
  "truncated": false,
  "metadata": {
    "source": "local-loki",
    "duration_ms": 8,
    "request_id": "doc-test-local-platform"
  }
}
```

## 结论

`local-tools` 真实 Loki 工具链验证通过：

```text
agent-worker
  -> local-internal-api-platform:9000
  -> host.docker.internal:3100
  -> Loki query_range
```

本次查询没有命中日志：

```text
line_count = 0
```

但链路本身是通的，证据是：

```text
metadata.source = local-loki
Loki buildinfo HTTP 200
Loki labels HTTP 200 with X-Scope-OrgID: tenant1
```

## 后续排查

如果后续查询仍然 `line_count=0`，优先检查：

```text
1. Loki 中是否存在 service="order-service" 这个 label。
2. 日志是否在最近 15 分钟内。
3. 日志中是否真的包含 MaterialNotEnoughException。
4. 当前 Loki tenant 是否应该是 tenant1。
5. 是否需要把 label 从 service 改成 app/job/container。
```
