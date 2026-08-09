## Why

当前真实 Agent 执行仍由 Python Worker 直接加载 Claude Agent SDK，并在同一进程承担 Job 编排、模型凭据解析、MCP 会话、权限钩子和结果归一化，既保留了 Python/Node 双运行时镜像，也把 SDK 升级风险扩散到核心后端。MCP 基线又暴露出 Agent/Application Publication 缺少正式治理入口，因此应在当前 MCP 架构上建立独立 TypeScript Agent Runtime，并恢复围绕不可变 Publication 的受控管理界面。

## What Changes

- 新增独立部署的 `agent-runtime` TypeScript 服务，使用官方 `@anthropic-ai/claude-agent-sdk` 最新稳定版并精确锁定依赖；该服务只负责一次 Agent 执行、MCP 连接、权限钩子、SDK 事件归一化和安全诊断。
- 保留 Python API、Job/RabbitMQ 编排、授权、Publication 解析、状态机、结果持久化和 Delivery；Python `agent-worker` 通过版本化内部执行协议调用 TypeScript Runtime，不把 Job 数据模型或平台数据库仓储重写到 Node.js。
- 建立一次性、受 audience/Job/Publication/expiry 约束的 Runtime 执行授权。模型 API Key、MCP Token 和其他认证材料不得进入 RabbitMQ、Job 快照、模型上下文、日志或响应；Runtime 只能按精确不可变绑定执行。
- 将现有 Python Claude SDK 适配器迁移为契约测试基准，完成等价性、失败分类、超时、取消、MCP 1.x 客户端到 MCP v2 Server 兼容和真实 smoke 验证后删除 Python SDK、全局 Claude CLI 及相关镜像层。
- 恢复 Agent Publication 管理前端及后端管理路由，支持多 Agent 列表、草稿、校验、发布、历史版本和受控回退；不得提供自由 Tool 名、任意 Prompt 注入安全层或未注册模型配置。
- 恢复 Business Application 管理前端，以 Agent Publication、Channel/Trigger/Delivery、精确 MCP Tool Publication 和 Resource Deployment 组成应用草稿，支持校验、发布、测试/生产环境激活与停用。
- 补齐 `mcp_tool_publication` 的受治理创建、更新、停用和审计入口，使 Application Publication 能冻结精确 Server、Tool、Schema Hash、Resource Deployment 与授权 scope；禁止模型自动发现平台全部 MCP Tool。
- **BREAKING** 删除 Python `claude-agent-sdk` 与 Python 进程内真实模型执行路径；切换完成后生产 Job 不再回退到 Python Runtime。
- **BREAKING** 替换已退役的 `/applications` 占位页并重新开放 Agent/Application 管理导航；页面只恢复本变更定义的 Publication 控制面，不恢复 API Capability、Internal API Platform、任意资源编辑器或通用执行平台。

## Capabilities

### New Capabilities

- `typescript-agent-runtime-service`: 独立 TypeScript Agent Runtime 的内部执行协议、授权、SDK/MCP 执行、事件归一化、健康检查、部署与迁移门禁。
- `mcp-tool-publication-management`: MCP Tool Publication 的生命周期、精确绑定、管理 API/UI、撤权、审计及 Application Publication 集成。

### Modified Capabilities

- `claude-agent-runtime-integration`: 将 Python 进程内 Claude Agent SDK 执行改为独立 TypeScript Runtime，同时保持精确 MCP allowlist、只读权限、失败分类和安全 provenance。
- `multi-agent-configuration`: 恢复多 Agent 草稿、校验、不可变 Publication、回退和 Job 固定版本的正式管理入口。
- `agent-profile-model-connection-management`: 使模型连接测试与真实运行由 TypeScript Runtime 执行，并保持加密 Secret、SSRF 防护、版本固定和脱敏审计。
- `business-application-control-plane`: 应用草稿改为装配精确 MCP Tool Publication 与 Resource Deployment，不再引用已删除的 API Capability。
- `business-application-publication`: 应用发布和激活必须冻结并校验 Agent、MCP Tool、Resource、Channel 与 Delivery 的精确版本交集。
- `business-application-admin-workbench`: 恢复真实 Application 列表、详情、编辑、校验、发布、激活和停用前端，但不恢复通用 API/资源管理页面。
- `web-admin-console`: 在认证控制台中恢复 Agent Publication 与 Application 管理导航，并继续隐藏 Secret、连接信息和已退役平台入口。

## Impact

- 新增 TypeScript workspace、锁文件、Docker 镜像、内部 Runtime API/客户端、服务身份、健康检查、指标和 Compose 服务；Node.js 运行时采用当前受支持的 LTS 版本并以非 root 用户运行。
- 调整 Python `agent-worker`、Claude SDK 适配器、Model Connection tester、Job 取消/超时、MCP Token 签发、Tool event/provenance 和运行时 readiness；保留 RabbitMQ、PostgreSQL Job 状态机与 Delivery Worker。
- 新增 MCP Tool Publication 管理服务、数据库约束、RBAC/CSRF API 和前端页面；恢复 Agent/Application 前端上下文，但不恢复已删除的 Capability、Handler、Connection 或 Internal API Platform 代码与数据。
- 本变更以当前 `mcp_dev` 和 `simplify-platform-with-mcp` 的实现为基线，不能从 `master` 的旧平台代码直接恢复。实施前应先提交当前 MCP 基线；OpenSpec 归档顺序必须先完成 `simplify-platform-with-mcp`，再归档本变更。
