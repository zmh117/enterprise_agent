## Why

当前标准 `tool-mcp` 虽已使用官方 MCP SDK，却仍只是旧 API Capability、Handler、Connection、Application Resource Mapping 与 Internal API Platform 的传输外壳，造成同一工具链同时维护 MCP、专用控制面和内部 HTTP 平台。现在需要一次性退役旧抽象，让 Python/TypeScript Runtime 只通过标准 MCP Tool Server 调用工具，同时保留必要的工具资源、凭据、业务权限和只读安全边界。

## What Changes

- **BREAKING**：永久删除 API Capability、Capability Handler、API Connection 的后端模块、管理 API、前端工作台、发布引用、运行时执行器、权限项和数据库表；这里的 Connection 不包含模型连接、钉钉 Connector 或交付 Connector。
- **BREAKING**：永久删除 Application Resource Mapping 及其草稿、发布、Job 快照、唯一解析矩阵和管理界面；Agent/Application 与 Job 只冻结精确 MCP Tool 集合及发布/授权摘要，不冻结用户消息中的 environment/base/workshop/placement。
- **BREAKING**：永久删除 `internal-api-platform`、`local-internal-api-platform`、`mock-internal-api-platform` 服务与模块、Internal API HTTP Client、服务 Token issuer/verifier、Compose secrets、`INTERNAL_API_*`、`FEATURE_REAL_INTERNAL_TOOLS` 和相关镜像/文档/测试。
- 保留单一私网 `tool-mcp`，直接使用官方 MCP SDK 注册代码拥有的只读工具；Python 与 TypeScript Runtime 继续共享该服务，不接受 Agent、Application、用户或模型提供的任意 MCP Server URL。
- 将数据库、Redis、Loki 的只读执行器、目标解析和安全策略收敛到 `tool-mcp` 进程内，不再经过内部 HTTP 平台。
- 保留工具资源、不可变资源发布版本、凭据中心、角色工具使用权限、应用访问权限和业务数据范围；Agent 按已发布 Skill 从当前消息与会话判断 Tool Call 目标，`tool-mcp` 对调用参数实时复核角色范围并从工具资源目录直接解析唯一资源。
- 保留统一身份体系中的 ONES 本人绑定、重新验证、默认 Team 选择、软解绑和管理员只读/停用/审计；管理员不得代绑、重验或解绑 ONES。邮箱与密码只用于单次身份验证，系统只持久化 ONES User ID、已验证 Team、默认 Team 和验证时间，不保存登录 Token，也不依赖 API Connection、Capability 或 MCP。
- 不增加 MCP Token、签名密钥、专用 RBAC、MCP 治理控制面或任意 URL/SQL/Shell/脚本执行器。
- 保留 Worker→Runtime 的 Runtime Grant 和模型探测 Token；它们不得传递给 MCP。
- 清理未完成 `migrate-claude-agent-sdk-to-typescript` 变更中已被双 Runtime 主规格取代的 `runtime-tool-mcp` 文档与任务，避免旧设计继续作为活动规格。
- 新增破坏性数据库迁移，在迁移前检查不存在引用旧 Capability/Mapping 的活动发布或在途 Job；迁移只删除旧平台数据，不删除工具资源、平台 Secret、模型连接、渠道连接或历史 Job 主记录。
- **BREAKING**：删除已不再参与现行授权的 `permission_policy`、`platform_access_grant` 与旧授权清理操作表/CLI，以及遗留的 Application Target、Job Execution Scope 表和 `agent_job` 目标冻结列；现行 `rbac_*`、用户、角色、成员关系、应用访问、MCP Tool grant、数据范围与 `agent_session.execution_scope_hash` 会话隔离事实继续保留。

## Capabilities

### New Capabilities

- `standard-mcp-tool-runtime`: 定义标准 MCP Tool Server 的直接工具注册、Job 上下文、资源解析、只读执行、安全失败、双 Runtime 共用和无专用认证边界。

### Modified Capabilities

- `agent-runtime-service-contract`: 明确 Runtime 只连接固定标准 MCP Tool Server，并使用 MCP Tool 发布快照而非旧 Capability/Resource Mapping。
- `claude-agent-runtime-integration`: 删除 `cap__*` Capability 运行时和 Internal API Platform 依赖，只保留标准 MCP 只读工具调用。
- `built-in-readonly-tool-governance`: 将代码 Handler Registry 收敛为代码拥有的 MCP Tool Manifest/实现，不再发布 Handler Release 控制面。
- `governed-tool-resource-management`: 保留工具资源与凭据生命周期，但取消 Application Resource Revision 绑定和 Internal API Platform 热加载。
- `application-tool-resource-composition`: 删除全部 Application Resource Mapping 要求，改为 Agent/Application/Job 精确 MCP Tool 子集与调用时目标解析。
- `business-application-publication`: 发布校验不再包含 Capability 或 Resource Mapping，改为校验 Agent MCP Tool Envelope、应用工具子集和业务范围。
- `role-authorization-model`: 保留角色应用访问、工具使用权限和数据范围，删除 API Capability 授权入口。
- `platform-config-api`: 删除旧拓扑/Internal API Platform 配置与资源映射 API，保留工具资源、凭据和必要运行配置。
- `platform-secret-management`: 删除 Internal API 服务 Token，保留工具资源、模型、渠道和平台凭据。
- `governed-api-capability-control-plane`: 永久移除整个能力控制面。
- `governed-api-capability-runtime`: 永久移除整个 Capability 运行时。
- `governed-capability-handler-runtime`: 永久移除整个 Handler 运行时。
- `api-capability-publication-composition`: 永久移除 Agent/Application Capability 发布组合。
- `external-api-connection-authentication`: 永久移除旧 API Connection 与认证配置。
- `external-api-credential-binding`: 移除仅服务于旧 API Connection/Capability 的个人 API 凭据，保留外部身份事实。
- `dingtalk-ones-identity-binding`: 明确 ONES 身份绑定独立于旧 API Platform 与 MCP，并由用户本人完成验证。
- `ones-identity-verification`: 将受信验证目标收敛为服务端固定 ONES 身份配置，验证挑战不保存登录 Token。
- `external-identity-presentation`: 删除个人业务调用凭据状态，保留 ONES 身份、Team、验证时间和治理投影。
- `internal-platform-topology`: 永久移除 Internal API Platform 专用拓扑模型。
- `internal-tool-platform-integration`: 永久移除 Internal API HTTP 集成和服务 Token。
- `local-internal-api-platform`: 永久移除本地 Internal API Platform。
- `local-internal-api-platform-structure`: 永久移除本地平台模块结构。
- `real-tools-runtime`: 将 real-tools 验收改为 Runtime→`tool-mcp`→真实工具资源链路。
- `oracle-instant-client-runtime`: Oracle 客户端如仍需要，由 `tool-mcp` 镜像直接承载，不再属于 Internal API Platform 镜像。

## Impact

- 后端：Bootstrap、API routes、Agent/Application/Job 快照、授权预览、外部凭据、平台配置、工具资源、MCP 服务和数据库迁移均受影响；旧模块和测试将物理删除或重写。
- 前端：删除 API Capability 页面及 Application Capability/Resource Mapping 配置；保留并简化内置工具、工具资源、凭据、角色授权、Agent/Application Tool 选择。
- 部署：删除三个 Internal API Platform 服务、镜像 target、内部 Token secrets 与环境变量；`tool-mcp` 增加所需数据库/Redis/Loki/Oracle 驱动并继续仅私网暴露。
- 数据：永久删除 Capability、Handler、API Connection、用于业务调用的个人 API Credential、Application Resource Mapping、遗留 Application Target/Job Execution Scope、旧 `permission_policy`/`platform_access_grant` 及相关发布表；保留平台资源、Secret、模型连接、渠道、现行 `rbac_*`、角色、用户、ONES 身份映射、会话隔离和历史 Job 主体。
- 规格：退役一组旧能力规格并新增标准 MCP 工具运行时事实源；归档前必须完成主规格语义同步和全量严格验证。
