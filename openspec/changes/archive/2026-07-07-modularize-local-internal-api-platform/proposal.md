## Why

当前 `backend/app/local_internal_api_platform.py` 同时承载 FastAPI 入口、endpoint、Loki gateway、DTO、错误分类、脱敏和 envelope 组装。它作为 MVP 可运行，但继续接入 DB、Redis、ER 或业务图真实网关时会让本地 Internal API Platform 变成难维护的单文件实现。

需要在保持 Compose/uvicorn 顶层入口不变的前提下，把本地平台实现拆入 `app/modules/local_internal_api_platform/`，让入口稳定、实现可扩展，并保护 Agent 只通过 Internal API Platform 调工具的边界。

## What Changes

- 保留 `backend/app/local_internal_api_platform.py` 作为顶层兼容入口，继续暴露 `create_app`，不改变 `docker-compose.yml` 的启动目标。
- 新增 `backend/app/modules/local_internal_api_platform/` 模块，将 app factory、路由、Loki gateway、schema、envelope/error helper 拆到清晰文件中。
- 迁移现有 local platform 测试引用，确保 `/health`、context placeholder、`query_loki`、DB/Redis `tool_not_configured` 行为保持不变。
- 保持 `mock-internal-api-platform`、`local-tools` profile、`HttpInternalApiClient` endpoint 契约和 Agent runtime 依赖不变。
- 不新增真实 DB/Redis/ER/业务图接入；本变更只做结构重组和回归验证。

## Capabilities

### New Capabilities

- `local-internal-api-platform-structure`: 约束本地 Internal API Platform 的顶层入口兼容、模块化实现边界、行为不变和测试覆盖。

### Modified Capabilities

- 无。

## Impact

- 代码：`backend/app/local_internal_api_platform.py`、新增 `backend/app/modules/local_internal_api_platform/`、相关 `__init__.py`。
- 测试：`backend/tests/test_local_internal_api_platform.py` 的 import 路径和必要覆盖。
- Docker/运行：`docker-compose.yml` 当前可保持不变；若入口仍 re-export `create_app`，Compose command 不需要调整。
- 架构边界：继续保持 Agent runtime 只依赖 `INTERNAL_API_BASE_URL`，不直接连接 Loki、DB、Redis、ER 或业务图存储。
