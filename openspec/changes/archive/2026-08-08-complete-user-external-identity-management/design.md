## Context

当前系统已经有以下可复用基础：

- `app_user`、`user_external_identity`、本地密码、Web Session、CSRF 与 RBAC；
- `/api/admin/users`、用户详情/更新、钉钉身份绑定、身份启停/解绑和冲突查询 API；
- 钉钉 Stream 在创建 Job 前把 `provider + tenant_code + external_subject_id` 解析为内部用户；
- 前端已经有同源 Session 登录门禁和统一 `apiRequest`，但“用户与外部身份”仍是禁用导航和静态说明；
- 独立 `docker-compose.ones-mock.yml` 已提供 ONES 登录响应，其中 UUID 和团队 UUID 可用于身份验证，Token 只用于后续业务请求。

本变更必须在不扩张其它控制面模块的前提下完成用户管理和两种外部身份绑定。身份映射只回答“这个外部主体对应哪个内部用户”，不能顺便授予角色、Capability 或 ONES 业务数据权限。

## Goals / Non-Goals

**Goals:**

- 提供可真实操作的用户列表、用户详情、新建、编辑、启停页面。
- 在用户详情页管理钉钉与 ONES 身份的绑定、状态和解绑。
- 复用现有唯一约束和钉钉解析链路，确保绑定立即影响新钉钉请求。
- 通过固定、受信的 ONES 登录端点验证 UUID 和团队上下文。
- 保证 ONES 邮箱、密码、Token 和原始响应不进入持久化、审计、日志、前端缓存或 URL。
- 保持前后端 DDD 目录边界、乐观并发、RBAC、CSRF 和安全审计。

**Non-Goals:**

- 不实现角色、权限、Session、安全设置或审计日志管理页面。
- 不实现外部身份自助验证、Claim、待审核、强制转移或独立冲突治理中心。
- 不实现外部身份 Connection 的 Web CRUD；第一版只读取服务端配置的一个 ONES 实例和现有钉钉 Connector。
- 不支持钉钉扫码登录、SSO、自动目录同步、按姓名/邮箱/手机号自动匹配。
- 不支持除 `dingtalk`、`ones` 外的 Provider 写入。
- 不调用 ONES 需求、任务、缺陷接口，不保存用于业务调用的 ONES Token。
- 不改业务应用、Agent、Workflow、Skill、API Capability、Channel 或运行中心页面。

## Decisions

### 1. 页面只建立“用户目录 → 用户详情 → 外部身份”一条工作流

新增真实路由：

```text
/users
/users/:userId
```

`/users` 支持加载、刷新、搜索、新建用户和状态展示；`/users/:userId` 支持基本资料编辑、启停，以及钉钉/ONES身份卡片。左侧“用户与外部身份”导航启用并指向 `/users`，其它禁用导航保持不变。

不创建全局身份中心、Connection 管理页或个人自助页。这样可以满足管理员为用户完成关联的直接目标，并避免把旧提案的治理平台重新带回本次范围。

前端目录：

```text
frontend/src/contexts/users/
  domain/
  application/
  infrastructure/
  presentation/

frontend/src/contexts/external-identities/
  domain/
  application/
  infrastructure/
  presentation/
```

TanStack Query 只保存用户和脱敏身份 Server State；ONES 密码只存在绑定表单组件的局部状态。

### 2. 复用现有表，不引入 Claim 和 Connection 数据模型

`user_external_identity` 已包含：

```text
provider
tenant_code
external_subject_id
connector_id
display_name
status
verified_at
last_seen_at
metadata_json
revision
```

这足以表达本阶段已经验证成功的身份。失败的 ONES 登录不创建记录，因此不需要 `pending` 或 Claim 状态；身份争用直接由现有唯一约束拒绝并返回安全冲突。

Provider 约定：

- 钉钉：`tenant_code` 是受信 Connector 的 tenant，`external_subject_id` 是 `senderStaffId`，`connector_id` 必填；
- ONES：`tenant_code` 是服务端配置的实例编码，`external_subject_id` 是登录响应 `user.uuid`，`connector_id` 为空；
- `metadata_json` 使用严格白名单，只保存 `verification_method` 和去重后的 `team_uuids`，不得接受任意客户端 JSON。

不新增表的代价是暂不保留失败 Claim 和完整验证历史；现有 `audit_event` 记录安全结果即可。

### 3. ONES 连接是服务端单实例配置，不提供页面编辑

新增非功能开关配置：

```text
ONES_IDENTITY_INSTANCE_CODE
ONES_IDENTITY_BASE_URL
ONES_IDENTITY_ALLOWED_HOSTS
ONES_IDENTITY_TIMEOUT_SECONDS
ONES_IDENTITY_MAX_RESPONSE_BYTES
ONES_IDENTITY_ALLOW_INSECURE_LOCAL
```

配置遵循现有 bootstrap/runtime-config 边界，但不增加 `FEATURE_*`。API 只向前端返回实例编码、显示名称和可用状态，不返回内部地址。

第一版只支持一个已配置 ONES 实例。与新增 Connection 表相比，这能显著降低当前 UI、迁移和治理范围；未来确需多个 ONES 或其它 Provider 时，再以独立 change 引入 Connection 聚合。

### 4. ONES 绑定必须先由 Provider 验证，不能手工提交 UUID

新增端口：

```text
OnesIdentityVerifier.verify(email, password) -> VerifiedOnesIdentity
```

规范化结果只包含：

```text
user_uuid
display_name
team_uuids
verified_at
```

适配器固定调用 `/project/api/project/auth/login`，固定使用 `POST application/json`，禁止请求级 URL、重定向和环境代理继承，并执行 Host allowlist、生产 HTTPS、短超时、响应大小上限和严格 JSON Schema 校验。

响应中的 `user.token` 在适配器边界立即丢弃。应用服务、Repository、Audit、API Response 和前端 Query Cache 都不得接触 Token。错误只映射为稳定错误码，例如：

```text
ones_invalid_credentials
ones_connection_unavailable
ones_response_invalid
ones_identity_conflict
```

不支持“管理员直接填写 ONES UUID”，因为那会把未验证声明变成可信身份。

### 5. 管理 API 只扩展用户详情所需端点

复用：

```text
GET/POST       /api/admin/users
GET/PUT        /api/admin/users/{userId}
POST           /api/admin/users/{userId}/dingtalk-identities
PUT/DELETE     /api/admin/identities/{identityId}
GET            /api/admin/dingtalk-tenants
GET            /api/admin/identity-conflicts
```

新增：

```text
GET  /api/admin/external-identity-providers
POST /api/admin/users/{userId}/ones-identities
```

用户列表可以增加可选搜索与分页参数，但保持原响应兼容。ONES 请求包含 `expected_user_revision`、`email` 和 Secret 类型的 `password`，禁止客户端提交 UUID、Token、URL、团队或 metadata。

所有写操作继续要求 Session、CSRF、`user:manage` 或 `identity:manage`，并携带 expected revision。服务账号可以展示，但不能绑定个人外部身份。

### 6. 用户停用与身份状态沿用现有 fail-closed 语义

- 用户被停用后，其管理 Session 失效，钉钉和 ONES 身份均不能解析为可用主体；
- 重新启用用户不会自动启用已停用身份；
- 身份“解绑”继续实现为受审计的 disabled 软删除，保留历史 Job 和审计引用；
- 对同一用户重复绑定同一外部主体保持幂等；
- 同一外部主体已属于其它用户时返回 409，不能覆盖或转移原绑定。

ONES 身份当前不参与 Channel ingress 或管理登录，但其状态和内部用户关系将为未来 API Capability 提供可信主体基础；本变更不实现该消费链路。

### 7. 审计只记录资源和结果，不记录验证材料

用户创建/修改/启停、钉钉绑定、ONES验证成功或失败、身份启停/解绑都记录内部 actor、目标用户、Provider、实例/tenant、身份记录 ID、结果和安全错误码。

明确禁止记录：

```text
ONES email/password/token
完整 ONES 响应
钉钉凭据或完整事件 payload
Session/CSRF 值
```

前端错误提示不得拼接上游响应正文；ONES密码在请求结束后无论成功失败都立即清空。

### 8. 旧大提案不作为本次实施清单

`connect-admin-auth-and-external-identity-management` 的认证部分已经由当前代码完成，其余 74 项包含多个超出本次目标的模块。本 change 的 specs/tasks 是本次唯一实施依据；实施时不得顺带完成旧提案中的角色页、Session页、Connection CRUD、自助验证或冲突治理中心。

## Risks / Trade-offs

- [管理员需要输入用户的 ONES 密码] → 只在一次 HTTPS 请求中使用，前端立即清空，后端使用 Secret 类型且禁止日志；未来如需更严格隔离再单独实现用户自助验证。
- [单 ONES 实例无法覆盖未来多实例] → 使用稳定实例编码写入 `tenant_code`，未来引入 Connection 表时可无损映射，不在本次提前建设管理面。
- [复用 `metadata_json` 可能容纳无界数据] → Repository 只接受服务端生成的白名单结构，API 不接受 metadata。
- [软解绑保留唯一键，无法立即转绑其他用户] → 优先保护身份归属和历史可追溯性；跨用户转移必须作为未来显式治理流程，不在本次提供危险覆盖。
- [前端启用用户菜单后扩大页面改动] → 只启用一个导航和两个路由，其它模块保持禁用，不改 Dashboard 产品说明。
- [ONES 上游错误可能泄露敏感正文] → 适配器禁止记录响应 body，并通过契约测试扫描日志、审计、数据库和 API。

## Migration Plan

1. 先补齐后端配置、ONES Verifier 和 API，保持前端导航禁用。
2. 用现有钉钉身份与 ONES Mock 执行后端集成测试，确认没有敏感数据落库。
3. 实现用户/身份前端工作区并完成浏览器测试。
4. 构建 API、Admin Web 与 ONES Mock，验证登录、用户管理、钉钉绑定、ONES绑定、冲突、禁用和解绑。
5. 发布前扫描数据库、日志、审计、浏览器存储和仓库，确认没有密码或 Token。

回滚时先恢复前端禁用导航并停止新增 ONES 绑定 API，再回滚适配器配置。已经创建的 ONES 身份仍是合法通用外部身份记录，可保留为 disabled；不得删除历史身份或破坏现有钉钉解析。

## Open Questions

无。本阶段固定采用“管理员管理、单 ONES 实例、两种 Provider、无自助/Claim/Connection UI”的边界。
