## Context

当前链路为：`Runtime -> tool-mcp -> Job Tool Registry / GovernedApiRuntimeExecutor -> InternalApiClient -> internal-api-platform -> DB/Redis/Loki`。`tool-mcp` 已使用官方 MCP SDK 且旧 `runtime-tool-mcp`/HS256 链已经删除，但工具目录、发布组合、资源映射、目标解析和实际执行仍由三套旧抽象共同承担。

本次变更是破坏性收敛：保留标准 MCP 传输、工具资源、平台 Secret、应用/角色/数据范围和安全执行器；删除 API Capability/Handler/API Connection/Application Resource Mapping/Internal API Platform。现有 `environment=test` 等工具资源必须在迁移后继续可由同一 Job 权限边界访问。

## Goals / Non-Goals

**Goals:**

- 形成唯一工具调用链：`Runtime -> tool-mcp -> direct resource resolver -> readonly executor`。
- 让 Python/TypeScript Runtime 使用相同 MCP Tool schema、执行语义和错误分类。
- 永久删除旧 Capability/Handler/API Connection/Resource Mapping/Internal API Platform 的代码、表、UI、配置、密钥和规格。
- 永久删除已被统一 RBAC 取代的旧 `permission_policy`、`platform_access_grant`、清理 CLI/操作表与测试兼容读取层，不保留双授权事实源。
- 保留工具资源、凭据、应用访问、角色工具权限、业务数据范围、Job/Tool Call 审计和只读安全限制。
- 保留独立于工具调用的 ONES 身份验证与映射，只持久化 User ID、Team、默认 Team 和验证时间。
- 对活动发布、在途 Job 和资源歧义失败关闭，避免破坏性迁移产生越权或静默漂移。

**Non-Goals:**

- 不允许管理员、Agent、Application、用户或模型提交任意 MCP Server URL。
- 不创建 MCP Server 注册中心、MCP Token、签名密钥、专用 RBAC 或新的 Resource Mapping。
- 不删除模型连接、钉钉 Connector、交付 Connector、外部身份事实、Runtime Grant 或 Model Probe Token。
- 不删除 ONES 本人绑定、重新验证、默认 Team、软解绑或管理员只读/停用/审计；管理员不得代用户提交 ONES 邮箱密码，也不得代用户解绑 ONES。
- 不把 SQL、Shell、脚本、HTTP URL 或模板变成可在 Web 中定义的通用执行器。
- 不承诺兼容旧 API Capability/Resource Mapping API；迁移完成后旧端点直接不存在。

## Decisions

### 1. `tool-mcp` 是唯一标准 MCP Tool Server

保留当前 `tool-mcp` 服务名、固定私网地址和官方 MCP SDK Streamable HTTP 实现。两个 Runtime 只接收协议中冻结的 `server_code=tool-mcp` 与精确 Tool 名，不自动发现其他 Server，也不从业务 payload 接收 URL。

选择保留单一服务而不是引入可配置 MCP Server 注册中心，是因为当前需求只要求替换旧平台且明确不新增复杂治理。未来若接入外部 MCP Server，必须另建规格定义网络、凭据和工具可信边界。

### 2. MCP Tool Manifest 取代 Handler/Capability 控制面

代码中的每个只读工具以稳定 identifier、描述、输入 Schema、资源类型、只读标记和实现函数注册到 MCP Tool Manifest。删除 Capability Release、Handler Revision、API Connection、Mapping Plan、`cap__*` 发布组合和 `GovernedApiRuntimeExecutor`。

Manifest 是代码事实，不在 Web 中编辑实现。Agent Publication 冻结精确 Tool identifier/schema hash，Application Publication 只能选择其显式子集；角色继续按稳定 Tool identifier 授权。

### 3. 工具资源保留，但 Application Resource Mapping 全部删除

保留 `platform_resource` 的 Draft/Verification/Revision、Secret Ref 和资源生命周期。删除 `business_application_*_resource*`、`*_builtin_tool_resource*`、资源槽、有限目标矩阵和 Job 映射快照。

Job 创建时只冻结应用/Agent Tool 交集、发送人有效工具权限摘要和发布完整性事实，不从 DingTalk Routing Context 或用户消息冻结 `environment`、`base`、`workshop`、`placement`。Agent 按当前消息、会话和已发布 Skill 为每次 Tool Call 选择目标参数；用户输入可能变化或不准确，因此 Skill 必须在不确定时澄清，不能猜测或跨环境探测。`tool-mcp` 在每次调用时先用当前角色数据范围复核 Agent 给出的目标，再按 Tool 所需资源类型从已发布且启用的工具资源中解析唯一匹配：

1. `environment` 必须精确相等；
2. `base`/`workshop` 只在资源声明了对应层级时匹配；
3. 当前角色数据范围必须覆盖调用目标；
4. 若 Tool 参数包含 `placement`，必须精确匹配；若候选 placement 不唯一则调用失败；
5. 匹配为零或大于一均失败，不使用排序、默认值或最近版本猜测。

这保留 `environment=test` 的动态资源能力，同时移除应用逐工具映射。

### 4. Internal API Platform 的实现能力内聚到 `tool-mcp`

从 `internal_api_platform` 中保留并迁移必要的纯领域/基础设施能力：只读 SQL 分析与方言限制、表白名单/前缀隔离、Redis Key 前缀与 scan 上限、Loki selector/time/line 限制、数据库驱动、Oracle client 初始化和安全结果裁剪。这些代码改归 MCP 工具运行时所有，不再保留 HTTP route、service-token middleware、平台 app、InternalApiClient 或独立服务镜像。

`tool-mcp` 直接只读访问平台数据库以解析 Job/Resource/Secret，并直接连接目标资源。它挂载 `APP_CONFIG_MASTER_KEY_FILE`，但不挂载 Internal API Token 或 Runtime Grant。

### 5. 权限仍在 Job 与工具实现处失败关闭

MCP transport 不承担认证和 RBAC。私网请求只携带非敏感 `X-Job-Id` 与 correlation id；`tool-mcp` 重新读取 Job，要求 Job 为 RUNNING、Runtime/protocol 合法，并验证 Tool 在 Job 冻结集合中。业务应用访问、角色 Tool grant 和数据范围在 Job 创建时求交，并在调用时对可撤权事实再次校验。

这不是新增 MCP 治理，而是保留已有业务安全事实。任何缺失、撤权、schema drift、资源歧义、Secret 不可用或只读策略失败均拒绝调用。

### 6. 破坏性迁移采用先切流后删表

新增单向迁移：先新增直接 MCP 所需的 Job Tool 快照字段或表并回填可确定历史；部署新代码并确认没有旧执行引用；最后删除 Capability、API Connection、用于业务调用的外部 API Credential、Application Resource Mapping、Internal API runtime generation/activation、遗留 Application Target/Job Execution Scope，以及已被统一 RBAC 取代的 `permission_policy`、`platform_access_grant`、旧清理操作表和 `agent_job` 目标冻结列。`user_external_identity` 及 ONES 身份元数据继续保留；身份验证使用独立的短时挑战，挑战只保存已验证主体与 Team 候选，不保存邮箱、密码或登录 Token。现行 `rbac_*`、应用访问、MCP Tool grant、数据范围和 `agent_session.execution_scope_hash` 会话隔离事实不得删除。

迁移器在删除前检查：不存在 RUNNING/QUEUED/RETRYING 且引用旧 Capability/Mapping 的 Job；不存在活动 Application Deployment 引用无法转换的旧发布。检查失败则迁移整体失败，不局部删表。

已完成历史 Job 主记录、Tool Call 摘要和 Delivery 历史保留；旧 Capability/Resource Mapping 的管理快照不承诺保留。执行前要求数据库逻辑备份。

### 7. 前端删除旧入口并简化配置

删除 API Capability 页面和路由；Application 组成配置删除 Capability Allowlist、资源槽、业务叶子矩阵与 Resource Mapping，只保留 Agent Publication、MCP Tool 子集、会话策略、触发器和投递。Agent 配置使用 MCP Tool Envelope。角色页面继续显示应用、MCP Tool 使用权限和数据范围。工具资源与凭据中心保留。“我的外部身份”继续提供 ONES 本人验证、重新验证、默认 Team 选择和解绑；人员管理对 ONES 只提供身份元数据查看、停用与审计，不显示或接收邮箱密码，也不提供管理员解绑。

### 8. 密钥和配置边界

删除 `INTERNAL_API_BASE_URL`、`INTERNAL_API_AUTH_TOKEN_FILE`、`INTERNAL_API_SERVER_AUTH_TOKENS_FILE`、`INTERNAL_API_CLIENT_AUTH_TOKEN_FILE`、`FEATURE_REAL_INTERNAL_TOOLS`、对应 Compose secrets 和数据库运行配置项。

持续通过扫描门禁禁止 `runtime-tool-mcp`、`RUNTIME_TOOL_MCP_*`、旧 HS256 issuer/verifier/signing key 回归。保留 `RUNTIME_GRANT_*`、`MODEL_PROBE_AUTH_TOKEN_FILE`、`APP_CONFIG_MASTER_KEY_FILE`。

### 9. 活动 TypeScript 迁移规格收敛

`migrate-claude-agent-sdk-to-typescript` 的实现已被已归档双 Runtime 变更和主规格部分取代。此次删除其中对 `runtime-tool-mcp`、旧 Capability 运行时和未实施工具迁移的活动要求；可复用的 Runtime 协议事实保留在主规格，避免并存两个事实源。

## Risks / Trade-offs

- [Risk] 删除 Resource Mapping 后同一逻辑目标存在多个资源候选。→ 解析必须要求唯一结果；有 cloud/edge 时要求 Tool 参数显式 placement，歧义绝不回退。
- [Risk] 把驱动放入 `tool-mcp` 增大镜像。→ 使用专用 Docker target，只在该镜像安装 DB/Redis/Loki/Oracle 依赖，Worker/API/Runtime 不安装。
- [Risk] 破坏性迁移删除治理历史。→ 执行前备份，保留 Job/Tool Call/Delivery 业务历史；迁移检查活动引用并原子失败。
- [Risk] 移除 API Capability 后 ONES 外部业务工具不可用，但身份绑定仍需存在。→ 身份验证与业务调用凭据彻底分离；本变更保留身份映射，不提供 ONES 业务工具。未来 ONES MCP 的调用凭据必须另建规格，不能复用或污染身份模型。
- [Risk] 私网无 MCP Token 依赖网络隔离。→ `tool-mcp` 不映射宿主端口，仅连接 `agent-runtime-control` 与必要 provider/target 网络，拒绝 Authorization header 和任意 Host/Origin。
- [Risk] 旧规格和测试数量很大，残留会形成误导。→ 把源码、迁移、Compose、env、前端路由、主规格与全文扫描列为独立完成门禁。

## Migration Plan

1. 创建数据库备份并记录当前活动 Application/Agent Publication、在途 Job、工具资源和 Secret 数量。
2. 引入直接 MCP Tool Manifest、唯一资源解析器和内聚执行器，新增/调整 Job Tool 快照；保持旧表只读用于一次性回填。
3. 切换 Agent/Application/Role API 与前端到 MCP Tool 模型，停止创建 Capability/Resource Mapping 数据；同时确认 ONES 身份绑定仅使用固定身份验证配置和无 Token 挑战。
4. 切换 `tool-mcp` 直接执行，完成 Python 与 TypeScript Runtime 的 DB/Redis/Loki 回归及 DingTalk 链路验收。
5. 执行破坏性迁移，删除旧表、字段、权限、路由、模块和 UI；删除旧授权清理 CLI/测试兼容层，保留 `user_external_identity`、统一 RBAC 与会话隔离事实，并为已经执行旧迁移的数据库向前恢复 ONES 身份专用挑战结构。
6. 删除 Internal API Platform Compose 服务、Docker target、Token secrets、环境变量、文档和测试；验证 Compose 配置与镜像。
7. 严格验证 OpenSpec、后端、前端、运行时合约、数据库迁移和残留扫描后再归档。

回滚只允许在破坏性迁移执行前回滚应用镜像；删表后必须通过执行前数据库备份恢复，不提供旧新双写或长期兼容模式。

## Open Questions

无。用户已确认保留工具资源和凭据中心，并采用上述直接 MCP 解析边界。
