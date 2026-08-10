## Context

`simplify-platform-with-mcp` 已将运行链路收敛为 Agent/Application Publication 驱动的 TypeScript Agent Runtime、受信 MCP Server、Tool Publication、受治理 Resource Deployment 与短期运行令牌。该切换正确退役了旧 API/Internal Platform，但也删除了人员、角色、身份、凭据、资源、渠道、调试和总览等日常治理入口。结果是运行边界比旧平台简单，但维护工作被迫回到数据库、环境变量或零散命令行。

本变更恢复 Web 治理能力，而不是恢复旧平台领域模型。`bak/frontend` 只作为页面结构、表格/表单交互和中文文案的参考；当前数据库模型、授权服务、MCP 发布模型和运行时契约仍是唯一事实源。

约束如下：

- 必须支持多个 Agent 和多个 Application；Draft、校验、Publication、历史、回退、激活和停用继续以当前实现为准。
- MCP Server 由代码或 Compose 固定注册，控制台不能创建任意远程 MCP 连接。
- API Capability、Handler、Connection、Application Resource Mapping 和旧 Internal Platform 数据保持退役，不备份、不迁移、不恢复。
- Resource Web 交互必须简单，但运行时仍须 fail-closed，并保留不可变 Revision、Deployment、Generation 和 Last Known Good。
- 凭据先使用现有加密数据库 Provider，不引入 Vault；明文不得进入 API 响应、日志、审计、事件或 Agent 上下文。
- OpenTelemetry 仅预留兼容边界，本次不安装 Collector、不增加遥测依赖，也不改变当前验收范围。

## Goals / Non-Goals

**Goals:**

- 恢复一个认证、权限感知、真实 API 驱动的治理控制台，覆盖总览、Agent、Application、渠道、调试与历史、人员、角色、身份、MCP Server、Tool Publication、Resource 和凭据。
- 让管理人员可以在 Web 中完成高频维护，不再通过直接改数据库或修改容器环境变量完成资源、凭据、人员和角色治理。
- 对 MCP 配置保持窄边界：浏览器只能管理服务端已知对象和允许的安全字段。
- 复用当前统一用户、RBAC、身份、Publication、Resource、Secret、Job 和审计事实，避免建立平行模型。
- 对控制面写操作统一使用 Session、CSRF、权限校验、乐观并发、幂等和审计。

**Non-Goals:**

- 不恢复 API Capability、Handler Registry、Connection、Resource Mapping、通用 HTTP/SQL/MCP/Shell 执行器或动态 Tool Schema 编辑器。
- 不允许通过页面录入任意 MCP Server URL、Transport、Header、认证参数或任意 Tool。
- 不把 Resource 的内部发布状态机压缩为两态；两态仅是 Web 主视图的投影。
- 不迁移 `bak` 数据、旧平台数据或被删除的表，也不恢复兼容路由。
- 不在本次接入 OpenTelemetry Collector、链路后端或正文级遥测。

## Decisions

### 1. 当前领域服务是事实源，备份前端只是交互参考

恢复页面时逐页重建 API 适配层和 TypeScript 类型，组件可以参考 `bak/frontend`，但不得复制旧 API Client、fixture、旧路由守卫或旧 Capability/Mapping 类型。每个页面先读取当前服务返回的安全 DTO，再根据 DTO 暴露操作。

这样可以复用用户熟悉的操作方式，同时防止已经退役的领域概念借由前端代码重新进入系统。直接整体回搬备份前端被拒绝，因为它会重新引入静态数据、失效接口和旧权限语义。

### 2. 使用一个权限感知的管理 Shell

登录后由同一个管理 Shell 提供以下导航域：

1. 总览；
2. Agent；
3. Application；
4. 渠道与触发器；
5. 调试与运行历史；
6. 人员与账号；
7. 角色与授权；
8. 身份治理；
9. MCP 配置（Server、Tool Publication、Resource、Credential）。

导航和路由都按服务端返回的代码拥有管理权限过滤。隐藏菜单不是授权措施；每个读写 API 必须再次校验权限和对象范围。未登录用户只能进入登录流程，不提供匿名治理或匿名历史查看。

代码拥有的权限目录按页面责任拆分，例如 `dashboard.read`、`users.read/manage`、`roles.read/manage/assign`、`identities.read/manage`、`channels.read/manage`、`jobs.read/debug`、`mcp.servers.read`、`mcp.tools.read/manage`、`mcp.resources.read/manage` 和 `credentials.read/manage`。权限代码由服务端发布，页面不得创建任意权限字符串。

### 3. MCP Server 使用只读受信注册表

MCP Server 来自服务端代码、部署清单或 Compose 配置形成的固定注册表。控制台可展示标识、显示名、来源、Transport 摘要、健康状态、最近检查时间和脱敏错误；只能执行服务端定义的安全检查或刷新动作，不能创建、编辑或删除 Server，也不能看到认证 Header/Token。

Tool 目录来自这些受信 Server 的发现快照。Tool Publication 的写操作只允许在当前 Application/Agent 发布流程允许的 Tool 集合中启用、停用或绑定精确 Resource Deployment。客户端提交 `tool_id`、目标对象、`expected_revision` 和幂等键；服务端根据注册表重新解析 Tool，拒绝客户端提交的 Tool 名、Schema、Server URL 或认证配置。

### 4. 不恢复 Resource Mapping，只保留精确运行依赖

Data MCP Tool Publication 可以引用零个或一个精确的 Resource Deployment。该引用表示“这个已发布 Tool 在运行时解析这一项受治理资源”，不是可编辑的字段映射或规则。绑定创建时服务端验证：

- Tool 类型允许使用该 Resource kind；
- Resource Deployment 已启用且验证通过；
- Application、Publication、Resource 和操作者范围一致；
- Secret 可解析但不返回给调用方；
- `expected_revision` 与当前事实一致。

运行时从冻结 Publication/Deployment/Generation 快照解析依赖；若引用已停用、Generation 不可用或 Secret 无法解析，则新 Job fail-closed。历史 Job 继续引用其冻结快照，不被控制面当前状态改写。

### 5. Resource 页面采用两态投影，后端保留安全状态机

列表主状态只有“启用”和“停用”，主操作只有新建、编辑、启用、停用。页面可以显示只读的验证结果、当前有效版本、最近错误和受影响对象，但不要求操作者理解 Draft/Revision/Deployment/Generation。

操作的服务端语义为：

- **新建**：创建资源身份与 Draft，校验字段及 Credential 引用；未验证成功前保持停用。
- **编辑**：以当前配置生成新 Draft/Revision，不原地修改已发布版本；若资源当前启用，验证成功后原子切换到新 Deployment/Generation，失败则保留 Last Known Good。
- **启用**：验证候选 Revision 和 Secret，成功后创建/激活 Deployment 与 Generation；失败不改变当前有效版本。
- **停用**：阻止新 Job 解析该资源并撤销新的绑定资格；不删除历史 Revision、Job 或审计事实。

支持的种类为当前受信的 Database、Redis 和 Loki。字段 Schema 由服务端按 kind 返回或由前端代码固定，浏览器不能定义任意连接器类型、任意驱动参数或通用查询模板。

### 6. Credential Center 使用加密数据库 Provider

本次不引入 Vault。凭据中心继续使用仓库外 Master Key 与 AES-256-GCM-AAD 保存加密负载，数据库只持久化密文、nonce、认证标签、版本、状态、用途和审计元数据。Master Key 仅由后端进程读取，不进入数据库和前端构建产物。

页面提供创建、轮换、停用和用途查看：

- 创建/轮换请求通过 TLS 与 CSRF 防护提交，明文只在请求处理内存中短暂存在；
- 成功响应只返回稳定凭据标识、显示名、kind、版本、状态和用途计数；
- 列表、详情、审计和错误均不得返回明文、密文、nonce、认证标签、Master Key 或可复制的内部 Secret Ref；
- Resource 表单按安全凭据标识选择，后端再解析内部引用；
- 被启用 Resource 或活动 Publication 使用的凭据不能直接停用，除非先解除依赖；
- 轮换创建新版本并使新 Job 使用新版本，历史 Job 仍保留其冻结引用，不回写历史。

### 7. 统一身份和 RBAC，不建立第二套人员模型

`app_user` 是系统主体。钉钉用户和 ONES 用户通过受信 External Identity 绑定到同一个 `app_user`：

- 钉钉候选只能来自已验证 Channel Ingress/目录同步事实，操作者不能手工输入任意 `senderStaffId` 作为新身份事实；
- ONES 邮箱与密码只用于后端向 ONES 获取/刷新 Token，并作为 Credential 保存，External Identity 只保存非敏感外部主体标识和绑定状态；
- Runtime 使用当前 `app_user`、Application Publication、角色/数据范围和绑定的 ONES Credential 签发短期内部调用上下文；Agent 和 MCP Server 永远看不到 ONES 密码；
- 一个外部主体在同一 Provider/租户内只能绑定一个 `app_user`，冲突与解绑均需审计和乐观并发保护。

角色由成员、代码拥有的管理权限、Application 使用权限和业务数据范围组成。角色不选择 API Capability，也不编辑 MCP Tool；实际可调用集合是角色/Application 访问上限与当前 Application Publication 中 MCP Tool/Resource 安全边界的交集。平台管理员仍通过代码拥有的系统角色获得治理权限，不能通过页面改写其内建权限定义。

### 8. 调试和历史复用真实 Job 链路

“发起调试”创建真实 Job，但客户端只提交允许的 Application/Agent 入口、用户输入和可选会话上下文，不得覆盖主体、Publication Revision、Resource Generation、Credential、MCP Server、Tool allowlist 或授权快照。服务端从当前登录用户和已激活 Publication 重新解析这些事实。

历史列表和详情按当前用户权限、Application 可见范围与对象归属过滤，并采用不可枚举标识。响应默认脱敏；Prompt、回复正文、Tool 参数/结果和敏感错误只在现有权限与保留策略允许时返回。页面可显示状态、阶段、耗时、调用摘要、投递状态、关联 Publication/Generation 标识和审计时间线，不暴露令牌或 Secret。

### 9. 总览只读取服务端安全聚合

总览通过专用聚合 API 展示当前用户可见范围内的 Agent/Application/Publication、渠道、Job、MCP Server、Tool、Resource 和 Credential 健康摘要。聚合 API 不接受任意查询表达式，不直接透传底层数据库行，也不因用户无权查看的对象泄露总数、名称或错误详情。

### 10. OpenTelemetry 只保留未来兼容点

本次在设计与接口中保留 W3C `traceparent`/`tracestate` 的透传位置：Python Worker → TypeScript Runtime → MCP Gateway/Server。未来接入 OTLP 时仅默认采集服务名、操作名、状态码、耗时、重试次数和不可逆散列后的关联标识；Prompt、回复正文、Tool 参数/结果、数据库语句、Token 和 Credential 一律默认排除。当前实现任务不包含 SDK、Collector、存储或 Dashboard。

## Architecture

```text
Authenticated Web Console
        |
        | Session + CSRF + expected_revision + idempotency_key
        v
Management APIs / Safe DTOs
        |
        +-- User / RBAC / External Identity / Channel services
        +-- Agent / Application / Publication services
        +-- Job / Session / Audit query services
        +-- Trusted MCP Registry / Tool Publication services
        +-- Resource lifecycle / Secret provider services
        |
        v
PostgreSQL governance facts + encrypted credential payloads

Runtime path (unchanged)
DingTalk or Debug -> Worker -> TypeScript Agent Runtime
                              -> short-lived MCP token
                              -> trusted MCP Server
                              -> frozen Resource Generation
                              -> Secret resolution -> DB / Redis / Loki / ONES
```

## API Projection

恢复页面优先消费面向 UI 的安全投影，而不是直接暴露内部实体：

| UI 区域 | 读取投影 | 允许写操作 |
| --- | --- | --- |
| 总览 | 范围过滤后的聚合计数与健康摘要 | 刷新 |
| MCP Server | 固定注册表与脱敏健康状态 | 受控健康检查 |
| Tool Publication | Tool 快照、Application/Agent 归属、精确 Resource 绑定 | 启用、停用、绑定/解绑精确 Deployment |
| Resource | 两态主状态、安全字段、版本/健康摘要、Credential 选择项 | 新建、编辑、启用、停用 |
| Credential | 元数据、版本、状态、用途 | 创建、轮换、停用 |
| 用户/角色/身份 | 统一主体和有效授权摘要 | 受权限约束的 CRUD/绑定/解绑 |
| 渠道 | 受信类型、脱敏配置和运行状态 | 新建、编辑、启用、停用、测试 |
| 调试/历史 | 范围过滤后的 Job/Session/Delivery 摘要 | 发起受限调试、取消允许取消的 Job |

所有列表使用分页和确定性排序；所有详情用不可枚举 ID；所有 mutation 返回新的 revision/version 与审计关联标识。

## Failure Handling

- 后端未知的 MCP Server、Tool、Resource kind、Connector kind 或权限代码一律拒绝，而不是由前端兜底。
- 健康检查失败只能更新健康事实，不得自动停用、删除或替换有效 Deployment。
- Resource 编辑/启用失败保留 Last Known Good，并返回可脱敏展示的错误码与建议动作。
- Credential 解析失败不回退到环境变量、请求参数或旧 Secret 表；新运行 fail-closed。
- 外部身份冲突、角色 revision 冲突和发布冲突返回稳定冲突码，页面要求刷新后重试。
- 页面/API 不可用不影响已经发布的运行链路；控制台是治理入口，不是运行时反向依赖。

## Migration Plan

1. 盘点 `bak/frontend` 页面与当前后端事实，建立“复用组件/重写数据层/永久排除”清单；首先加入禁止旧路由和旧类型回归的静态检查。
2. 扩展代码拥有的权限目录和安全 DTO，补齐总览、人员、角色、身份、渠道、Job、MCP、Resource 与 Credential 管理 API；不得创建旧 Capability/Mapping 表。
3. 恢复管理 Shell 和导航，再按 Agent/Application → 人员/RBAC/身份 → MCP/Resource/Credential → 渠道/调试/历史顺序接入真实 API。
4. 对每个写操作补权限、CSRF、revision、幂等、依赖保护和审计测试；对敏感 DTO、日志与事件执行字段泄漏回归测试。
5. 在 Compose 集成环境执行 Database/Redis/Loki、ONES 身份、DingTalk 绑定和真实 Job→MCP 链路验收；确认旧 API/Internal Platform 容器、路由、导航和数据库对象均未恢复。
6. 分页面启用控制台；出现控制面问题时可回退前端和管理 API 版本，当前 Publication/Runtime/Resource Generation 继续运行，无需数据迁移。

## Risks / Trade-offs

- **[备份 UI 携带旧领域语义]** → 建立允许清单，仅复用展示组件；旧路由、Capability、Mapping 和 fixture 名称加入静态/路由回归测试。
- **[两态 Resource UI 掩盖内部失败]** → 主状态保持简单，同时显示只读健康、当前有效版本、最近错误与受影响对象；所有切换仍由事务状态机完成。
- **[权限面扩大]** → 权限代码服务端拥有、默认拒绝、读写分离；新增 API 必须包含负向授权与越权枚举测试。
- **[数据库 Secret Provider 增加 Master Key 运维责任]** → 启动时验证 Key 文件权限和长度，缺失时 Credential/Resource mutation fail-closed；不回退明文环境变量。
- **[完整恢复页面导致交付面较大]** → 按垂直功能切片实施，每片包含 API、UI、授权、审计和测试，不先建新的通用前端平台抽象。
- **[多个并行 OpenSpec 基线漂移]** → 实施前先验收并固定 MCP 与 TypeScript Runtime 基线；本变更只依赖当前分支，不从 `master` 或备份覆盖现有实现。

## Open Questions

无。MCP 注册边界、精确 Resource 绑定和 Credential Center 均已确认；OpenTelemetry 明确延期。
