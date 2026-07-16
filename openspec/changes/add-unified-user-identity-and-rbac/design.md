## Context

系统目前有三套彼此未统一的“身份”：

- 钉钉 Stream adapter 从 payload 读取 `senderStaffId` 或 `senderId`，并直接把它作为 Channel actor、job requester 和 `permission_policy.subject_code`。
- Web/平台配置接口从 `x-admin-user-id` 或 `x-agent-user-id` 接受调用方自报的 actor，只适合测试，不构成可信认证。
- `permission_policy` 和 `platform_access_grant` 虽然预留了 user/role/group/service 等主体类型，但当前权限服务只按一个字符串直接查询 allow，没有用户角色展开、统一 deny 语义或外部身份解析。

Agent 行为也缺少独立配置聚合。模型和执行限制主要来自全局 runtime config，系统角色、安全规则、工具列表、Skill 和报告格式主要由代码构造；已有 workflow template 虽支持草稿和发布，但尚未接入 Agent job runtime。仓库当前没有前端工程。

本 change 的关键约束是：

- 内部用户必须成为 Web、钉钉、Agent job、工具调用、平台授权和审计的唯一权限主体。
- 钉钉身份绑定必须包含 tenant/corp 边界，不能仅凭昵称、手机号或跨企业不唯一的员工号自动匹配。
- 管理端必须建立可信认证，不能继续相信客户端自报身份头。
- Web 可编辑业务配置，但不可弱化只读工具、安全规则、数据权限和 secret 边界。
- 数据模型从第一天支持多 Agent；第一版产品只暴露一个默认诊断 Agent，控制交付范围。

## Goals / Non-Goals

**Goals:**

- 建立内部用户、本地密码身份、钉钉外部身份和服务端 session 的统一身份模型。
- 支持管理员手工绑定、解绑、启停钉钉身份，并让 Web 与钉钉共享用户角色、工具权限和数据范围。
- 建立可复用的 RBAC 求值器，统一处理用户直接策略、角色策略、平台访问授权、通配符和 deny。
- 建立 Agent 定义、草稿 revision、不可变发布快照、回滚和 job 版本固定能力。
- 让默认诊断 Agent 可以通过 Web 管理业务指令、模型策略、执行限制、Skill、只读工具与 Channel/Delivery 绑定。
- 提供安全、可审计的管理 API 和第一版 Web 管理端。
- 兼容现有钉钉入口、平台配置、工作流、工具调用和历史 job/audit 数据。

**Non-Goals:**

- 不在本 change 中实现企业 OIDC/SSO、钉钉扫码登录或钉钉组织架构自动同步。
- 不实现用户通过机器人一次性绑定码自助绑定，只预留 application port 和状态模型。
- 不允许 Web 新建任意 HTTP API、MCP server、脚本、Shell、写 SQL 或代码执行工具。
- 不实现多 Agent 切换入口、Agent 市场、工作流画布或 workflow runtime 执行；UI 只开放默认诊断 Agent。
- 不恢复或扩展 DOCX/XLSX/PPTX/Markdown 附件提取验收。
- 不让 Agent 草稿、角色草稿或权限编辑立即改变运行中的 job。

## Decisions

### 1. 内部用户是唯一权限主体，外部身份只负责解析

新增稳定内部用户 ID，所有新权限、job、工具调用和配置审计都引用内部用户。外部身份使用通用表表达：

```text
app_user
├── user_password_credential
├── user_external_identity(provider=dingtalk, tenant_code, external_subject_id)
├── user_role ── role
└── user_session
```

钉钉唯一键为：

```text
provider + tenant_code + external_subject_id
```

其中 `tenant_code` 来自受信 connector 配置的企业/corp 标识，`external_subject_id` 优先使用 `senderStaffId`。`senderId`、unionId/openId 等可作为附加标识和 last-seen metadata，但不能在没有 tenant 的情况下单独作为全局用户键。

选择通用外部身份表而不是 `app_user.dingtalk_user_id`，是为了支持一个用户绑定多个钉钉企业身份以及后续 OIDC/企业 SSO，而不改变权限表。昵称、姓名、手机号和邮箱不得自动建立绑定。

### 2. 第一版只允许管理员手工绑定，未绑定身份 fail closed

管理员在 Web 选择内部用户、DingTalk tenant/connector 并输入 `senderStaffId` 完成绑定。系统必须检查：

- tenant/connector 已启用且允许 ingress；
- 外部身份未绑定其他用户；
- 用户与身份均为 enabled；
- 绑定、解绑、冲突、拒绝均被审计。

未知或已禁用的钉钉身份返回安全拒绝，不自动创建用户。相比自动 provisioning，这会增加初始录入工作，但避免任何能联系机器人者自动获得系统主体。

### 3. 本地登录使用服务端 session，不使用浏览器持有长期 JWT

第一版管理端采用用户名密码和 PostgreSQL 服务端 session：

- 密码使用 Argon2id 等经过审计的 password hashing library；
- 登录成功生成高熵随机 token，只把 token 放入 `HttpOnly`、`SameSite=Lax` cookie；
- 数据库只保存 token hash、过期时间、创建/最后使用时间、撤销状态和安全设备摘要；
- 修改密码、禁用用户、管理员撤销会话时，使相关 session 立即失效；
- state-changing API 使用 SameSite cookie、Origin 校验和 CSRF token 形成纵深防御；
- 生产环境 cookie 必须 `Secure`，本地开发可显式关闭。

管理 API actor 由 authentication middleware 注入。`x-admin-user-id` 仅保留为显式 test-only adapter，生产配置必须禁用。

首次管理员不通过匿名 Web 注册创建。提供显式 CLI/bootstrap 命令创建首个管理员；本地测试 seed 可创建固定测试用户，但生产 migration 不写入默认密码。

### 4. RBAC 统一展开用户与角色，deny 优先

权限求值输入为内部用户、资源类型、资源编码、作用域和动作。求值器展开：

```text
user principal
+ enabled role principals
+ enabled platform access grants
```

规则为：

- disabled 用户、角色、身份、grant 或 policy 不参与 allow；
- 命中的显式 deny 优先于 allow；
- 更具体资源/作用域优先于通配符，同级按既有 priority 求值；
- 平台 topology 范围和工具权限必须同时通过；
- Agent 工具调用还必须通过工具启用、Agent 分配和只读风险策略；
- 管理端动作使用独立资源和 action，例如 `user:manage`、`role:manage`、`agent:publish`、`platform_config:manage`。

保留 `permission_policy` 和 `platform_access_grant` 作为策略事实表，新增 user/role membership 并重构 evaluator，而不是再创建一套互不相通的 Web ACL。

### 5. 身份解析发生在 job 持久化前，原始外部身份单独追踪

Channel adapter 只归一化外部身份描述，不自行决定内部 user：

```text
DingTalk payload
  → ExternalIdentityDescriptor
  → IdentityResolver
  → AuthenticatedPrincipal(app_user.id, roles, external_identity_id)
  → connector/project permission
  → session/job persistence
```

新 job 的 `requester_id/user_id` 使用内部用户 ID，并保存 `external_identity_id` 和 source connector。历史 `requester_id` 不强制重写；迁移为现有 `subject_type=user` 的原始钉钉主体创建 legacy 用户/映射，无法可靠归属的记录保持 legacy actor，避免错误合并。

私聊 session key 使用内部用户 ID 与 bot identity，因此同一钉钉用户在绑定后保持稳定；不同 Channel 仍维持各自 conversation/session 边界，不因为身份统一而自动共享聊天记录。

### 6. Agent 配置使用定义、草稿 revision 和不可变发布快照

数据模型分为：

```text
agent_definition
  └── agent_revision (draft/validated)
        └── agent_publication (immutable snapshot/hash)
              ├── agent_tool_binding
              ├── agent_skill_binding
              └── agent_channel_binding
```

`agent_definition` 支持多个 Agent。seed 创建稳定 code 的 `default-diagnostic-agent`。第一版 API 底层可按 Agent code 工作，但 Web 路由只展示该默认 Agent，不提供“新建 Agent”按钮。

发布快照包含：

- 可编辑的业务角色/业务指令；
- 模型选择策略和执行限制；
- 允许的只读工具 code；
- 允许的 Skill code；
- 默认 project/routing；
- ingress/delivery connector 绑定；
- schema version、revision、config hash、发布人和发布时间。

平台强制安全规则、SDK 内置写工具禁用、只读策略、secret 值和用户权限不进入可编辑快照，运行时在发布配置外层强制叠加。

### 7. Job 固定 Agent publication，worker 不读取活动草稿

Channel 或 Web 创建 job 时先解析目标 Agent；第一版默认选择 `default-diagnostic-agent`。创建事务固定：

```text
agent_definition_id
agent_publication_id
agent_revision
agent_config_hash
```

RabbitMQ 仍只发送 `job_id/correlation_id`。worker 通过 job 读取指定 publication snapshot。发布新版本只影响之后创建的 job，重试继续使用原 publication。回滚通过把某个历史 publication 设为当前版本实现，不修改不可变快照。

如果默认 Agent 尚未发布、发布已禁用、配置 hash 不匹配或快照无法校验，系统必须拒绝创建新 job，而不是回退到编辑中的草稿。

### 8. 工具可用性取多层安全交集

最终暴露给模型的工具集合为：

```text
代码注册且只读
∩ tool_definition 已启用
∩ Agent publication 已分配
∩ 用户或角色有 tool 权限
∩ 当前 topology/data scope 允许
```

管理员可在默认 Agent 页面分配已有只读工具，但不能通过 UI 构造新的 executable adapter。即使发布快照错误包含写工具 code，发布校验和 runtime registry 都必须拒绝。

### 9. 前端采用独立 TypeScript 管理端并以 API 为唯一数据源

新增独立 `frontend/` 管理端，采用 React + TypeScript + Vite，使用 TanStack Query 管理 server state，并复用 shadcn 风格组件体系。前端不直接读数据库、环境变量或 secret 明文。

第一版页面：

```text
/login
/admin/users
/admin/roles
/admin/users/:id/identities
/admin/agents/default-diagnostic-agent
/admin/agents/default-diagnostic-agent/publications
/admin/audit
```

默认 Agent 页面包含基础信息、业务指令、模型/限制、工具、Skill、Channel/Delivery、有效配置预览、校验、发布和回滚。隐藏多 Agent 创建入口不等于后端单 Agent 建模。

### 10. 管理 API 使用 typed DTO、revision 和审计

新增 `/api/auth/*`、`/api/admin/users/*`、`/api/admin/roles/*`、`/api/admin/agents/*`。写接口必须：

- 从 session principal 获取 actor；
- 校验 action permission；
- 使用 expected revision 或 ETag 防止覆盖并发编辑；
- 返回 field-level validation error；
- 记录 before/after 安全摘要、actor、target、action、correlation id；
- 不返回 password hash、session token/hash、secret value/ciphertext 或完整敏感外部 payload。

现有平台配置与 workflow API 逐步迁移到同一 authentication dependency。测试中可以显式注入 principal，不在业务 service 中解析 HTTP header。

## Risks / Trade-offs

- [身份错误绑定会继承他人权限] → tenant + senderStaffId 唯一约束、管理员确认、冲突拒绝、绑定审计、禁止昵称/手机号自动匹配。
- [切换到内部用户 ID 导致现有权限失效] → 提供 legacy principal 迁移和对账报告，先双读验证再切换，历史运行记录不强制重写。
- [角色与直接策略组合复杂] → 统一 evaluator、deny 优先、决策 trace 和表驱动测试，不让各模块自行拼权限 SQL。
- [cookie session 带来 CSRF 风险] → SameSite、Origin/CSRF 校验、Secure/HttpOnly、短 idle timeout 和管理员撤销。
- [Web 可编辑 prompt 造成安全规则覆盖] → 业务指令与平台安全指令分层，发布校验拒绝越权字段，runtime 最外层强制安全策略。
- [多 Agent 数据模型扩大第一版工作量] → 后端模型和 API 按多 Agent 设计，seed/UI 只开放一个默认 Agent，暂不实现创建和切换体验。
- [配置发布与 job 并发导致版本漂移] → job 创建事务固定 publication ID/hash，worker 不读取“当前版本”指针。
- [工具分配被误解为工具开发] → 第一版只分配代码注册的已有只读工具；动态 HTTP API 工具另立 change。
- [现有平台接口依赖自报 header] → 提供短期 test-only compatibility adapter，生产启动时默认拒绝未认证 header。
- [前后端同时开发导致契约反复] → 先完成 migration、domain、typed API 和 contract tests，再实现 Web 页面。

## Migration Plan

1. 增加加法 migration，创建用户、凭证、外部身份、session、角色关系、Agent 配置/发布表，并为 job 增加可空的内部主体和 Agent publication 字段。
2. 根据现有 `permission_policy.subject_type=user`、平台 grant、历史 requester 和已知钉钉 connector 生成 legacy identity 对账清单；只自动迁移可唯一确定 tenant 的主体。
3. seed 默认角色、默认诊断 Agent 草稿和等价于当前代码行为的首个发布快照；不创建生产默认密码。
4. 实现统一身份 resolver 和 RBAC evaluator，在 shadow mode 同时记录旧/新权限决策差异，不立即改变生产入口。
5. 启用管理员手工绑定和管理 session；完成现有管理员权限向内部用户/角色迁移。
6. 钉钉入口切换为先解析内部用户再授权；未绑定身份 fail closed，并提供安全提示和审计。
7. job 创建开始固定默认 Agent publication；worker 改为读取该快照。旧 job 使用 legacy runtime adapter 保持可重试。
8. 平台配置/workflow API 切换到 session principal，保留仅测试环境可用的 header adapter。
9. 上线 Web 管理端并执行真实验证：登录、用户启停、绑定、角色权限、钉钉请求、工具调用、Agent 发布/回滚和审计。

回滚时可关闭统一身份、Web admin 和 published-agent-runtime feature flags，使新入口暂时回到现有 runtime；新增表和历史绑定保留。已创建且固定 publication 的 job 继续按其快照执行或通过运维策略安全失败，不删除审计记录。

## Open Questions

- 生产环境最终采用哪一种企业 OIDC/SSO 提供方，留到后续 change 决定。
- 是否需要一个用户绑定多个钉钉 tenant；数据模型允许，第一版 UI 可先限制为一个启用绑定。
- 默认 Agent 的模型选择是否允许覆盖全局 provider/base URL；本设计只允许选择已注册模型策略，不允许 Agent revision 保存密钥或任意 provider URL。
