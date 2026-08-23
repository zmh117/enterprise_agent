## Implementation evidence

本文件仅记录 `generalize-business-mcp-principal-jwt` 的实施与验证事实，不是 canonical requirement。

### 1. Confirmed-current 实现边界

- 业务 Principal 统一由 `issue_business_mcp_for_job(job_id, server_code)` 签发；生产代码不再存在 `issue_for_job()` 或 Server 专用业务签发方法。
- 代码固定的 MCP Server 鉴权策略只有 `job-context`、`business-principal-jwt`、`file-principal-jwt` 三类；当前生产业务 Principal Server 仍只有 `ones-mcp`。
- Control Plane 按冻结 MCP bindings 为每个业务 Server 各签发一次 JWT，并通过唯一的 `X-MCP-Principal-Token-<Server-Code>` Header 传递。
- Python Runtime 使用只读 `mcp_principal_tokens[server_code]` 与独立 `file_principal_token`；收到的业务 Header 集合必须与请求所需业务 Server 集合严格相等。
- File Principal 的 tenant、workspace、文件 scope、File bridge、File Transfer Context 与沙盒边界保持专用实现。
- 静态 MCP Server 策略位于 shared 边界；Python Runtime 镜像无需携带完整 `mcp_tool_runtime` 控制面模块。

### 2. 测试护栏与回归

- 变更前基线：117 passed。
- Principal、ONES MCP、Runtime HTTP、Python Runtime、File MCP、统一 MCP 审计、身份与沙盒聚焦回归：185 passed。
- File Service、File bridge、文件传输、工作区、统一 MCP 审计与沙盒专项回归：123 passed。
- 最终完整 backend：1124 passed、30 skipped、2 subtests passed。
- Ruff 全仓、`mypy backend/app`（377 source files）与 backend/services compileall：passed。

测试固定的第二业务 Server 为 `test-business-mcp`，只存在于测试 fixture，不进入生产 Manifest 或启动装配。测试覆盖：

- 同一 Job 分别签发两个 audience、scope 不混合且跨 audience 验证失败；
- Runtime 双业务 Header 严格匹配、只读映射、重复/额外/缺失/非法/超长/CR/LF 失败关闭；
- SDK 为两个业务 Server 构造独立 URL、alias 与 Authorization Header；
- 测试第二业务 Server 并发 fake-provider 调用只使用自身 token；
- token 不进入请求 JSON、digest、Runtime Grant、事件、响应、错误或 terminal ledger。

### 3. Compose 与镜像证据

- 主 Compose、Python Runtime acceptance overlay 与独立 ONES mock Compose 配置校验：passed。
- 重建 `api-server`、`agent-worker`、`python-agent-runtime`、`ones-mcp` 及关联目标：passed。
- local 运行状态：API、Python Runtime、ONES MCP、Tool MCP 健康；Agent Worker 进程运行。
- 实镜像检查：Agent Worker 不含 `claude_agent_sdk` 或 `app.python_runtime`；Python Runtime 含 shared MCP Server 策略且不含完整 `app.modules.mcp_tool_runtime`。

### 4. 独立测试数据验收

以下四个独立测试用例均通过：

- 双业务 Server Principal 的 audience/scope 隔离；
- ONES mock 查询及完整统一 MCP Operation Audit；
- Runtime HTTP 双业务 token 不落请求与账本；
- 测试第二业务 Server 的并发调用与 token 隔离。

结果：4 passed。

### 5. 明确未宣称的能力

- 未实现、注册或部署真实 `dingtalk-mcp` Server、Tool 或 Provider Credential。
- 未执行真实钉钉业务 E2E；`test-business-mcp` 证据只证明通用边界可隔离第二个代码固定业务 Server。
- 未改变 Runtime 协议版本、Runtime Grant、MCP Operation Audit 语义、身份/RBAC、File Principal 或沙盒策略。
