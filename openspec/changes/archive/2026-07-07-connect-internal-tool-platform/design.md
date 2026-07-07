## Context

当前只读诊断 Agent 已经具备：

```text
DingTalk / Debug API
  -> AgentJob
  -> RabbitMQ
  -> Agent Worker
  -> Claude Code Agent Runtime
  -> ToolRegistry
  -> ReadOnlyToolService
  -> FakeInternalApiClient
```

现有 `HttpInternalApiClient` 只是一个最小 HTTP 雏形，运行时仍在 `bootstrap.py` 中固定注入 `FakeInternalApiClient`。因此真实 Claude 即使能发起工具调用，拿到的仍是本地假数据。这个 change 要把工具层切换成可运行、可审计、可测试的 Internal API Platform 调用。

关键约束：

- Agent Runtime 不允许直连业务数据库、Redis、Loki、ER 图或业务图存储。
- MVP 仍只允许只读诊断，不引入写操作、审批执行或自动修复。
- 测试 runtime 和默认本地开发必须能继续使用 fake client，避免每次单测依赖内网。
- 真实内部平台要承担第二层权限、限流、脱敏和审计；Agent 侧保留第一层预校验。

## Goals / Non-Goals

**Goals:**

- 通过配置让 API / worker runtime 可以选择 `FakeInternalApiClient` 或 `HttpInternalApiClient`。
- 固定六个 MVP 工具的 HTTP endpoint、请求字段和响应 envelope。
- 为 HTTP client 增加 Bearer token、请求 ID、job/user/project 上下文头、超时和错误映射。
- 把内部平台返回的成功、拒绝、超时、限流、上游失败统一映射为 `ToolResult` 或受控异常。
- 确保工具调用记录、audit event、Agent step 中只保存安全摘要，不保存未脱敏 raw payload。
- 提供本地 mock Internal API Platform 验证路径，让 Docker Compose 可以在没有真实内网平台时跑通 HTTP 工具闭环。

**Non-Goals:**

- 不实现真实 Database Gateway、Redis Gateway、Loki Gateway、ER Context Gateway 或 Business Flow Gateway。
- 不设计 Web 配置台的数据模型和页面。
- 不改变 Claude Code Agent SDK、RabbitMQ 或 DingTalk 的核心流程。
- 不增加任何 mutating tool。

## Decisions

### 1. 用显式 feature flag 切换 fake / real internal tools

新增配置建议：

```text
FEATURE_REAL_INTERNAL_TOOLS=false
INTERNAL_API_BASE_URL=http://internal-api-platform.local
INTERNAL_API_AUTH_TOKEN=
INTERNAL_API_TIMEOUT_SECONDS=10
INTERNAL_API_MAX_RESPONSE_CHARS=4000
```

装配规则：

```text
build_test_container        -> FakeInternalApiClient
FEATURE_REAL_INTERNAL_TOOLS=false -> FakeInternalApiClient
FEATURE_REAL_INTERNAL_TOOLS=true  -> HttpInternalApiClient
```

选择显式开关，而不是“只要配置了 base_url 就启用”，原因是本地和 CI 通常会有默认 base url，占位地址不应该导致 worker 误连外部服务。

### 2. HTTP contract 使用统一 envelope

内部平台所有工具 endpoint 使用 `POST`，返回统一 envelope：

```json
{
  "summary": {},
  "raw": {},
  "truncated": false,
  "metadata": {
    "request_id": "...",
    "source": "...",
    "duration_ms": 12
  }
}
```

Agent 侧只依赖 `summary` 生成报告和持久化；`raw` 仅保留在内存中的 `ToolResult.raw`，默认不持久化。

MVP endpoint：

```text
POST /tools/context/er
POST /tools/context/business-flow
POST /tools/loki/query
POST /tools/database/query
POST /tools/redis/get
POST /tools/redis/scan
```

通用 headers：

```text
Authorization: Bearer <INTERNAL_API_AUTH_TOKEN>
X-Agent-Job-Id: <job_id>
X-Agent-User-Id: <user_id>
X-Agent-Project-Code: <project_code>
X-Correlation-Id: <correlation_id>
Content-Type: application/json
```

其中 `job_id/user_id/project_code` 需要从 `ReadOnlyToolService.call_tool()` 传到 `InternalApiClient`，而不是让 HTTP client 从全局状态读取。

### 3. Agent 侧和内部平台双层安全校验

Agent 侧继续执行：

- 用户 / 项目 / 工具 allowlist。
- SQL 只读预校验。
- Redis 只读操作预校验。
- Loki service、时间范围、limit 预校验。

内部平台必须再次执行：

- 数据源授权。
- 实际 SQL / Redis / Loki 策略。
- 限流和超时。
- 返回脱敏和截断。
- 平台侧审计。

这样即使模型生成异常参数，或者 Agent 侧策略有漏洞，内部平台仍是最后一道边界。

### 4. 错误分类必须服务于 job retry

HTTP client 应把错误分为：

```text
RetryableExecutionError:
  - 连接超时
  - DNS / 网络临时失败
  - HTTP 502 / 503 / 504
  - HTTP 429

ToolPolicyError / NonRetryableExecutionError:
  - HTTP 400 参数非法
  - HTTP 401 / 403 鉴权或授权失败
  - HTTP 404 数据源或 endpoint 不存在
  - 内部平台明确返回 policy_denied

ToolPolicyError:
  - SQL / Redis / Loki 策略拒绝
```

工具层失败后仍要写入：

- `agent_tool_call.status=FAILED`
- 安全错误摘要
- duration
- audit event

可重试错误由 worker / `JobRetryService` 处理，不在 HTTP client 内部循环重试，避免一次工具调用阻塞 Agent 太久。

### 5. 本地 mock 平台用于验证 HTTP 闭环

为了让 Docker Compose 不依赖真实内网，增加一个轻量 mock 验证方式。可以是：

```text
mock-internal-api-platform
  -> FastAPI app 或测试内置 HTTP server
  -> 实现六个 endpoint
  -> 返回与真实平台同形的 envelope
```

Compose 验证路径：

```text
FEATURE_REAL_INTERNAL_TOOLS=true
INTERNAL_API_BASE_URL=http://mock-internal-api-platform:9000
FEATURE_REAL_CLAUDE=false 或 true
```

这样可以单独证明：

```text
ToolRegistry
  -> ReadOnlyToolService
  -> HttpInternalApiClient
  -> HTTP mock platform
  -> agent_tool_call / audit_event
```

真实 DeepSeek / Claude 可作为额外手动验证，不作为该 change 的唯一验收条件。

## Risks / Trade-offs

- [Risk] 内部平台响应格式和这里定义的 envelope 不一致 -> 在 HTTP client 做兼容解析，但测试以统一 envelope 为主；README 明确契约。
- [Risk] 真实平台慢导致 Agent job 长时间 RUNNING -> 配置 `INTERNAL_API_TIMEOUT_SECONDS`，超时映射为 retryable 并由 job retry 控制。
- [Risk] raw payload 被误持久化 -> repository 只写 `bounded_summary(result.summary)`，测试断言敏感字段不会进入 `agent_tool_call`。
- [Risk] 本地 mock 通过但真实内网鉴权失败 -> ready/debug endpoint 暴露 internal tools mode 和 base_url 是否配置，但不打印 token。
- [Risk] 双层校验导致错误看起来重复 -> Agent 侧错误用于快速拒绝，内部平台错误用于最终数据源边界；审计中记录拒绝来源。
- [Trade-off] 不在本 change 做 Web 配置 -> 配置仍通过 env 和 seed 控制，但避免在内部工具契约未稳定时过早做 UI。

## Migration Plan

1. 增加 internal tools 相关配置和 `.env.example`。
2. 调整 `InternalApiClient` 协议，使六个工具方法接收 job/user/project/correlation 上下文或统一 `ToolRequestContext`。
3. 完善 `HttpInternalApiClient` 的 headers、timeout、endpoint、响应 envelope、错误映射和脱敏。
4. 调整 `bootstrap.py`，按 `FEATURE_REAL_INTERNAL_TOOLS` 注入 fake 或 real client。
5. 增加 HTTP client 单元测试和 `ReadOnlyToolService` 集成测试。
6. 增加本地 mock Internal API Platform 验证路径，并更新 Docker Compose / README。
7. 运行 `make check`、`openspec validate connect-internal-tool-platform` 和 Docker Compose HTTP 工具闭环验证。

Rollback：

- 将 `FEATURE_REAL_INTERNAL_TOOLS=false`，运行时回到 `FakeInternalApiClient`。
- 已创建的 job、tool_call、audit_event 仍保留，可用于排查失败原因。

## Open Questions

- 真实 Internal API Platform 最终是否已经固定统一 envelope？如果没有，本 change 先以 mock/约定契约为准，后续按真实平台微调。
- 鉴权先用单一 Bearer token，还是需要后续升级为 mTLS / HMAC 签名？MVP 建议 Bearer token。
- 内部平台是否需要接收 DingTalk conversation 信息？MVP 先透传 `job_id/user_id/project_code/correlation_id`。
