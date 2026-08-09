## Context

当前 Agent Worker 使用 Claude Agent SDK 创建进程内 SDK MCP Server，把内置工具和受治理 API Capability 包装后交给模型。ONES 查询经过 Capability、Handler、Connection、Mapping、Application Publication 等多层控制面；数据库、Redis 和 Loki 则经过 `internal-api-platform` 与同样复杂的资源组合。安全边界较完整，但实现与管理前端的体量已经超过当前只读项目管理和诊断场景。

现有实现中有五类事实值得保留：

1. `app_user` 是 Web 与渠道请求的统一内部权限主体，钉钉和 ONES 是独立外部身份；
2. ONES 本人验证采用短时 Challenge，密码不持久化，Token 加密保存，默认 Team 与外部主体在 Job 创建时冻结但运行时继续复核撤权；
3. 数据库、Redis、Loki Resource 使用 Draft、技术验证、不可变 Revision 和原子运行时 generation；
4. Secret 使用数据库密文、版本和仓库外 Master Key，模型和 API 响应不包含明文；
5. Job、Step、Tool Call、Ingress、Outbox 和 Delivery 提供了真实运行链审计。

提案日期的官方 MCP Python SDK 稳定版本为 `mcp==2.0.0`。Agent Worker 使用 2026-08-08 官方 PyPI 最新版 `claude-agent-sdk==0.2.134`；它仍保持 `mcp<2.0.0` 依赖边界，因此不能与 MCP v2 Server 合并为同一 Python 环境。MCP v2 Server 可以兼容旧协议客户端，适合通过独立容器解开依赖冲突。

本设计假设 ONES MCP 与 Data MCP 均由平台自托管、位于同一企业信任域；第一阶段以当前 Docker Compose 部署模型落地，Kubernetes 只作为后续部署形态。Vault、第三方托管 MCP、动态数据库账号和写操作不在本次范围。

## Goals / Non-Goals

**Goals:**

- 用少量领域 MCP Server 取代通用 API Capability Runtime 和 Internal API Platform 协议桥接。
- 使用官方 MCP v2 的 `MCPServer`、结构化 Schema、`Resolve` 隐藏依赖、Streamable HTTP 与内置可观测能力。
- 保持 Agent 只能看到有界业务参数，不能获得身份、Team、Resource、地址、用户名、密码、Token 或 Secret 引用。
- 保留统一身份、本人凭据、实时撤权、只读资源保护、不可变版本、Job 精确快照和安全审计。
- 用 `platformctl` 与声明式文件替代管理前端，保留登录、本人身份和历史调试前端。
- 在维护窗口直接删除旧平台代码和专属数据，并使用新 MCP 配置冷启动，不承担旧 Job 和历史兼容成本。

**Non-Goals:**

- 不实现 MCP Gateway 产品、动态 Server 注册市场或让模型发现平台内全部 MCP Server。
- 不提供任意 HTTP、任意 SQL、任意 LogQL、任意 Redis 命令、脚本、Shell、模板或通用代码执行。
- 不允许 Agent 配置、发布、取消发布 MCP Server、Resource 或 Secret。
- 不存储 ONES 登录密码，不使用共享 ONES 服务账号，不把个人 Token 发送给 Agent Worker。
- 不引入 Vault，不在线周期轮换 Master Key，不把 Master Key 写入数据库、仓库或普通环境变量。
- 不在本次增加 ONES 写操作、数据库写入、Redis 写入或 Loki 管理能力。
- 不重写 Job/Outbox/Delivery 基础设施，也不移除现有登录和 RBAC。

## Decisions

### 1. 使用两个独立领域 MCP Server，不先建设语义 Gateway

第一阶段部署：

```text
Agent Worker
  ├── Streamable HTTP ──> ones-mcp-server ──> ONES OpenAPI
  └── Streamable HTTP ──> data-mcp-server ──> DB / Redis / Loki
```

`ones-mcp-server` 与 `data-mcp-server` 分别拥有独立 `pyproject.toml`、锁文件、镜像和 `mcp==2.0.0` 精确依赖；Agent Worker 保持 Claude Agent SDK 支持的 MCP 1.x 依赖。v2 Server 同时服务旧协议客户端，避免为了“端到端全 v2”替换现有 Agent Loop。

Server 地址、TLS/服务鉴权和允许的 Server Code 由部署配置固定。反向代理只能承担 TLS、路由、请求大小、超时和速率限制，不保存业务身份映射、不改写 Tool Schema、不聚合全部 Tool，也不形成新的自研 Gateway 控制面。

替代方案是把 v2 SDK 升级到 Agent Worker 同一环境，或先自研 MCP Gateway；前者与 Claude Agent SDK 当前依赖冲突，后者会重建本次希望删除的控制面，因此拒绝。

### 2. Tool 由代码拥有并保持有界，不再使用通用 Handler

MCP Tool 名、描述、输入输出模型、只读语义、结果上限和授权 scope 由各 Server 代码拥有。初始 ONES 只按新契约重新实现已经验收的工作项查询语义，不导入旧 Capability 定义或运行数据；新增工作项详情、迭代或其他 ONES Tool 必须通过代码版本与契约测试发布，不能由 YAML 动态生成。

Data MCP 复用现有数据库方言驱动、Redis/Loki 客户端和范围校验，但只暴露代码定义的查询与诊断 Tool。Schema 搜索、表描述、预定义或受限诊断查询、Redis 前缀内读取、Loki 结构化过滤均必须由服务端注入资源范围与硬上限。第一阶段不暴露模型自由编写 SQL、LogQL 或 Redis 命令的入口。

Tool 输出统一包含有界业务数据和不可信数据标记；原始 Provider 响应仅存在于单次调用内存。模型描述与 Tool 参数不得包含连接信息或认证材料。

### 3. 平台短期 MCP Token 与下游凭据严格分层

Agent Run 开始时，Worker 为每个远程 MCP Server 签发一个仅覆盖本次执行窗口的访问令牌，并通过固定 HTTP Authorization Header 连接 Server。令牌至少包含：

```text
iss = enterprise-agent
aud = ones-mcp | data-mcp
sub = app_user.id
azp = agent-worker
job_id
application_publication_id
scopes = 精确 Tool scope
iat / exp / jti
```

有效期必须不超过 Job 最大执行时间加 60 秒，且上限为 15 分钟；令牌不得进入模型上下文、Tool 参数、日志或持久化请求体。Server 必须验证签名、issuer、audience、subject、authorized party、scope、expiry 和 Job 状态。

MCP Token 只认证平台调用者。ONES MCP 在服务端根据 `sub + job_id` 读取 Job 冻结的外部主体快照，复核当前 `app_user`、ONES Identity、默认 Team 和 Credential 状态，再解密个人 ONES Token 调用 ONES。禁止把 ONES Token 作为 MCP Bearer Token，禁止 Token passthrough。

MCP v2 `Resolve` 用于注入 `PrincipalContext`、`JobContext`、`OnesClient`、`ResourceContext` 和 Provider Client。这些依赖不进入 Tool Schema。HTTP Header 属于客户端输入，只有鉴权中间件验证后的 Principal 才能成为身份来源。

### 4. 保留统一主体，收缩外部身份与凭据模型

`app_user` 继续作为唯一授权主体。钉钉身份稳定键为企业与外部 subject，ONES 身份稳定键为 ONES 实例与验证返回的 user UUID；邮箱、手机号、昵称和用户名均不得用于自动合并。

第一阶段保持每个用户在每个钉钉企业最多一个当前钉钉身份、在每个 ONES 实例最多一个当前 ONES 身份。两个外部身份不直接互相引用，而是共同引用 `app_user`。

ONES 自助绑定保持两阶段：

1. 已登录用户通过 HTTPS 提交邮箱和密码；
2. 服务端登录受信 ONES 实例并严格校验 user UUID、Team 和 Token；
3. 密码在请求结束前丢弃，Token 加密写入短期 Challenge；
4. 用户选择候选集合内的默认 Team 后原子保存 ONES Identity、默认 Team 和个人 Credential；
5. 管理员只能查看状态、禁用或解绑，不能代用户输入密码或查看 Token。

现有 `external_api_credential` 与 API Connection Revision 耦合，因此纳入旧平台数据直接删除，不做凭据转换、导出或兼容读取。新系统从空表创建 provider-specific `provider_credential`，引用用户、外部身份、Provider 实例和加密 Token，不再引用 Capability/Connection Revision。保留下来的 ONES 稳定身份与默认 Team 在切换后处于 `REVERIFICATION_REQUIRED`，用户必须本人重新执行两阶段验证才能生成新凭据。新 Job 保留精确外部主体、默认 Team 和 binding revision；凭据值运行时实时解析，因此 Token 轮换可继续使用，主体或 Team 变化则 Job 失败关闭。

### 5. Resource 保留版本治理，但用 Deployment 指针替代复杂应用资源组合

Resource 继续分为稳定 Identity、可变 Draft、技术 Verification 和不可变 Revision。数据库、Redis、Loki 的非敏感连接配置与限制存入 Revision，密码或 Token 只保存 `secret://platform/<code>`。

新增轻量 `mcp_resource_deployment`，至少保存：

```text
server_code
resource_code
active_resource_revision_id
status
revision
updated_by / updated_at
```

每个 Server/Resource Code 在一个运行环境中只能有一个活动 Revision。MCP Tool 通过 Job 固定的 Deployment 与 Resource Revision 解析目标，禁止选择 `latest` 或数组首项。现有复杂的 Application Tool Resource Composition 及数据直接删除；新 Deployment 只能由声明式文件和 CLI 从空状态创建。

发布流程固定为 `plan -> apply Draft -> verify -> publish Revision -> activate Deployment`。`apply` 默认只更新 Draft，不能隐式发布。取消发布清除或禁用 Deployment，立即阻止新 Tool Call；已经发往上游的单次请求可以结束，但后续调用与重试必须失败关闭。回滚必须从历史 Revision 复制新 Draft、重新验证并发布新 Revision，不能把已禁用版本直接改回活动状态。

运行时以 generation digest 监听 Resource Revision、Deployment 和 Secret active version，完整构建成功后原子切换。构建失败时可以保留同一 Resource 的 Last Known Good，但不得让 Job 的精确 Revision 浮动到另一 Revision；没有精确 LKG 时阻断相关 Tool。

### 6. `platformctl` 是唯一资源与 Secret 写入口

移除管理页面后，管理员通过 `platformctl` 调用现有登录/Session/CSRF 与细粒度管理 API。CLI 保存的 Session 文件权限必须为 `0600`，不得记录密码、Session Token、CSRF Token 或 Secret 值。CI 服务账号认证延期，不为本次引入长期个人访问令牌。

声明式 YAML 可以进入私有运维仓库，但只包含非敏感配置与 Secret Ref。CLI 支持：

- `resource plan/apply/verify/publish/status/unpublish/draft-from-revision`；
- `secret create/rotate/disable/usages`，Secret 值只从 stdin 或受保护文件描述符读取；
- `mcp status/tools` 的只读健康与版本检查；
- `cutover check/clean/verify` 的受保护破坏性切换检查。

CLI 不直接写数据库，也不作为 MCP Tool 暴露。所有写操作继续使用 `app_user`、RBAC、expected revision、幂等键和审计。

### 7. 继续使用数据库加密 Secret，不引入 Vault

新 Secret 使用 AES-256-GCM-AAD、Secret ID/Version 绑定、版本状态和安全摘要。Master Key 通过 `APP_CONFIG_MASTER_KEY_FILE` 从仓库外只读挂载，并与数据库存储隔离。此次切换不备份旧 API/Internal Platform Secret 或凭据数据。Master Key 不挂载到前端、Agent Worker或反向代理，只授予实际需要解密的自托管 MCP/Runtime 服务。

ONES 密码不保存。系统登录密码只保存不可逆 Hash。Token/密码轮换更新 Secret 或 provider credential 的活动版本，不要求重新发布未变化的 Resource Revision；运行时审计记录安全的 Credential Revision、Secret Version 或 Key ID，不记录明文。

保留 Secret Provider Port 作为未来扩展缝，但 `vault:` 引用在本次继续失败关闭，Compose 不增加 Vault 服务和认证配置。

### 8. 前端改为用户门户，管理与发布功能全部退出导航

保留路由：登录/退出/修改密码/Session、自身身份、ONES Challenge 与默认 Team、会话历史、Job 详情、Step、Tool Call 和 Delivery 调试。管理员可以查看必要的安全治理摘要，但不能在 Web 中输入其他用户密码或编辑 MCP、Resource、Secret、Agent、Capability、Handler、Connection、业务应用或通用运行配置。

删除页面前必须先为仍需运维的新资源、Secret 和切换检查提供 CLI 等价路径，并验证普通用户与管理员导航都不存在悬空链接。历史 API 只返回脱敏 MCP provenance，不返回请求 Header、Secret Ref、连接地址或外部 Token。

### 9. 用 MCP provenance 替代 Capability provenance

每次 MCP Tool Call 持久化：

```text
mcp_server_code / server_version
tool_name / tool_schema_hash
job_id / app_user_id / application_publication_id
subject_snapshot_id
resource_deployment_id / resource_revision_id（如适用）
credential_revision（如适用）
request_summary / result_hash / result_size
status / duration / correlation_id
```

不再要求 Capability Release、Handler Revision、Connection Revision 或 HTTP Mapping Plan provenance。旧 Capability provenance、HTTP attempt 和依赖它们的历史 Job/Tool Call 数据在维护窗口直接删除；新 MCP 调用使用 Server 内部 attempt 审计或统一 Tool Call attempt，不把原始响应持久化。

### 10. Tasks 不替代现有 Job 生命周期

MCP Tasks 不用于普通 ONES 查询或数据诊断。平台已有 RabbitMQ Job、幂等、重试、超时、Tool Call 和 Delivery 生命周期，重复引入 MCP Tasks 会造成两个任务状态机。只有未来需要客户端跨连接恢复单个 MCP 长任务时再独立评估。

## Risks / Trade-offs

- [MCP v2 与 Claude Agent SDK 依赖不兼容] → MCP Server 使用独立环境；Agent Worker 固定兼容 MCP 1.x，并通过 v2 Server 的旧协议兼容能力接入。
- [去掉通用 Capability 后新增外部系统需要写代码] → 接受这一取舍；当前目标是少量稳定领域 Tool，不以动态通用性换取控制面复杂度。
- [MCP Server 直接读取平台身份、资源和密文扩大信任域] → Server 自托管、使用最小数据库权限和独立服务身份；Agent Worker、模型和外部 MCP 永不获得这些权限。
- [固定 HTTP Header 中的 MCP Token 可能在长 Job 中过期] → Token TTL 绑定本次 Agent 最大执行窗口；超过窗口必须结束当前 Run 并由 Worker 重新签发，禁止模型刷新。
- [取消发布不能撤回已经发出的上游请求] → 新调用和重试立即失败关闭；安全事件同时禁用 Credential/Secret 或上游账号。
- [Secret 数据库与 Master Key 同时泄露会暴露凭据] → Key 文件与数据库存储隔离、严格挂载范围、日志脱敏和凭据轮换；Vault 明确延期而非伪实现。
- [CLI 降低非技术管理员可用性] → 命令提供 plan、结构化 diff、安全错误和幂等操作；当前用户前端不承担平台运维，未来确有需求再针对高频动作增加窄页面。
- [硬切换会丢失旧 Capability/Internal Platform 历史] → 这是本变更明确接受的破坏性取舍；维护通知必须列出删除范围，删除后不提供恢复或历史查询。
- [没有旧数据迁移会延长首次恢复时间] → 在维护窗口前准备新的声明式 Resource 文件和验收用非敏感配置，删除后通过 CLI 重新创建并验证。
- [Data MCP 能力过窄影响分析] → 先按新契约重新实现已验收的只读诊断语义；任何自由 SQL/LogQL 需求必须作为独立高风险变更审查。

## Migration Plan

本变更不执行旧 API/Internal Platform 数据迁移，也不为这些数据创建备份或恢复路径；以下步骤是破坏性硬切换计划：

1. **准备新系统代码。** 在独立测试数据库和测试 Provider 上完成两个 MCP Server、统一身份解析、CLI、Resource Deployment、MCP provenance 和轻量前端验证，不读取生产旧数据做双读。
2. **准备冷启动配置。** 人工编写新的 DB、Redis、Loki 声明式 YAML 与所需 Secret 清单；不得从旧表自动导出或转换，不得把明文写入文件。
3. **进入维护窗口。** 停止入口、Worker、旧 Capability Runtime 和 Internal API Platform，拒绝创建新 Job，并确认相关进程全部退出。
4. **执行破坏性 schema 清理。** 直接删除 Capability、Handler、Connection、Mapping、Release、Application 复杂资源组合、Internal Platform Resource/Runtime Snapshot、旧专属 Job/Step/Tool Call/HTTP attempt/provenance、迁移账本和只服务旧模块的审计数据；删除前不创建备份。
5. **保留新系统基础。** 保留 `app_user`、密码 Hash、Session、钉钉/ONES 稳定外部身份、ONES 默认 Team 元数据、钉钉接入与 Ingress/Outbox/Delivery 基础表；直接删除旧 `external_api_credential` 和 Challenge，清理交叉外键，并将保留的 ONES 身份标记为需要本人重新验证。
6. **删除旧代码和部署。** 删除 API Capability/Internal API Platform 后端模块、管理 API、前端页面、测试、Compose 服务、环境变量和依赖包，确保仓库中没有可重新启用的旧执行入口。
7. **初始化 MCP 数据。** 执行新 schema，注册代码拥有的 MCP Server/Tool 元数据，通过 CLI 从空状态创建 Secret、Resource Draft、Verification、Revision 和 Deployment；新 Provider Credential 初始为空。
8. **启动并验收。** 启动 API、Worker、ONES MCP、Data MCP、钉钉 Runtime 和轻量前端；覆盖登录、身份绑定、ONES、DB、Redis、Loki、Job、取消发布、凭据轮换、服务重启、Outbox/Delivery 与敏感信息扫描。
9. **恢复入口。** 只有全部新链路验收通过后恢复 Web、钉钉和调试入口；旧历史为空属于预期结果。

由于用户明确不需要备份和迁移，步骤 4 执行后不提供数据级回滚。若新系统验收失败，只能继续修复新系统或重新初始化环境，不能恢复旧 API/Internal Platform 数据与历史。

## Open Questions

当前没有阻止进入实现的问题。第一阶段固定为自托管、同信任域、Docker Compose、两个 MCP Server、数据库加密 Secret、无 Vault、无通用 Gateway、无自由 SQL/LogQL/Redis 命令；任何改变这些边界的需求必须单独提出变更。
