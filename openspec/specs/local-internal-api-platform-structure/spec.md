# local-internal-api-platform-structure Specification

## Purpose
TBD - created by archiving change modularize-local-internal-api-platform. Update Purpose after archive.
## Requirements
### Requirement: Top-level local platform entrypoint remains compatible
系统 SHALL 保留本地 Internal API Platform 的顶层 FastAPI factory 入口，使现有 Compose 和 uvicorn 启动路径无需迁移即可继续启动服务。

#### Scenario: Compose command imports the top-level entrypoint
- **WHEN** local tools profile 使用 `app.local_internal_api_platform:create_app` 启动 `local-internal-api-platform`
- **THEN** Python import 能解析到 FastAPI factory，并创建本地平台应用实例

#### Scenario: Top-level entrypoint delegates implementation
- **WHEN** 开发者查看 `backend/app/local_internal_api_platform.py`
- **THEN** 该文件只保留入口兼容职责，不包含 endpoint、Loki gateway、summary 转换或数据源访问实现细节

### Requirement: Local platform implementation is modularized
系统 SHALL 将本地 Internal API Platform 的实现拆分到 `backend/app/modules/local_internal_api_platform/`，并按职责隔离 app factory、routes、schemas、Loki gateway 和 envelope/error helper。

#### Scenario: App factory lives in the module package
- **WHEN** 代码调用 `app.modules.local_internal_api_platform.app.create_app`
- **THEN** 该 factory 加载配置、创建本地平台依赖并注册工具 endpoint

#### Scenario: Loki behavior lives outside routes
- **WHEN** `POST /tools/loki/query` 被调用
- **THEN** route 层只负责 HTTP 编排，Loki 输入校验、LogQL 构造、upstream 查询、错误分类和 summary 转换由 Loki gateway 模块处理

#### Scenario: Shared response helpers are isolated
- **WHEN** context placeholder、Loki 成功响应或禁用工具错误需要返回 Internal API Platform 兼容结构
- **THEN** 标准 envelope、`tool_not_configured` 和安全错误文本处理由共享 helper 提供，而不是散落在 route 或 gateway 代码中

### Requirement: Modularization preserves local platform behavior
系统 MUST 保持本地 Internal API Platform 的外部 endpoint、成功响应 envelope、错误结构和安全边界不变。

#### Scenario: Health endpoint behavior is unchanged
- **WHEN** 开发者请求 `GET /health`
- **THEN** 响应仍包含 `status`、`mode=local-internal-api-platform` 和 Loki 配置摘要

#### Scenario: Placeholder context behavior is unchanged
- **WHEN** Agent 调用 `/tools/context/er` 或 `/tools/context/business-flow`
- **THEN** 响应仍返回明确标记为 local placeholder 的 summary、raw、truncated 和 metadata envelope

#### Scenario: Loki query behavior is unchanged
- **WHEN** Agent 调用 `/tools/loki/query`
- **THEN** 本地平台仍按现有 service、keyword、minutes、limit 和 response chars 限制查询 Loki，并返回 bounded summary、raw 摘要、truncated 标记和 metadata

#### Scenario: Unconfigured tools remain disabled
- **WHEN** Agent 调用 `/tools/database/query`、`/tools/redis/get` 或 `/tools/redis/scan`
- **THEN** 本地平台仍返回安全的 `tool_not_configured` 错误，并且 MUST NOT 连接真实数据库或 Redis

### Requirement: Tests cover both entrypoint compatibility and module internals
系统 SHALL 更新测试，使本地平台 endpoint 回归覆盖顶层入口，同时直接覆盖模块化后的 Loki gateway 和 helper 行为。

#### Scenario: Endpoint tests use top-level entrypoint
- **WHEN** 测试验证 `/health`、context endpoint、Loki endpoint 和禁用工具 endpoint
- **THEN** 测试通过 `app.local_internal_api_platform.create_app` 创建应用，证明现有启动入口仍可用

#### Scenario: Unit tests use module imports
- **WHEN** 测试验证 LogQL 构造、Loki 输入校验、upstream 错误分类、summary 截断和敏感字段脱敏
- **THEN** 测试直接导入 `app.modules.local_internal_api_platform` 下的实现模块，证明内部职责可被单独测试

