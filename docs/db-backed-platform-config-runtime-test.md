# DB-backed Platform Config Runtime 测试记录

目标：验证 Web 配置平台写入 PostgreSQL 后，正式 `internal-api-platform` 运行时优先从数据库读取 topology、resource binding 和 access grant，而不是继续依赖 YAML。

```text
api-server
  -> /api/platform/import/topology-yaml
  -> PostgreSQL platform_* tables
  -> internal-api-platform startup snapshot
  -> /health config.source=database
  -> /tools/resolve 或只读工具 endpoint
```

默认不调用真实 Claude/DeepSeek：

```env
FEATURE_REAL_CLAUDE=false
FEATURE_REAL_INTERNAL_TOOLS=true
INTERNAL_API_BASE_URL=http://internal-api-platform:9000
```

## 1. 启动基础服务

```bash
FEATURE_REAL_CLAUDE=false \
FEATURE_REAL_INTERNAL_TOOLS=true \
INTERNAL_API_BASE_URL=http://internal-api-platform:9000 \
docker compose --profile real-tools up -d --build postgres rabbitmq api-server internal-api-platform agent-worker
```

检查：

```bash
docker compose --profile real-tools ps
```

必须看到：

```text
postgres
rabbitmq
api-server
internal-api-platform
agent-worker
```

## 2. 导入 YAML 到 PostgreSQL

```bash
curl --noproxy '*' -s -X POST http://127.0.0.1:8000/api/platform/import/topology-yaml \
  -H 'content-type: application/json' \
  -H 'x-admin-user-id: local-user' \
  -d '{"path":"config/internal_platform_topology.example.yaml"}'
```

预期：

```json
{
  "import": {
    "errors": []
  }
}
```

## 3. 查看 DB-backed Snapshot

```bash
curl --noproxy '*' -s http://127.0.0.1:8000/api/platform/topology-snapshot
```

关键预期：

```text
snapshot.source = database
snapshot.valid = true
snapshot.resource_count > 0
snapshot.access_grant_count > 0
snapshot.config_hash 是 64 位 sha256
```

响应中允许出现：

```text
secret://sanjiu/guanlan/db_password
env:ORDER_DB_PASSWORD
```

不允许出现真实明文：

```text
真实 password
真实 token
真实 api key
```

## 4. 重启 Internal API Platform 读取 DB Snapshot

当前 runtime 使用启动时 snapshot。修改平台配置后，需要重启 `internal-api-platform`，或后续实现 reload endpoint 后显式 reload。

```bash
docker compose --profile real-tools restart internal-api-platform
```

检查 health：

```bash
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; print(json.dumps(json.loads(urllib.request.urlopen('http://127.0.0.1:9000/health').read().decode()), ensure_ascii=False, indent=2))"
```

关键预期：

```text
status = ok
mode = internal-api-platform
config.source = database
config.valid = true
config.resource_count > 0
config.config_hash 存在
```

如果 `config.source=yaml`，说明数据库没有启用 topology，运行时走了本地 fallback。

如果 `config.source=database-invalid`，说明数据库里存在启用 topology 但配置不完整。此时必须先修复 DB 配置，不能依赖 YAML 静默绕过。

## 5. 验证 Runtime Resolve

```bash
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; payload={'environment':'sanjiu','base':'guanlan','workshop':'GL001','kind':'database'}; req=urllib.request.Request('http://127.0.0.1:9000/tools/resolve', data=json.dumps(payload).encode(), headers={'content-type':'application/json','X-Agent-User-Id':'local-user'}, method='POST'); print(urllib.request.urlopen(req).read().decode())"
```

预期：

```text
summary.environment = sanjiu
summary.base = guanlan
summary.workshop = GL001
summary.kind = database
metadata.source = internal-api-platform
```

## 6. 验证只读工具边界

Schema directory：

```bash
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; payload={'environment':'sanjiu','base':'guanlan','workshop':'GL001','limit':20}; req=urllib.request.Request('http://127.0.0.1:9000/tools/schema/directory', data=json.dumps(payload).encode(), headers={'content-type':'application/json','X-Agent-User-Id':'local-user'}, method='POST'); print(urllib.request.urlopen(req).read().decode())"
```

Loki labels：

```bash
docker compose --profile real-tools exec internal-api-platform python -c "import json, urllib.request; payload={'environment':'sanjiu','base':'guanlan','workshop':'GL001','minutes':15,'limit':20}; req=urllib.request.Request('http://127.0.0.1:9000/tools/loki/labels', data=json.dumps(payload).encode(), headers={'content-type':'application/json','X-Agent-User-Id':'local-user'}, method='POST'); print(urllib.request.urlopen(req).read().decode())"
```

如果未配置真实 DB/Redis/Loki 或上游不可达，工具可以返回安全错误；判断重点是：

```text
Agent runtime 不直连外部源
请求进入 internal-api-platform
source 仍为 database
错误不泄漏密钥
只读策略不被绕过
```

## 7. YAML Fallback 边界

允许 fallback：

```text
PostgreSQL 没有启用 topology
且配置了 INTERNAL_PLATFORM_TOPOLOGY_FILE
```

禁止 fallback：

```text
PostgreSQL 已有启用 topology
但 resource binding 缺 endpoint、engine 或 secret ref
```

这种情况必须显示：

```text
config.source = database-invalid
status = degraded
```

## 8. 可选真实 Loki / MySQL 验证

真实 Loki：

```env
SECRET_SANJIU_GUANLAN_LOKI_URL=http://host.docker.internal:3100
```

真实 MySQL：

```env
SECRET_SANJIU_GUANLAN_DB_HOST=host.docker.internal
SECRET_SANJIU_GUANLAN_DB_USER=reader
SECRET_SANJIU_GUANLAN_DB_PASSWORD=...
```

只允许只读账号。不要用 root、DBA 或有写权限的账号做 Agent 工具验证。
