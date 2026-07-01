## Why

当前真实 Claude/DeepSeek 联调只能使用 mock Internal API Platform，无法用本机真实 Loki 验证日志诊断链路。需要增加一个本地开发用的 Internal API Platform 服务，让 Agent 在保持“只通过内部平台调用工具”的边界下，真实查询宿主机 Loki `localhost:3100`。

## What Changes

- 新增本地 `local-internal-api-platform` 服务，用于开发和联调，不作为生产内部平台实现。
- 将 `query_loki` endpoint 真实转发到 Loki HTTP API，容器内默认通过 `http://host.docker.internal:3100` 访问宿主机 Loki。
- 保持 `get_er_context`、`get_business_flow_context` 为本地安全占位响应，避免阻塞真实 Claude + Loki 联调。
- 对 `query_database`、`query_redis_get`、`query_redis_scan` 默认返回明确的未配置/禁用错误，除非后续显式接入真实数据库或 Redis。
- 增加 Docker Compose profile 和环境变量，支持真实 Claude/DeepSeek + 本地真实 Loki 的端到端验证。
- 增加 Loki 查询边界、错误分类、响应摘要和审计要求，防止无界日志查询或敏感内容直接落库。
- 不改变生产推荐架构：生产仍应接独立 Internal API Platform。

## Capabilities

### New Capabilities

- `local-internal-api-platform`: 定义本地开发用 Internal API Platform 服务，覆盖 Loki 转发、占位上下文、禁用未接入工具、Compose 启动和真实联调行为。

### Modified Capabilities

- `readonly-tool-platform`: 明确本地 Internal API Platform 也必须遵守现有只读工具契约、固定 endpoint、bounded summary、工具审计和错误分类要求。

## Impact

- 代码：新增本地 Internal API Platform FastAPI 服务、Loki gateway/client、配置项、Docker Compose profile。
- API：新增本地实现的 `/tools/context/er`、`/tools/context/business-flow`、`/tools/loki/query`、`/tools/database/query`、`/tools/redis/get`、`/tools/redis/scan`。
- 配置：新增 `LOKI_BASE_URL`、Loki 查询限制、local internal platform profile 和真实 Claude 联调环境变量说明。
- 外部系统：开发环境需要可访问 Loki，宿主机 Loki 地址为 `http://localhost:3100`，容器内使用 `http://host.docker.internal:3100`。
- 测试：需要覆盖 Loki URL 构造、查询限制、成功摘要、Loki 不可用、禁用数据库/Redis 工具、真实 Claude + local platform 联调路径。
