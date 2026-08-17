## 1. 固化现状与行为基线

- [x] 1.1 盘点控制面 `claude_client`、`RuntimeClientRegistry`、`RoutedRuntimeClient`、bootstrap 装配及测试替身的全部引用，记录当前依赖方向和退役/未知 Runtime 的稳定错误码。
- [x] 1.2 盘点 `claude_agent_sdk_adapter.py` 与 `sdk_executor.py` 的职责、公开入口、私有跨文件导入和调用关系，形成仅用于重构核对的模块责任表。
- [x] 1.3 为协议版本、request digest、invocation/terminal、事件 sequence、取消/恢复、错误分类、审计、MCP、Principal/Grant、文件桥和 Job Sandbox 建立重构前后的行为等价检查表。
- [x] 1.4 运行并记录现有 Runtime focused tests、相关静态检查和 Python 单 Runtime Compose 验证基线；任何既有失败必须先分类，不得借重构改变预期行为。

## 2. 第一小步：统一命名与依赖方向

- [x] 2.1 将 Runtime 调用端口明确归属 application 层并统一命名为 `AgentRuntimeClient`；端口不得引用 Claude SDK、HTTP 实现或平台装配细节。
- [x] 2.2 将 `AgentExecutor` 的构造参数、属性、调用点和测试替身从 `claude_client` 统一重命名为 `runtime_client`，不改变请求、响应、错误或审计语义。
- [x] 2.3 用静态装配的单一 Python Runtime delegate guard 替换基于 mapping 的 `RuntimeClientRegistry`/`RoutedRuntimeClient`，保持 `typescript_agent_runtime_retired`、`agent_runtime_kind_unsupported`、`agent_runtime_protocol_unsupported`、`agent_runtime_unconfigured` 及取消能力错误不变。
- [x] 2.4 更新生产 bootstrap 与测试 bootstrap，使其只装配一个 Python HTTP client 或显式测试 stub；删除过渡别名、动态注册入口、client mapping 和残留双 Runtime 路由语义。
- [x] 2.5 删除已无引用的 `routed_runtime_client.py` 或将仍需的稳定守卫迁入职责明确的模块；禁止保留兼容层和新旧两套实现。
- [x] 2.6 运行命名/装配 focused tests、完整后端回归和静态依赖检查；仅在第一小步全部通过后进入文件拆分阶段。

## 3. 提取纯事件规范化与错误映射

- [x] 3.1 基于现有 fixture 补齐 characterization tests，覆盖成功、tool event、API retry、最大轮次、超时、Provider 错误、矛盾终态、计量和有界脱敏 diagnostics。
- [x] 3.2 从两个大文件提取纯 `sdk_event_normalizer` 职责，保持事件类型、sequence、计量、tool event、terminal 和审计字段逐项等价。
- [x] 3.3 提取纯 `error_mapper` 职责，保持稳定错误码、retryable 分类、safe message 和 diagnostics 脱敏规则不变。
- [x] 3.4 消除 `_append_cli_stderr`、`_build_system_prompt` 等跨模块私有导入；共享能力必须通过命名明确的公开函数或值对象单向依赖。
- [x] 3.5 运行事件、计量、错误、审计与取消/恢复 focused tests，确认无 fixture 或预期结果被为适应重构而放宽。

## 4. 提取固定 MCP 配置与 Tool Policy

- [x] 4.1 基于现有测试补齐 Tool MCP、ONES MCP、File MCP、Principal 绑定、Runtime Grant、禁止字段、调用次数和文件路由的 characterization coverage。
- [x] 4.2 提取静态 `mcp_config` 构造职责，保持 Server code、Tool identifier/schema/scope、模型可见配置和 fail-closed 校验不变。
- [x] 4.3 提取 `tool_policy` 职责，保持允许/拒绝判定、危险工具限制、越界参数处理、调用次数与审计关联不变。
- [x] 4.4 验证新模块没有动态 Server registry、插件发现、任意 MCP URL、通用 HTTP/MCP 执行入口或凭据持久化。
- [x] 4.5 运行 MCP、身份、授权、审计和文件工具 focused tests，通过后再继续拆分 SDK client。

## 5. 提取 Claude Agent SDK Client

- [x] 5.1 基于现有测试固定 SDK options、system prompt、session/message stream、临时环境、模型绑定、凭据解析和 CLI stderr 行为。
- [x] 5.2 将 Claude Agent SDK 调用提取到单一 `claude_client` 模块，公开边界只接收已经解析的调用配置并产出规范化输入所需的 SDK 结果。
- [x] 5.3 确认 Claude SDK client 不拥有数据库、RabbitMQ、Job、retry、Outbox、Delivery、Runtime invocation 或 terminal 业务状态。
- [x] 5.4 删除旧 SDK client 实现和过渡转发入口，更新调用点与测试；不得并存两套 SDK 调用链。
- [x] 5.5 运行模型绑定、SDK stream、错误映射、事件规范化和凭据隔离 focused tests。

## 6. 收敛 Python Runtime 执行编排

- [x] 6.1 基于现有测试固定 attempt 编排、invocation 恢复、唯一终态、取消、retry handoff、文件物化/提交和 finally 清理行为。
- [x] 6.2 将单次 attempt 编排收敛到职责明确的 `executor` 模块；它仅依赖模型绑定、MCP 配置、Tool Policy、Claude SDK client、事件/错误模块及既有文件/沙盒端口。
- [x] 6.3 使 Python Runtime service 只依赖新的 executor 公开入口，不直接拼装 SDK、MCP、Tool Policy 或文件桥内部细节。
- [x] 6.4 删除已被完全替代的 `claude_agent_sdk_adapter.py`、`sdk_executor.py` 内容或文件，并清理旧类名、旧工厂、私有跨文件导入和循环依赖。
- [x] 6.5 运行执行、恢复、取消、文件工作区、Sandbox 和 Runtime service focused tests，确认所有失败路径仍执行相同清理和终态写入。

## 7. 架构守卫与残留清理

- [x] 7.1 增加或更新静态架构测试，禁止 application 端口反向依赖 infrastructure、Python Runtime 业务层依赖 service/bootstrap、模块循环依赖及跨模块私有符号导入。
- [x] 7.2 增加或更新安全架构测试，禁止动态 client/Server registry、插件扫描、任意 Runtime/MCP URL、通用执行器和 Worker 进程内 Claude SDK。
- [x] 7.3 扫描并清理 `claude_client` 控制面旧命名、`RuntimeClientRegistry`、`RoutedRuntimeClient`、TypeScript 路由分支、旧 SDK/executor 类名及兼容转发入口；历史只读/审计语义除外。
- [x] 7.4 更新必要的模块说明和测试命名，使文档描述与最终依赖图一致；不得把内部模块重构表述为新增平台能力。

## 8. 完整验证与交付证据

- [x] 8.1 运行 Python Runtime、AgentExecutor、Runtime client、恢复/取消、模型绑定、MCP、Tool Policy、事件审计、文件桥和 Job Sandbox 的 focused regression。
- [x] 8.2 运行完整后端测试、lint、类型检查、编译检查和依赖图/架构测试，修复所有由本变更引入的失败。
- [x] 8.3 运行 Compose 配置与镜像安全检查，并在 local 环境重建受影响服务，证明 Worker 不含 Claude SDK/CLI 且只有 Python Runtime 执行模型调用。
- [x] 8.4 用新 Job 逐项验证成功、可重试/失败、取消或恢复、MCP Tool Call、File MCP/Workspace 和 Delivery 闭环；记录协议、错误码、审计字段和沙盒清理的等价证据。
- [x] 8.5 运行 `openspec validate simplify-python-runtime-internals --strict`、相关 canonical validation 和 `git diff --check`，确认任务证据齐全后再进入 sync/archive。
