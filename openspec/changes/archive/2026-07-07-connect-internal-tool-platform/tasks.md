## 1. 配置与装配边界

- [x] 1.1 扩展 `backend/app/shared/config.py`，新增 `FEATURE_REAL_INTERNAL_TOOLS`、`INTERNAL_API_AUTH_TOKEN`、`INTERNAL_API_TIMEOUT_SECONDS`、`INTERNAL_API_MAX_RESPONSE_CHARS` 配置。
- [x] 1.2 调整 `Container.internal_api_client` 类型为 `InternalApiClient` 协议，而不是固定 `FakeInternalApiClient`。
- [x] 1.3 修改 `backend/app/bootstrap.py`，让 API / worker runtime 在 `FEATURE_REAL_INTERNAL_TOOLS=true` 时注入 `HttpInternalApiClient`。
- [x] 1.4 确认 `build_test_container()` 默认仍注入 `FakeInternalApiClient`，所有无网络单元测试不依赖真实内部平台。
- [x] 1.5 增加装配测试，覆盖 real/fake internal tools feature flag 与 test runtime 默认行为。

## 2. Internal API HTTP Client 契约

- [x] 2.1 定义 `ToolRequestContext` 或等价 DTO，包含 `job_id`、`user_id`、`project_code`、`correlation_id`。
- [x] 2.2 调整 `InternalApiClient` 协议和 `ReadOnlyToolService` 调用路径，将 tool 执行上下文传给 internal client。
- [x] 2.3 完善 `HttpInternalApiClient` 六个 endpoint 映射：ER、业务图、Loki、数据库、Redis get、Redis scan。
- [x] 2.4 为 HTTP 请求增加 `Authorization`、`X-Agent-Job-Id`、`X-Agent-User-Id`、`X-Agent-Project-Code`、`X-Correlation-Id` headers。
- [x] 2.5 实现统一响应 envelope 解析：优先使用 `summary`，兼容无 `summary` 的 legacy JSON body。
- [x] 2.6 确保 `ToolResult.raw` 只保留内存使用，持久化只写 bounded summary。

## 3. 安全策略与错误分类

- [x] 3.1 保留 Agent 侧 SQL / Redis / Loki 预校验，并在测试中证明不安全请求不会被发送到 HTTP client。
- [x] 3.2 将 HTTP 429、502、503、504、连接超时和临时网络错误映射为 retryable execution error。
- [x] 3.3 将 HTTP 400、401、403、404 和平台 `policy_denied` 映射为非重试安全错误或 `ToolPolicyError`。
- [x] 3.4 对错误消息、headers、请求体、响应体做脱敏，确保 token 和敏感字段不会进入日志、audit 或 `agent_tool_call`。
- [x] 3.5 记录每次成功、拒绝、失败工具调用的 duration、risk_level、audit_id 和平台 metadata 摘要。

## 4. 本地 Mock Internal API Platform

- [x] 4.1 增加本地 mock Internal API Platform 服务或测试 HTTP server，实现六个 MVP endpoint。
- [x] 4.2 mock endpoint 返回统一 envelope，并提供成功、policy denial、timeout / 5xx、large response 场景。
- [x] 4.3 更新 `docker-compose.yml`，可选启动 mock internal-api-platform 并让 worker 指向该服务。
- [x] 4.4 增加 Compose 验证命令：提交 debug job，worker 通过 HTTP mock 工具执行并生成报告。
- [x] 4.5 明确 mock 仅用于本地验证，不作为生产内部平台实现。

## 5. 测试覆盖

- [x] 5.1 新增 `HttpInternalApiClient` 单元测试，覆盖 headers、payload、endpoint、envelope 解析和 legacy body 兼容。
- [x] 5.2 新增 HTTP 错误分类测试，覆盖 retryable、non-retryable、policy_denied 和脱敏。
- [x] 5.3 扩展 `ReadOnlyToolService` 测试，证明 unsafe SQL / Redis / Loki 请求在 HTTP 调用前被拒绝。
- [x] 5.4 增加工具调用审计测试，证明成功、拒绝、失败都写入安全摘要和 audit linkage。
- [x] 5.5 增加 worker/debug API 集成测试，使用 mock internal API client 验证 job 最终 `SUCCEEDED` 且持久化真实工具事件。
- [x] 5.6 确认真实 Claude runtime 与 real internal tools 可组合，至少通过 fake SDK / mock platform 覆盖 tool loop。

## 6. 文档与运行验证

- [x] 6.1 更新 `.env.example`，加入 real internal tools 相关配置，不写入真实 token。
- [x] 6.2 更新 `backend/README.md` 和中文根 `README.md`，说明 fake 模式、mock 模式、真实内部平台模式的启动方式。
- [x] 6.3 文档化内部平台 HTTP endpoint、请求字段、headers、响应 envelope、错误码约定。
- [x] 6.4 运行 `make check`，确保格式、lint、类型检查和测试通过。
- [x] 6.5 运行 `openspec validate connect-internal-tool-platform`。
- [x] 6.6 运行 Docker Compose mock HTTP 工具闭环验证，并记录预期 curl 输出。
