## Why

当前 Agent 执行链路已经能通过 RabbitMQ、PostgreSQL、Claude Code Agent Runtime 跑通，但只读工具仍默认走 `FakeInternalApiClient`。下一步需要把 Claude 工具调用真正接到 Internal API Platform，使 Agent 能基于真实 ER / 业务图 / Loki / Redis / 数据库证据生成诊断报告，同时保持 Agent Runtime 不直连任何业务数据源。

## What Changes

- 增加可配置的真实 Internal API Platform HTTP 客户端装配，生产/Compose 可通过环境变量选择 fake 或 real internal tools。
- 固化 MVP 六个只读工具到内部平台的 HTTP 契约：
  - `get_er_context`
  - `get_business_flow_context`
  - `query_loki`
  - `query_database`
  - `query_redis_get`
  - `query_redis_scan`
- 为内部平台调用增加认证头、超时、请求 ID / job 上下文透传、错误分类和安全响应归一化。
- 保持 Agent 侧 SQL / Redis / Loki 本地预校验，并要求内部平台再次执行权限、限流、脱敏和审计，形成双层防护。
- 增加本地 mock Internal API Platform 或测试替身，使 Docker Compose 可以验证“Claude tool -> ToolRegistry -> HTTP client -> internal platform response -> tool call audit -> final report”的闭环。
- 更新 README / `.env.example`，说明内部平台地址、鉴权 token、超时、启用 real tools 的方式和 curl 验证流程。

非目标：

- 不实现真实 Loki、Redis、业务数据库、ER 图存储或业务图存储网关本身。
- 不允许任何写操作、删除操作、重启、发版、代码修改或审批执行。
- 不做 Web 配置平台。
- 不改变 Claude Code Agent SDK 接入方式。

## Capabilities

### New Capabilities

- `internal-tool-platform-integration`: 定义真实 Internal API Platform HTTP 集成、认证、错误分类、响应归一化和本地验证能力。

### Modified Capabilities

- `readonly-tool-platform`: 将只读工具从 fake-only 合约扩展为可运行的真实内部平台调用合约，并补充跨平台调用的安全和审计要求。
- `agent-audit-permission`: 补充内部平台调用失败、拒绝、截断、脱敏等场景下的审计记录要求。

## Impact

- 影响 `backend/app/shared/config.py`：新增内部平台启用开关、认证 token、请求超时等配置。
- 影响 `backend/app/bootstrap.py`：根据配置注入 `FakeInternalApiClient` 或 `HttpInternalApiClient`，测试 runtime 默认仍使用 fake。
- 影响 `backend/app/modules/internal_tools/infrastructure/internal_api_client.py`：完善 HTTP client 的 endpoint、headers、timeout、错误映射和响应解析。
- 影响 `backend/app/modules/internal_tools/application/tools.py`：确保调用内部平台前后均记录安全摘要、错误、耗时和审计事件。
- 影响 Docker Compose / README / `.env.example`：增加内部平台配置与本地 mock 验证说明。
- 影响测试：新增 HTTP client 单元测试、工具服务集成测试、Docker/mock 闭环验证测试。
