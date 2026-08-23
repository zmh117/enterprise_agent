## Context

TypeScript Runtime 已退役，生产拓扑只保留 `agent-worker -> python-agent-runtime`。当前控制面仍通过 `routed_runtime_client.py` 中的 `RuntimeClientRegistry` 组装单个 Python client，`AgentExecutor` 的端口和成员仍名为 `claude_client`；这既保留了双 Runtime 时期的路由语义，也让应用层从 infrastructure 模块导入端口。

Python Runtime 已有 `service.py`、`job_sandbox.py`、`file_mcp_bridge.py`、`file_transfer.py`、`model_binding.py`、`invocations.py` 和 `grant.py` 等边界，但 `claude_agent_sdk_adapter.py` 仍约 1286 行，`sdk_executor.py` 约 1127 行。前者同时承担 SDK 装载、会话执行、消息/审计规范化、错误识别、脱敏和临时模型环境；后者同时承担一次 attempt 编排、固定 MCP 构造、工具策略、文件桥、模型调用和终态整理，并从前者导入 `_append_cli_stderr`、`_build_system_prompt` 等私有函数。

现有 canonical spec 已固定 Worker/Runtime 状态所有权、版本化协议、Runtime Grant、Principal JWT、固定 MCP、错误分类、审计和文件沙盒边界。本变更只调整内部结构，不能借重构修改这些事实。

## Goals / Non-Goals

**Goals:**

- 让控制面使用准确的 `runtime_client` 端口命名，并让端口由 application 层拥有、HTTP 实现位于 infrastructure 层。
- 删除映射式 Runtime Registry、`RoutedAgentRuntimeClient` 兼容别名和生产 `runtime_clients` 字典，改为单 delegate 的失败关闭守卫。
- 保留历史 TypeScript Job、未知 runtime kind、未支持协议和未配置 client 的现有稳定错误码与无模型调用语义。
- 以 characterization test 为先导，按单一职责逐步拆分两个大文件，形成静态、可追踪、无环的依赖方向。
- 每一步都保持现有协议 fixture、审计事件、MCP/File bridge、取消/恢复、错误分类和安全拒绝结果不变。

**Non-Goals:**

- 不改变数据库 schema、Runtime protocol、HTTP API、Compose 服务、队列拓扑、SDK/CLI 版本或前端。
- 不引入 Runtime/MCP/Provider 插件系统、动态包扫描、热安装、运行时 registry、任意 URL 或通用执行器。
- 不把 Claude Agent SDK/CLI、模型 Secret、MCP 调用或 Job Sandbox 合并到 `agent-worker`。
- 不删除历史 `typescript-v1` 枚举、Publication、终态 Job、协议事件或只读展示语义。
- 不以减少行数为目标机械拆文件；没有独立职责和测试边界的 helper 保持就地。

## Decisions

### 1. Application层拥有Runtime client端口

新增 application-owned `AgentRuntimeClient` Protocol，并把 `AgentExecutor` 构造参数、成员和调用点从 `claude_client` 统一为 `runtime_client`。基础设施的 `AgentRuntimeHttpClient` 和测试 stub 通过结构化类型实现该端口，application 层不再从 infrastructure 导入 Protocol。

选择 application-owned port 是为了让依赖方向保持 `application -> port <- infrastructure`。备选方案是只做文本重命名并继续从 `routed_runtime_client.py` 导入，改动更小但不能消除反向依赖。

### 2. 用单delegate守卫替代映射式Registry

删除 `RuntimeClientRegistry`、`RoutedAgentRuntimeClient` 和生产 `runtime_clients` 映射。使用只持有一个 `AgentRuntimeClient` delegate 的静态守卫，在委托前校验 Job 固定 runtime kind 与协议版本，并原样保留 `typescript_agent_runtime_retired`、`agent_runtime_kind_unsupported`、`agent_runtime_protocol_unsupported`、`agent_runtime_unconfigured` 和取消能力错误。

生产 bootstrap 只构造一个 Python HTTP client；测试显式注入一个 stub client。守卫不接受 URL、名称到 client 的映射或动态注册。备选方案是直接把所有校验移入 HTTP client，但这样测试 stub 和未来非 HTTP transport 可能绕过控制面完整性门禁。

### 3. 拆分以依赖方向而不是文件大小为准

目标依赖图为：

```text
service -> executor
executor -> model_binding / mcp_config / tool_policy / claude_client
executor -> file_mcp_bridge / file_transfer / job_sandbox / invocations
claude_client -> sdk_event_normalizer / error_mapper
```

任何低层模块不得反向导入 `service` 或 `executor`，模块之间不得导入以下划线开头的私有符号。已有文件边界保持不变，只有 `claude_agent_sdk_adapter.py` 与 `sdk_executor.py` 中可独立测试的职责被提取。

### 4. 按风险从纯函数到编排逐步提取

拆分顺序固定为：

1. 提取纯事件/计量规范化与错误映射，保持 payload、脱敏、错误码和重试分类逐字段等价；
2. 提取固定 MCP 配置与 Tool Policy，保持 Server code、Tool identifier/schema/scope、禁止字段、调用次数和文件工具路由不变；
3. 提取 `ClaudeSdkClient`，只拥有 SDK 装载、Options/session 调用和 SDK message stream，不读取数据库、RabbitMQ 或业务状态；
4. 把剩余 attempt 生命周期收敛为 `PythonRuntimeExecutor`，负责模型绑定、沙盒/MCP 生命周期、调用 client、产生唯一终态和 finally 清理；
5. 删除被替代的旧类、私有跨模块导入和兼容入口，不并行保留新旧实现。

每一项先补齐或锁定 characterization test，再移动实现并运行 focused regression。不得一次性重写两个大文件。

### 5. 行为等价由合同与安全事实共同定义

“行为不变”不仅是最终文本相同，还包括 request digest、invocation、sequence、唯一终态、取消/恢复、稳定错误码、retryable 分类、SDK/CLI 版本投影、事件字段/有界脱敏、MCP 审计关联、Principal JWT、Runtime Grant、文件版本/哈希和沙盒清理等事实相同。

单元测试使用 fake/stub 与合成本地服务；默认测试和 readiness 不调用外部模型。最终 Compose 验收复用 Python 单 Runtime 合成入口，不使用真实业务消息或 Secret。

## Risks / Trade-offs

- [大范围重命名导致测试替身遗漏] → 先用全仓搜索建立 `claude_client`/Registry 引用清单，集中完成第一阶段并运行完整 backend。
- [移动错误逻辑改变 retry 或错误码] → 对现有异常类、`error_code`、safe message、tool events 和 diagnostics 建 characterization table，逐类对账。
- [事件规范化拆分导致审计字段漂移] → 复用 golden fixture 与 MCP meta fidelity 测试，逐字段比较 sequence、计量和有界 payload。
- [MCP/Tool Policy 拆分放宽安全边界] → 固定 Server/Tool/schema/scope 和禁止字段测试必须先失败后通过；不得引入通用 URL 或插件 registry。
- [文件生命周期在编排拆分中泄漏] → 保留 sandbox/file bridge 的现有 finally、取消、超时和恢复测试，并运行合成文件闭环。
- [模块数量增加但职责仍交叉] → 每个新模块必须有单一 owner、公开最小 API 和禁止反向依赖测试；无法形成独立边界的 helper 不提取。

## Migration Plan

1. 记录当前全量测试、模块依赖和两个大文件职责基线。
2. 完成 `runtime_client` 命名、application-owned port、单 delegate 守卫和 bootstrap/test 注入迁移；运行完整 backend 与静态检查。
3. 依次完成事件/错误、MCP/工具策略、Claude SDK client、attempt executor 提取；每一步独立运行 focused regression 和 diff/residual scan。
4. 运行 Runtime 合同、模型绑定、MCP、审计、取消/恢复、文件工作区、安全拒绝、完整 backend、静态检查与 Python 单 Runtime Compose 合成闭环。
5. 观察现有 local Python Runtime readiness 和新鲜合成 Job；确认没有协议、审计或错误事实漂移后再归档。

任一步失败时回退该步的模块移动和装配，不修改数据库或持久化事实。由于没有外部合同与数据迁移，回滚不需要兼容双实现。

## Open Questions

无。模块命名可在实现中按现有项目约定微调，但职责、依赖方向和行为不变门禁已经固定。
