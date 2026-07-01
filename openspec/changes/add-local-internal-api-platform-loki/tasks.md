## 1. 配置与模块结构

- [x] 1.1 新增本地平台配置项：`LOKI_BASE_URL`、`LOKI_MAX_MINUTES`、`LOKI_MAX_LINES`、`LOKI_MAX_RESPONSE_CHARS`、可选 `LOKI_TENANT_ID`。
- [x] 1.2 新增 `backend/app/local_internal_api_platform.py` 或等价模块入口，提供 FastAPI factory。
- [x] 1.3 将本地平台代码与 `mock_internal_api_platform` 分离，避免真实 Loki 联调返回 mock 业务证据。
- [x] 1.4 增加健康检查 endpoint，返回 local platform mode、Loki base URL 是否配置、限制参数。

## 2. Loki Gateway 实现

- [x] 2.1 实现 Loki query DTO 校验：service 必填、安全字符校验、minutes/limit 上限校验、query 长度限制。
- [x] 2.2 实现 LogQL 构造：`{service="<service>"}`，非空 query 追加安全文本过滤。
- [x] 2.3 使用 Loki `/loki/api/v1/query_range` 查询宿主机 Loki，容器默认使用 `http://host.docker.internal:3100`。
- [x] 2.4 将 Loki 返回转换为统一 envelope：`summary`、`raw`、`truncated`、`metadata`。
- [x] 2.5 对日志行做 bounded summary、截断标记和敏感字段脱敏。
- [x] 2.6 将 Loki 超时、连接错误、5xx 映射为 retryable HTTP 响应；将校验/策略错误映射为 non-retryable 响应。

## 3. 本地平台 Endpoint

- [x] 3.1 实现 `POST /tools/loki/query`，真实查询 Loki 并返回摘要。
- [x] 3.2 实现 `POST /tools/context/er`，返回明确标记为 local placeholder 的 ER 上下文。
- [x] 3.3 实现 `POST /tools/context/business-flow`，返回明确标记为 local placeholder 的业务流上下文。
- [x] 3.4 实现 `POST /tools/database/query`，默认返回 `tool_not_configured`，不执行 SQL。
- [x] 3.5 实现 `POST /tools/redis/get` 和 `POST /tools/redis/scan`，默认返回 `tool_not_configured`，不访问 Redis。
- [x] 3.6 确保所有 endpoint 返回结构与 `HttpInternalApiClient` 兼容。

## 4. Docker Compose 与运行模式

- [x] 4.1 新增 `local-internal-api-platform` Compose 服务，使用 `local-tools` profile。
- [x] 4.2 为 `api-server` 和 `agent-worker` 增加 local tools 运行所需环境变量透传。
- [x] 4.3 文档化真实 Claude + local Loki 启动命令，使用 `FEATURE_REAL_CLAUDE=true`、`FEATURE_REAL_INTERNAL_TOOLS=true`、`INTERNAL_API_BASE_URL=http://local-internal-api-platform:9000`。
- [x] 4.4 保留 `mock-tools` profile，确保 mock 验证和 local Loki 验证互不影响。
- [x] 4.5 确认容器内访问宿主机 Loki 使用 `host.docker.internal:3100`，并在 README 中说明。

## 5. 测试覆盖

- [x] 5.1 新增 Loki LogQL 构造和输入校验单元测试。
- [x] 5.2 新增 Loki 成功响应转换测试，覆盖 stream labels、line count、highlights、metadata。
- [x] 5.3 新增 Loki 大响应截断和敏感字段脱敏测试。
- [x] 5.4 新增 Loki 不可用、超时、5xx、策略拒绝的错误分类测试。
- [x] 5.5 新增本地平台 endpoint 测试，覆盖 context placeholder、database/Redis `tool_not_configured`。
- [x] 5.6 扩展 `HttpInternalApiClient` 或集成测试，确认 local platform envelope 可被 worker 工具链持久化。

## 6. 文档与真实联调

- [x] 6.1 更新 `.env.example`，加入 local Loki 相关配置，不写入真实 DeepSeek key。
- [x] 6.2 更新中文根 `README.md` 和 `backend/README.md`，区分 fake、mock、local-loki、real-platform 四种模式。
- [x] 6.3 运行 `make check`，确保格式、lint、类型检查和测试通过。
- [x] 6.4 运行 `openspec validate add-local-internal-api-platform-loki`。
- [x] 6.5 在用户确认 Loki 已运行、DeepSeek key 已配置后，启动 `local-tools` profile。
- [ ] 6.6 提交 debug job，确认真实 Claude/DeepSeek 运行、local platform 查询 Loki、job 最终进入终态，并可查询 steps/tool-calls。
- [ ] 6.7 记录真实联调命令、job_id、状态、Loki tool-call 摘要和失败排查方法。
