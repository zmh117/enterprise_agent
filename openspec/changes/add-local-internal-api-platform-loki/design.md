## Context

现有 Agent 执行链路已经支持：

- API / Worker 通过 `FEATURE_REAL_INTERNAL_TOOLS=true` 使用 `HttpInternalApiClient`。
- `HttpInternalApiClient` 调用固定 Internal API Platform endpoint。
- `mock-internal-api-platform` 可用于本地 fake 工具链验证。
- 真实 Claude/DeepSeek 可通过 `FEATURE_REAL_CLAUDE=true` 启用。

当前缺口是：用户希望进行“真实 Claude/DeepSeek + 真实 Loki”的本地联调，但还没有独立真实 Internal API Platform。按照现有架构，Agent Worker 不应直接连接 Loki；因此需要新增一个本地开发用 Internal API Platform 服务，由它负责连接宿主机 Loki。

本地 Loki 地址：

```text
宿主机：http://localhost:3100
容器内：http://host.docker.internal:3100
```

## Goals / Non-Goals

**Goals:**

- 支持 `local-internal-api-platform` Compose profile，用真实 Loki 替代 mock Loki。
- 保持 Agent Runtime 只依赖 `INTERNAL_API_BASE_URL`，不直接知道 Loki 地址。
- 实现 `/tools/loki/query` 到 Loki HTTP API 的只读转发和结果摘要。
- 对 Loki 查询做时间范围、行数、服务名/selector、响应大小边界控制。
- 支持真实 Claude/DeepSeek + local platform 的端到端诊断验证。
- 保持数据库、Redis 工具默认禁用，避免误连真实数据源。

**Non-Goals:**

- 不实现生产级 Internal API Platform。
- 不接入真实数据库或 Redis。
- 不实现 ER 图/业务图真实检索，只返回明确的本地占位上下文。
- 不开放任何写操作、删除操作、重启操作或发版操作。
- 不把 Loki 连接逻辑放进 Agent runtime、`ReadOnlyToolService` 或 Claude SDK client。

## Decisions

### 1. 新增本地平台服务，而不是让 Worker 直连 Loki

实现一个新的 FastAPI factory，例如：

```text
backend/app/local_internal_api_platform.py
```

或在后续实现中拆成：

```text
backend/app/modules/local_internal_api_platform/
  app.py
  loki_client.py
  schemas.py
```

该服务暴露与真实 Internal API Platform 相同的 MVP endpoint。Agent Worker 仍然通过：

```text
INTERNAL_API_BASE_URL=http://local-internal-api-platform:9000
```

调用工具。

替代方案是让 `ReadOnlyToolService` 直接连 Loki。拒绝该方案，因为它会破坏“Agent 只调用内部工具平台”的架构边界，并让生产迁移变困难。

### 2. Loki 使用 `/loki/api/v1/query_range`

`query_loki` 的输入包含：

```json
{
  "service": "order-service",
  "query": "MaterialNotEnoughException",
  "minutes": 15,
  "limit": 100
}
```

本地平台构造 Loki LogQL：

```text
{service="<service>"} |= "<query>"
```

如果 `query` 为空，则只使用服务 selector：

```text
{service="<service>"}
```

实现时需要限制：

- `minutes <= LOKI_MAX_MINUTES`
- `limit <= LOKI_MAX_LINES`
- `service` 不能为空，且只允许安全字符
- `query` 作为日志过滤文本处理，不允许直接传入任意完整 LogQL

替代方案是允许 Agent 直接传完整 LogQL。当前阶段拒绝该方案，因为真实 Claude 联调时更容易产生无界 selector 或高成本查询。

### 3. 返回统一 Internal API envelope

本地平台必须返回：

```json
{
  "summary": {},
  "raw": {},
  "truncated": false,
  "metadata": {
    "request_id": "corr-1",
    "source": "local-loki",
    "duration_ms": 12
  }
}
```

`summary` 面向 Agent 和持久化，包含：

- `service`
- `query`
- `minutes`
- `line_count`
- `highlights`
- `streams`
- `truncated`

`raw` 仅用于 HTTP client 内存返回；实际落库仍由上游 `ReadOnlyToolService` 做 bounded summary。

### 4. 未接入工具默认显式禁用

本地平台中的数据库和 Redis endpoint 不返回 fake 业务数据，而是返回 501 或 403，并使用安全错误结构：

```json
{
  "error": {
    "code": "tool_not_configured",
    "message": "database tool is not configured in local internal platform"
  }
}
```

这样真实 Claude 联调时，如果模型尝试数据库/Redis 工具，系统会清楚显示“未配置”，而不是误以为查到了真实数据。

### 5. Compose 用独立 profile 区分 mock 和 local

新增服务：

```text
local-internal-api-platform
```

建议 profile：

```text
local-tools
```

启动真实 Claude + 本地真实 Loki：

```bash
FEATURE_REAL_CLAUDE=true \
FEATURE_REAL_INTERNAL_TOOLS=true \
INTERNAL_API_BASE_URL=http://local-internal-api-platform:9000 \
LOKI_BASE_URL=http://host.docker.internal:3100 \
docker compose --profile local-tools up -d --build local-internal-api-platform api-server agent-worker
```

`mock-tools` profile 继续保留，用于不依赖 Loki 或 DeepSeek 的确定性测试。

## Risks / Trade-offs

- [Risk] 容器内 `localhost:3100` 指向容器自身，不是宿主机 Loki。  
  → Mitigation: Compose 默认配置使用 `http://host.docker.internal:3100`，文档明确说明 Mac Docker Desktop 的访问方式。

- [Risk] 真实 Claude 可能调用数据库或 Redis 工具。  
  → Mitigation: 本地平台默认对数据库/Redis 返回 `tool_not_configured`，并由 Agent 汇报限制，而不是返回假数据。

- [Risk] Loki 查询过大导致本地环境卡顿。  
  → Mitigation: 双层限制，Agent 侧已有 `MAX_LOKI_MINUTES` / `MAX_LOKI_LINES`，本地平台再用 `LOKI_MAX_MINUTES` / `LOKI_MAX_LINES` 限制。

- [Risk] 日志内容可能包含敏感信息。  
  → Mitigation: 本地平台只返回 bounded summary 和有限 highlights；持久化路径继续使用 bounded summary 与脱敏逻辑。

- [Risk] DeepSeek/Claude 真实运行成本不可控。  
  → Mitigation: 文档要求真实联调显式设置 `FEATURE_REAL_CLAUDE=true`，并保留 `AGENT_MAX_TURNS`、`AGENT_TIMEOUT_SECONDS` 控制。

## Migration Plan

1. 新增 local platform 代码和配置，默认不启用。
2. 新增 `local-tools` Compose profile，不影响当前 `mock-tools` 和默认服务。
3. 增加测试覆盖 Loki client、endpoint、禁用工具和配置装配。
4. 更新 README，给出真实 Claude + local Loki 的启动和 curl 验证流程。
5. 使用本机 Loki `localhost:3100` 验证端到端 job。

回滚方式：停止使用 `local-tools` profile，恢复 `mock-tools` 或生产 `INTERNAL_API_BASE_URL` 即可；Agent runtime 不需要改回。

## Open Questions

- Loki 服务标签是否固定为 `service`，还是你的 Loki 日志使用 `app`、`job`、`container` 等其它 label？
- 是否需要支持 tenant header，例如 `X-Scope-OrgID`？
- 第一版是否只允许 `service + keyword` 查询，还是需要允许一小段受限 LogQL？
