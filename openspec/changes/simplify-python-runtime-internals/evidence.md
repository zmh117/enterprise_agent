## Implementation evidence

本文件仅记录 `simplify-python-runtime-internals` 的重构核对事实和验证结果，不是 canonical requirement。

### 1. 重构前基线

#### 控制面依赖与错误守卫

| 事实 | 重构前位置 | 必须保持的结果 |
| --- | --- | --- |
| Runtime 调用端口 | infrastructure `routed_runtime_client.py` | 迁至 application-owned port，方法仍为 `run`/`cancel` |
| Executor 成员 | `AgentExecutor.claude_client` | 只改名为 `runtime_client` |
| 生产装配 | `bootstrap.py` 构造 `runtime_clients` mapping 后传给 Registry | 收敛为一个静态 Python client delegate |
| TypeScript 历史 Job | Registry 前置校验 | `typescript_agent_runtime_retired`，且不调用模型 |
| 未知 Runtime kind | Registry 前置校验 | `agent_runtime_kind_unsupported` |
| 不支持协议 | Registry 前置校验 | `agent_runtime_protocol_unsupported` |
| 未配置 Python client | Registry 前置校验 | `agent_runtime_unconfigured` |
| delegate 无取消能力 | Registry 前置校验 | `agent_runtime_cancel_unavailable` |

#### 两个聚合文件的责任表

| 原文件 | 重构前责任 | 目标 owner |
| --- | --- | --- |
| `claude_agent_sdk_adapter.py` | SDK 装载、Options/session、SDK stream | `claude_client.py` |
| `claude_agent_sdk_adapter.py` | SDK 审计事件、计量和 tool event 投影 | `sdk_event_normalizer.py` |
| `claude_agent_sdk_adapter.py` | SDK/Provider 错误识别、脱敏和 diagnostics | `error_mapper.py` |
| `sdk_executor.py` | 固定 Tool/ONES/File MCP 构造 | `mcp_config.py` |
| `sdk_executor.py` | Tool allow/deny、禁止字段、调用限额 | `tool_policy.py` |
| `sdk_executor.py` | attempt、模型绑定、文件桥、终态和清理编排 | `executor.py` |
| `sdk_executor.py` -> adapter | `_append_cli_stderr`、`_build_system_prompt` 私有导入 | 公开的单向依赖 API |

#### 行为等价检查表

| 领域 | 等价事实 |
| --- | --- |
| Runtime contract | protocol version、request digest、request/response schema 不变 |
| Invocation | invocation id、恢复判定、事件 sequence、唯一 terminal 不变 |
| Failure | error code、retryable、safe message、有界脱敏 diagnostics 不变 |
| Audit | event type、字段、计量、tool call 关联和 provenance 不变 |
| MCP | 固定 Server code、Tool identifier/schema/scope、禁止字段和调用次数不变 |
| Identity | Principal JWT、Runtime Grant、模型凭据解析/隔离不变 |
| Files | 精确版本/哈希、流式传输、路径/符号链接/容量守卫不变 |
| Sandbox | 成功、失败、取消、超时和恢复后的 finally 清理不变 |

#### 命令基线（2026-08-17）

- Runtime focused pytest：53 passed。
- 相关 Runtime 文件 Ruff：passed。
- 相关 Runtime 文件 Mypy strict：passed。
- `docker compose config --quiet`：passed。
- 主 Compose 与 `docker-compose.python-runtime-acceptance.yml` overlay 组合校验：passed。

### 2. 命名与依赖方向

- 新增 application-owned `AgentRuntimeClient` port 和只持有单个 delegate 的 `GuardedAgentRuntimeClient`。
- `AgentExecutor`、bootstrap、测试替身和调用点统一使用 `runtime_client`。
- 生产 bootstrap 只静态构造一个 Python Runtime HTTP client；测试显式注入单个 client。
- 删除 `routed_runtime_client.py`、mapping Registry、过渡别名和所有 Python 源码残留引用。
- 守卫测试逐项固定退役 Runtime、未知 kind、不支持协议、未配置 delegate 和取消能力错误码。

验证结果：

- 第一阶段 focused pytest：41 passed。
- 完整 backend pytest：1070 passed、30 skipped、2 subtests passed。
- 相关 Ruff、Mypy strict、残留扫描和 `git diff --check`：passed。

### 3. SDK 事件与错误映射

- 提取 `sdk_event_normalizer.py`：SDK message/event 投影、计量、tool event 和有界 payload。
- 提取 `error_mapper.py`：错误识别、retry 分类所需判定、safe message、stderr 边界和脱敏 diagnostics。
- 原 adapter 不再定义上述逻辑，也不再跨模块导入下划线私有符号。
- 复用现有 success、API retry、accounting、tool meta、Provider reject/timeout、恢复和取消 fixture 做等价验证。

验证结果：

- 事件/错误 focused pytest：37 passed。
- 四个受影响模块 Mypy strict、Ruff、compileall 和 AST 私有导入检查：passed。
- `claude_agent_sdk_adapter.py`：1286 行降为 817 行。

### 4. 固定 MCP 与 Tool Policy

- 提取 `mcp_config.py`：固定 Tool/ONES/File MCP server、Principal header、File bridge、manifest 校验和 SDK MCP options。
- 提取 `tool_policy.py`：禁止输入字段、精确 Tool allow/deny、SDK Tool origin 与 Runtime tool event 规范化。
- executor 只通过公开 API 构造固定 MCP client 和规范化 tool events；旧类、私有 helper 和重复常量均已删除。
- 静态扫描确认新模块不存在插件扫描、entry point、动态 import 或 client/Server registry。

验证结果：

- MCP/身份/审计/文件工具 focused pytest：60 passed。
- 三个受影响模块 Mypy strict、Ruff、compileall 和残留扫描：passed。
- `sdk_executor.py`：1127 行降为 618 行。

### 5. Claude Agent SDK client

- 将剩余 SDK 装载、Options/session、stream、临时模型环境和 prompt 构造移动到唯一 `claude_client.py`。
- SDK client 公开类统一为 `ClaudeSdkClient`；streaming prompt 也改为公开 API，测试不再跨模块导入私有符号。
- 删除旧 `claude_agent_sdk_adapter.py` 路径、`RealClaudeCodeAgentClient` 类名和所有转发/兼容入口。
- SDK client 不持有 Repository、Database、RabbitMQ、Job、retry、Outbox 或 Delivery 状态；`assert_external_io_allowed` 仅保留原事务外部 I/O 安全断言。

验证结果：

- SDK/model/MCP meta focused pytest：51 passed、2 skipped（显式 real integration 条件跳过）。
- `claude_client.py` 与 `mcp_config.py` Mypy strict、Ruff、compileall 和旧入口残留扫描：passed。

### 6. Python Runtime executor

- 将剩余 attempt 编排移动到 `executor.py`，公开类统一为 `PythonRuntimeExecutor`。
- `service.py` 只通过 executor 入口执行/探测，不直接构造 Claude SDK、MCP server、Tool Policy 或 File bridge。
- executor 显式依赖 model binding、固定 MCP、Tool Policy、Job Sandbox 和现有 invocation/文件边界。
- 删除旧 `sdk_executor.py`、`PythonRuntimeSdkExecutor` 及所有旧 import/monkeypatch 路径；没有兼容别名。

验证结果：

- 执行/恢复/取消/文件/Sandbox focused pytest：44 passed。
- executor/service/invocations Mypy strict、Ruff、AST 私有导入和旧入口残留扫描：passed。

### 7. 架构守卫与文档

- 新增 `test_python_runtime_internal_architecture.py`，固定 application-owned port、单 delegate、无环依赖、无跨模块私有导入、无动态 registry/plugin 和 SDK client 业务状态边界。
- 复用 `test_agent_runtime_compose_security.py` 固定 Worker 镜像不含 Claude SDK/CLI 且只有 Python Runtime 镜像包含运行依赖。
- 新增 `backend/app/python_runtime/README.md`，记录静态依赖图、模块 owner 和禁止项。
- execution-delivery delta 补充现有 canonical requirement 的内部类名与依赖方向更新；不直接修改 canonical，不改变协议或行为。
- 生产与测试调用路径无旧 Registry、路由、adapter/executor 文件和旧类名；旧词只保留在 change 的变更前事实、已完成任务及负向架构断言中。

验证结果：

- 架构/Compose/guard pytest：15 passed。
- Runtime 全模块 Mypy strict、Ruff、循环依赖、私有导入、动态扩展和残留扫描：passed。
- change strict validation 和 `git diff --check`：passed。

### 8. 完整验证与 local 合成证据

- 最终 focused regression：80 passed，覆盖 Runtime client、HTTP 协议、执行、恢复/取消、模型绑定、MCP、事件审计、文件桥和 Sandbox。
- 最终完整 backend：1074 passed、30 skipped、2 subtests passed。
- 全仓 Ruff、376 个 app source 的 Mypy strict、backend compileall、主/acceptance Compose config：passed。
- local 重建 `python-agent-runtime` 与 `agent-worker`；Runtime 健康、Worker 已运行，未删除 volume 或业务数据。
- 实镜像检查：Worker 不含 `claude_agent_sdk` 或 `app.python_runtime`；Python Runtime 含 SDK 和 `app.python_runtime.executor`，且不含 `app.bootstrap`。
- 独立 Compose project `enterprise-agent-python-runtime-acceptance` 使用独立 PostgreSQL/RabbitMQ/MinIO volume 运行 6 个新 Job，结果：
  - success：`job_ea0aa880366e45cdbf6a22beda4fb0ad`，SUCCEEDED，retry 0；
  - retry：`job_4ac1d1892acb419999cd582a335a0408`，SUCCEEDED，retry 1；
  - dead：`job_9c5d6ec20b4f4d3bb9f2de1c6e90144b`，FAILED，retry 0；
  - Tool MCP：`job_d991c0ba089b4e9796cce8ad63ea437b`，SUCCEEDED，1 个 MCP Tool Call；
  - ONES MCP：`job_db183fcb232c44fc9071e2d2f18d3800`，SUCCEEDED，2 个 MCP Tool Call；
  - File Service：`job_b711e1364dca4602b6ec3a928d7297d1`，SUCCEEDED，protocol 1.3 工作区和 1 个 File MCP Tool Call。
- acceptance runner 对每个 Job 核对 dispatch、Worker claim、精确 Runtime invocation/terminal、MCP audit、Job 和 Delivery 终态；取消/恢复由 fresh test Job recovery regression 覆盖。
- 最终 `openspec validate simplify-python-runtime-internals --strict`：passed。
- 最终 `openspec validate --all --strict`：18 passed、0 failed。
- Markdown link check、`git diff --check`、local Runtime/Worker 状态复核：passed。
