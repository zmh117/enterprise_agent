## Context

当前后端已经实现：

- `AuthService`、`/api/auth/login`、`/me`、`/logout`、修改密码和Session撤销；
- HttpOnly Session Cookie、CSRF Cookie/Header校验、Session idle/absolute expiry和登录限流；
- `app_user`、`user_external_identity`、角色、权限和统一授权求值；
- 管理端用户、角色、钉钉绑定、身份状态和冲突查询API；
- 钉钉入口在创建Agent Job前把受信tenant下的外部主体解析为内部用户，未知身份fail closed。

但前端仍是纯静态原型：没有Router、认证状态、API Client和真实用户数据。现有外部身份管理也主要围绕钉钉专用接口，`connector_id`语义依赖Channel Connector，无法表达不是消息渠道的ONES实例、一次性Provider验证、pending claim和可治理冲突。

用户已经提供ONES登录、工作项类型和需求/任务/缺陷报文，并建立独立ONES Mock。当前阶段只需要完成可信身份映射；业务接口调用将来由API Capability接入。因此必须严格区分：

```text
身份验证结果：
ONES user UUID + team UUIDs

临时登录材料：
email + password + response token

未来业务调用凭据：
由独立Credential/API Capability边界管理
```

只有第一类进入外部身份记录。第二类在单次请求后销毁，第三类不属于本变更。

## Goals / Non-Goals

**Goals:**

- 将现有管理Web连接到已经落地的本地认证和服务端Session。
- 建立可复用的前端Router、认证状态、CSRF API Client和权限导航基础。
- 让管理员真实管理内部用户、钉钉/ONES外部身份、pending claim、验证状态和冲突。
- 支持普通内部用户在“我的外部身份”中自助验证自己的ONES账号。
- 建立独立的外部身份Connection与Provider Adapter模型，未来新增其它业务系统不修改`app_user`。
- 通过受信ONES连接执行一次性登录验证，只保存用户UUID和团队上下文。
- 保持钉钉入口、内部RBAC和外部系统原生权限分别生效。
- 为后续Business Application控制面复用前端认证、路由和API基础。

**Non-Goals:**

- 不重写现有AuthService、密码哈希、Session和RBAC。
- 不实现OIDC、企业SSO、钉钉扫码登录或外部身份直接登录管理Web。
- 不按姓名、显示名、手机号或邮箱自动合并内部用户。
- 不进行ONES组织目录全量同步。
- 不把ONES Token保存成长期Credential，也不调用需求、任务或缺陷接口。
- 不实现API Capability、Capability Gateway或Agent自主调用ONES。
- 不实现Business Application、Workflow或运行中心真实页面。
- 不允许服务账号登录、绑定个人外部身份或执行自助验证。

## Decisions

### 1. 复用现有Auth API，前端建立单一认证状态机

前端增加：

```text
src/app/router/
src/contexts/auth/
  domain/
  application/
  infrastructure/
  presentation/
src/shared/api/
```

应用启动时只通过`GET /api/auth/me`恢复认证状态：

```text
unknown → authenticated
        ↘ anonymous
```

受保护路由在`unknown`期间显示阻塞式加载状态；`anonymous`进入`/login`；已登录用户访问`/login`时返回原目标页。`returnTo`只接受站内相对路径，防止开放重定向。

浏览器不保存Session Token。所有API请求使用同源`credentials: include`。写请求从非HttpOnly CSRF Cookie读取值并发送`X-CSRF-Token`。增加一个不含Secret的`GET /api/auth/config`或等效响应，告诉前端CSRF Cookie名称、Web管理是否启用和安全展示配置，避免把可配置Cookie名称硬编码在多个模块。

采用TanStack Query维护`auth.me`和Server State，不使用自建全局可变store复制用户与权限数据。401统一清除认证查询并进入登录页；403保留登录态并展示无权限。

### 2. 登录、安全设置和身份管理共享认证Shell

新增页面：

```text
/login
/profile/security
/profile/external-identities
/admin/users
/admin/users/:userId
/admin/external-identities
/admin/external-identity-connections
```

`/profile/security`连接修改密码、当前Session列表和撤销接口。修改密码会使所有Session失效，因此前端成功后立即返回登录页。

导航依据`/api/auth/me`返回的能力显示；隐藏导航不是授权，后端每个API继续执行RBAC。无`user:manage`的普通用户只能管理自己的安全设置和自助外部身份验证，不能指定其它内部用户。

### 3. 外部身份Connection独立于Channel Connector

新增`external_identity_connection`：

```text
id
code
name
provider
tenant_code
verification_mode
connector_id
base_url
allowed_hosts_json
tls_required
status
config_json
revision
created_by / created_at / updated_at
```

- 钉钉Connection引用现有Channel Connector，`base_url`为空；
- ONES Connection保存受信实例的非敏感Base URL、tenant/instance code和允许Host；
- Provider、验证模式和config使用严格schema，不能定义任意请求Method、Path或Header；
- ONES登录Path由Provider Adapter代码固定为`/project/api/project/auth/login`。

不复用`integration_connector`表达ONES，因为ONES当前不是Channel入口或Delivery；强行复用会混淆方向校验和凭据语义。`connector_id`保留为可选桥接字段，使既有钉钉绑定可以迁移。

Connection管理要求独立`identity_connection:manage`权限。生产ONES连接必须HTTPS；本地开发只有在明确`allow_insecure_local=true`且Host命中开发allowlist时才能使用HTTP Mock。验证请求不能传入URL，避免SSRF。

### 4. 身份可用状态与验证状态分离

扩展`user_external_identity`：

```text
connection_id
verification_status
verification_method
verified_by_user_id
provider_context_json
last_verified_at
last_verification_error_code
```

保留现有`status=enabled|disabled`表示管理员是否允许使用；`verification_status`表示身份真实性：

```text
pending
verified
conflict
revoked
```

身份只有同时满足以下条件才可作为可信主体：

```text
内部用户 enabled 且 account_type=human
∩ identity status=enabled
∩ verification_status=verified
∩ connection status=enabled
```

现有钉钉绑定迁移为`verified/admin_asserted`，从Connector派生Connection；这保持当前钉钉消息行为。ONES身份必须经过Provider登录验证才能成为verified，管理员手工录入UUID只能创建pending claim。

### 5. Pending和冲突使用Claim建模，不制造重复身份

新增`external_identity_claim`：

```text
id
user_id
connection_id
proposed_external_subject_id
display_hint
status
verification_method
conflict_identity_id
evidence_summary_json
revision
created_by / created_at / updated_at / expires_at
```

Claim状态：

```text
pending → verified
        ↘ conflict
        ↘ rejected / expired / cancelled
```

管理员可为用户创建pending claim，但不能把它当作可用身份。用户通过Provider验证后：

- 如果返回subject尚未绑定，事务创建verified identity并完成claim；
- 如果已绑定同一内部用户，幂等更新验证时间和团队上下文；
- 如果绑定其它用户，claim进入conflict，现有identity不变；
- 如果用户、Connection或claim revision已变化，返回冲突。

不提供“一键强制转移”。管理员只能保留现有绑定、拒绝claim，或先显式停用/撤销旧绑定，再要求目标用户重新验证。每一步都有独立revision和审计，避免误把外部账号转给错误人员。

### 6. Provider Adapter返回规范化主体，不泄露验证材料

定义端口：

```text
ExternalIdentityVerifier.verify(
  connection,
  verification_proof,
  request_context
) -> VerifiedExternalSubject
```

规范化结果：

```text
provider
external_subject_id
display_name
provider_context
verification_method
verified_at
```

Provider Proof是短生命周期对象，不允许序列化进Repository、Audit或异常。ONES Proof包含email/password；Pydantic使用`SecretStr`或等效类型，日志/模型repr必须脱敏。

第一版Adapter：

- `DingTalkAdminVerifier`：只接受已启用且允许ingress的受信Connector，由有权限管理员确认`senderStaffId`；
- `OnesPasswordVerifier`：向固定登录Path发送email/password，严格解析`user.uuid`、`user.name`和`teams[].uuid`。

`OnesPasswordVerifier`不得把响应`user.token`放入规范化结果。解析完成后立即丢弃原始响应引用；应用服务和API响应看不到Token。

### 7. ONES网络调用实行固定路径、限流、超时和响应上限

ONES Adapter从Connection读取Base URL，执行以下防护：

- scheme和Host必须与已保存、已校验Connection完全一致；
- 禁止请求级URL、重定向和代理继承；
- 登录Path固定，Method固定为POST，Content-Type固定为JSON；
- 连接与读取使用短超时；
- 响应体设置小型上限并要求JSON；
- 只接受非空`user.uuid`和至少一个合法team UUID；
- 上游401映射为统一“ONES凭据验证失败”，不区分邮箱或密码；
- 其它上游故障返回安全、可重试或不可重试错误码，不回显响应正文。

验证尝试按内部用户、Connection和来源地址限流。结果写入append-only的`external_identity_verification_attempt`或等效安全审计投影，只保存outcome、error code、connection、actor、claim和subject摘要，不保存email、password、Token或原始响应。

开发集成测试使用`docker-compose.ones-mock.yml`的明显假凭据。仓库测试和文档必须扫描并禁止真实ONES IP、邮箱、UUID和Token。

### 8. ONES团队UUID属于身份上下文，不是平台授权

成功验证后`provider_context_json`只允许保存受控结构：

```json
{
  "team_uuids": ["MOCK-ONES-TEAM-001"]
}
```

团队UUID用于将来Capability调用时提供已验证身份线索，但本变更不依据team自动生成RBAC、不授予项目权限，也不保存登录Token。未来业务调用若需要用户Token，必须由单独Credential/Vault变更决定生命周期、加密、刷新和撤销。

用户详情同时展示：

```text
内部角色与权限
外部身份Provider/Connection/Subject
验证状态与团队上下文
“关联不等于授权”说明
```

### 9. 管理API采用通用Provider资源并保留钉钉兼容端点

新增或扩展：

```text
GET/POST/PUT /api/admin/external-identity-connections
GET          /api/admin/external-identity-providers
GET          /api/admin/external-identities
POST         /api/admin/users/{id}/external-identity-claims
GET          /api/admin/users/{id}/external-identity-claims
POST         /api/admin/external-identity-claims/{id}/resolve
POST         /api/me/external-identity-claims/{id}/verify
GET          /api/me/external-identities
PUT/DELETE   /api/admin/external-identities/{id}
```

现有`POST /api/admin/users/{id}/dingtalk-identities`保留兼容，内部改用通用Connection/Claim服务并返回同样安全摘要。通用API请求使用`extra="forbid"`和expected revision。

权限：

```text
identity:manage
identity_connection:manage
identity_conflict:resolve
identity:self_verify
user:manage
```

管理员不能替普通用户调用`/api/me`自助验证；如确需协助输入凭据，必须在目标用户已登录的浏览器会话中完成，避免管理员收集用户密码。

### 10. 前端按Auth与External Identity上下文分层

目标结构：

```text
frontend/src/
  app/router/
  contexts/auth/
  contexts/users/
  contexts/external-identities/
    domain/
    application/
    infrastructure/
    presentation/
  shared/api/
  components/ui/
```

现有`external-identity-map.tsx`保留为Dashboard产品说明，但其中“管理关联”入口改为真实路由；真实页面不得从`mocks/dashboard.ts`读取用户或身份。

表单行为：

- 密码输入使用`type=password`、禁用浏览器意外回显，提交后立即清空；
- ONES验证Mutation不得写入Query Cache、URL、history state、Toast详情或错误遥测；
- identity/claim/connection更新携带expected revision；
- 409显示刷新和对比提示，不静默覆盖；
- 权限不足隐藏动作并由后端再次拒绝；
- 手机和桌面均保持身份关系、状态、冲突原因和验证步骤可读。

### 11. 功能开关与落地顺序

复用：

```text
FEATURE_UNIFIED_IDENTITY
FEATURE_WEB_ADMIN
```

新增：

```text
FEATURE_EXTERNAL_IDENTITY_MANAGEMENT
FEATURE_ONES_IDENTITY_VERIFICATION
```

关闭ONES验证时，已有钉钉和管理登录继续工作，ONES连接与验证入口显示未启用。关闭External Identity Management时，不注册新增写API，现有钉钉运行时解析保持原样。

建议先实施本变更，再实施`add-business-application-control-plane-foundation`，后者直接复用Router、Auth Guard、TanStack Query和统一API Client，避免两次建立前端基础。

## Risks / Trade-offs

- [把ONES登录密码通过管理端传输存在敏感风险] → 只允许HTTPS/本地Mock，使用Secret类型、禁止持久化和日志，提交后立即清空，并优先让用户自助验证自己的身份。
- [ONES返回Token被框架或异常自动记录] → Adapter在边界内解析并丢弃原始响应，禁止记录body，契约测试扫描Repository、Audit、API响应和日志。
- [管理员错误绑定同名人员] → 不按姓名/邮箱自动匹配；ONES verified必须由Provider登录证明，钉钉管理员确认也必须选择受信tenant/connector。
- [两个内部用户争用同一外部主体] → 唯一约束保持原绑定，创建conflict claim且禁止强制覆盖。
- [Connection Base URL引入SSRF] → URL只能来自高权限Connection配置，Provider固定Path/Method，校验scheme/host/allowlist并禁止重定向和请求级URL。
- [ONES团队变化导致上下文陈旧] → 展示last verified时间，支持重新验证刷新team列表；团队上下文不直接授予平台权限。
- [前端隐藏菜单被误当安全边界] → 每个API继续执行Session、RBAC、CSRF和对象级授权，前端能力仅用于体验。
- [同时实施业务应用控制面产生前端冲突] → 明确本变更先落地共享Router/Auth/API层，业务应用变更随后基于该基线实施。
- [旧钉钉身份迁移影响正在使用的用户] → 迁移为verified/admin_asserted并保留原唯一键、connector和enabled状态，运行时解析语义不变。

## Migration Plan

1. 新增Connection、Claim、Verification Attempt表及外部身份验证字段，不改变现有身份唯一键。
2. 从启用的钉钉企业Stream Connector幂等生成DingTalk Connection，把现有钉钉身份标记为verified/admin_asserted。
3. 实现Provider端口、通用Identity服务和Fake Adapter测试，再实现ONES Adapter并只连接本地Mock。
4. 扩展管理与`/api/me` API，默认关闭新增功能开关，运行现有钉钉身份回归。
5. 建立前端Router、Auth Guard、API Client、登录、安全设置和权限导航。
6. 上线用户、Connection、Identity、Claim、Conflict和ONES自助验证页面。
7. 在开发环境开启ONES验证，对Mock执行登录→UUID/team提取→绑定→重复验证→冲突→停用完整验收。
8. 在测试环境配置受信ONES HTTPS连接，使用专用测试账号验证无Token持久化后再开放。

回滚时先关闭`FEATURE_ONES_IDENTITY_VERIFICATION`和`FEATURE_EXTERNAL_IDENTITY_MANAGEMENT`，前端隐藏新增入口；现有Auth、RBAC和钉钉解析继续工作。新增表和字段可保留，不能在尚有新身份引用时直接删除。任何回滚都不得恢复按请求头伪造管理员身份。

## Open Questions

无。本阶段确定采用用户自助ONES验证、管理员治理Connection/Claim/Conflict且不保存业务调用Token；未来是否使用用户Token、服务账号或API平台委托调用ONES，由API Capability变更另行决定。
