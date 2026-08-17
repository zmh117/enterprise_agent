## Why

TypeScript Runtime 退役后，生产执行已经收敛为独立 Python Runtime，但控制面仍使用 `claude_client`、`RuntimeClientRegistry` 等双实现时期命名，Python Runtime 的 `claude_agent_sdk_adapter.py` 与 `sdk_executor.py` 也合计超过 2400 行并存在跨文件私有函数依赖。继续在这两个聚合文件中叠加模型、MCP、工具策略、事件和错误处理，会重新积累难以验证的耦合。

## What Changes

- 第一阶段只整理命名与依赖方向：把控制面端口统一命名为 `runtime_client`，移除双 Runtime 路由/Registry 语义和过渡别名，让生产装配直接依赖单一 `AgentRuntimeClient`，同时保留对历史 TypeScript Job、未知 Runtime 和不受支持协议的稳定失败关闭。
- 第二阶段在现有合同、focused regression 和 Compose 合成证据保护下，逐步从 `claude_agent_sdk_adapter.py` 与 `sdk_executor.py` 提取单一职责模块：执行编排、Claude SDK 调用、SDK 事件规范化、固定 MCP 会话构造、工具策略和错误映射。
- 每次提取先建立或复用 characterization test，再移动代码并删除旧入口；不并行保留两套实现，不增加动态插件扫描、运行时注册或任意 Runtime/MCP URL。
- 保持 `python-agent-runtime` 独立服务以及 Worker/Runtime 业务状态边界；不把 Claude Agent SDK 或 CLI 合并回 `agent-worker`。
- 不改变 Runtime 协议、request digest、invocation/terminal 恢复、事件 schema、审计格式、错误码、MCP Tool identifier/schema/scope、Principal JWT、Runtime Grant、模型凭据解析、文件桥或 Job Sandbox 行为。
- 不升级 Claude Agent SDK/CLI，不修改数据库结构、Compose 拓扑、公开 API 或前端行为。

## Capabilities

### New Capabilities

无。本变更不引入新的平台能力。

### Modified Capabilities

- `execution-delivery`：补充 Python Runtime 内部职责必须静态组装、依赖方向明确且重构前后行为等价的要求；不改变现有执行、协议或安全语义。

## Impact

- 控制面：`AgentExecutor`、bootstrap 装配、Runtime client 端口/守卫及相关测试替身。
- Python Runtime：`backend/app/python_runtime/claude_agent_sdk_adapter.py`、`sdk_executor.py` 及从中提取的新模块。
- 验证：Runtime 协议/恢复、模型绑定、MCP、工具策略、事件审计、取消、错误分类、文件工作区和 Compose Python 单 Runtime 闭环。
- 不涉及数据库 migration、前端、外部 MCP/Provider 接口或部署拓扑变化。
