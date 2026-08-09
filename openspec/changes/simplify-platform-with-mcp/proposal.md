## Why

当前平台为少量 ONES 查询和内部诊断能力构建了通用 API Capability、Handler、Connection、Publication、Internal API Platform 与大面积管理前端，控制面层级、自研代码和运维路径明显超过现阶段业务需要。现在应以官方 MCP SDK 和自托管的领域 MCP Server 取代通用执行平台，同时保留统一身份、个人凭据、只读资源边界、Job 审计和安全撤权这些真正必要的企业能力。

## What Changes

- 新增独立部署的 `ones-mcp-server` 与 `data-mcp-server`，使用最新稳定版官方 MCP Python SDK；MCP Server 通过有界业务 Tool 提供 ONES、数据库、Redis 和 Loki 能力，不提供任意 HTTP、SQL、LogQL、Redis 命令、脚本或 Shell 执行器。
- Agent Worker 通过显式服务器与 Tool allowlist 调用远程 MCP Server；MCP 身份使用平台签发、受 audience 和 scope 约束的短期访问令牌，禁止把 ONES Token 当作 MCP Bearer Token，也禁止信任模型参数或客户端 Header 作为业务身份。
- 以 `app_user` 作为唯一内部权限主体，将系统账号、钉钉身份和 ONES 身份关联到同一主体；ONES 仍采用本人邮箱密码两阶段验证，密码只存在于单次请求内，验证得到的 Token 加密持久化并由 ONES MCP 在运行时按当前主体解析。
- 为数据库、Redis 和 Loki 提供声明式 YAML 与 `platformctl` 管理入口，保留 Resource Identity、Draft、技术验证、不可变 Revision、发布部署、取消发布、审计和运行时原子热加载；不再要求管理前端配置资源。
- 继续使用数据库加密 Secret 与仓库外 Master Key 文件管理数据库密码、Redis 密码、Loki Token、钉钉 AppSecret 和 ONES Token；Secret 只以 `secret://platform/<code>` 引用进入配置。**本次不引入 Vault。**
- 前端收缩为登录与会话安全、本人钉钉/ONES 身份绑定、ONES 默认 Team、会话与 Job 历史、Tool Call 与投递调试；移除 API Capability、Handler、Connection、内置工具治理、资源/Secret、业务应用工作台和通用运行配置编辑页面。
- **BREAKING** 停止创建和发布新的通用 API Capability/Handler/Connection，并以 ONES MCP 取代 ONES Capability Runtime；在破坏性切换检查通过后删除旧 Capability 执行路径及其前端入口。
- **BREAKING** 以 `data-mcp-server` 取代 `internal-api-platform` 对数据库、Redis 和 Loki 的协议桥接；可复用已验证的只读驱动与安全约束代码，但不读取、导出或转换旧资源记录和运行快照。
- **BREAKING** 在维护窗口执行硬切换：停止旧 Runtime 与 Worker 后直接删除 API Capability、Handler、Connection、Internal API Platform、复杂资源组合及其专属运行数据，不做备份、双读、影子对账、历史迁移或旧 Job 兼容；数据库、Redis 和 Loki 由新 CLI 重新配置。

## Capabilities

### New Capabilities

- `mcp-server-runtime`: 自托管 MCP Server 的 SDK、传输、鉴权、Tool 暴露、隐藏依赖、版本兼容、健康与可观测性契约。
- `mcp-subject-credential-resolution`: 统一内部主体、钉钉/ONES 身份、个人 ONES Token、Job 主体快照和 MCP 请求级凭据解析契约。
- `declarative-resource-operations`: 数据库、Redis、Loki 的 YAML/CLI 配置、验证、发布、取消发布、Secret 引用和原子运行时生效契约。
- `lightweight-user-portal`: 收缩后的登录、本人身份管理、历史查询和调试前端边界。
- `legacy-platform-retirement`: API Capability 与 Internal API Platform 的维护窗口停机、专属数据清理、代码删除和新系统冷启动契约。

### Modified Capabilities

- `claude-agent-runtime-integration`: 将“只使用进程内 SDK MCP Server”改为连接显式允许的远程领域 MCP Server，并保留 Job 级隔离、精确 Tool allowlist 和写工具禁用。
- `external-api-credential-binding`: 保留 ONES 两阶段本人验证协议，但删除依赖旧 Connection Revision 的凭据数据；用户切换后重新验证，Token 写入新的 Provider Credential 并只由 ONES MCP 解析。
- `governed-tool-resource-management`: 保留资源版本、验证和热加载边界，改用 CLI/声明式配置与精确 MCP Resource Deployment，不再要求资源管理页面或 Application Tool Resource Composition。
- `platform-secret-management`: 从 Web 凭据中心改为受认证 CLI/管理 API；继续使用数据库密文、版本和仓库外 Master Key，明确不实现 Vault。
- `governed-api-capability-control-plane`: 彻底移除 Capability/Handler/Connection 配置、发布、历史读取及其专属持久化数据。
- `governed-api-capability-runtime`: 彻底移除旧 Capability Runtime、HTTP attempt 与 Capability provenance；ONES 由 ONES MCP 重新提供。
- `local-internal-api-platform`: 彻底移除旧服务、协议端点和专属配置/快照数据；数据库、Redis 和 Loki 由 `data-mcp-server` 重新配置。
- `web-admin-console`: 管理控制台收缩为登录、本人身份与历史调试入口，不再承载 Agent、Capability、资源和 Secret 编辑。
- `business-application-admin-workbench`: 移除业务应用 Web 工作台；仅保留 Agent/渠道运行仍需要的后端发布事实和受控运维接口，不继续扩张通用前端控制面。

## Impact

- 新增独立 MCP Server 包、容器、健康检查、服务鉴权配置和 `platformctl`；MCP Server 使用与 Agent Worker 分离的依赖环境，避免官方 MCP SDK 主版本与 Claude Agent SDK 的依赖约束冲突。
- 调整 Agent Runtime、Job 上下文、Tool allowlist、Tool Call 审计、外部身份/凭据解析、资源运行时快照和 Compose 部署。
- 删除 `backend/app/modules/api_capability`、`backend/app/modules/internal_api_platform`、相关管理 API、Compose 服务，以及前端 Capability、平台治理、业务应用工作台和通用配置页面。
- 保留 `app_user`、系统登录、钉钉/ONES 稳定外部身份、ONES 默认 Team 元数据和 Ingress/Outbox/Delivery 基础设施；删除旧 `external_api_credential` Token 数据，用户必须在切换后本人重新验证并创建新的 Provider Credential。允许删除只服务旧 API/Internal Platform 的 Application/Capability/Handler/Connection、Resource 组合、运行快照、Job/Step/Tool Call/HTTP attempt 与审计历史。
- 数据库变更直接删除旧专属表、列、外键和数据并新增 MCP Server/Deployment/Provenance 事实；不提供旧数据备份、转换、物化、隔离报告或历史兼容查询。
- `.env`/Compose 仅保留平台数据库、RabbitMQ、Master Key 文件、服务鉴权、模型连接和必要网络引导；业务数据库、Redis、Loki Secret 由 CLI 从空状态创建，个人 ONES Token 由用户重新验证后写入新的加密凭据。
