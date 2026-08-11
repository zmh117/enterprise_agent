# 统一身份、RBAC 与 Agent 管理端

该能力把 Web 管理员和钉钉用户统一映射为内部 `app_user`。权限只授予内部用户或角色；钉钉 `senderStaffId` 只有在受治理企业和受信应用消息共同确认后才是外部身份键，不能直接充当授权主体。

Web 分别治理 Python 与 TypeScript Agent；数据库、服务和运行时使用多 Agent 的 definition、draft revision、immutable publication 模型。新 job 在创建时固定 publication ID、runtime kind、revision 和 hash，后续发布或回滚不会改变已经创建的 job。

## 功能开关与启动

本地 HTTP 验收可在 `.env` 中设置：

```env
FEATURE_WEB_ADMIN=true
FEATURE_PUBLISHED_AGENT_RUNTIME=true
WEB_COOKIE_SECURE=false
WEB_ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
ADMIN_WEB_PORT=8080
DINGTALK_TENANT_CODE=default
DEFAULT_AGENT_CODE=default-diagnostic-agent
ONES_IDENTITY_INSTANCE_CODE=default
ONES_IDENTITY_DISPLAY_NAME=ONES
ONES_IDENTITY_BASE_URL=http://host.docker.internal:19121
ONES_IDENTITY_ALLOWED_HOSTS=host.docker.internal
ONES_IDENTITY_ALLOW_INSECURE_LOCAL=true
```

`FEATURE_WEB_ADMIN=true` 会同时启用统一身份、Web Session、RBAC 和业务应用控制面。
生产必须使用 HTTPS，并把 `WEB_COOKIE_SECURE` 设为 `true`。`WEB_ALLOWED_ORIGINS`
只配置明确可信的 Origin，不使用通配符。测试身份请求头只允许测试进程内部启用，
生产误配会导致启动失败。

启动管理端与 API：

```bash
FEATURE_WEB_ADMIN=true docker compose --profile admin up -d --build \
  postgres rabbitmq api-server admin-web
```

访问 `http://localhost:8080`。`admin-web` 由 Nginx 提供静态资源，并把同源 `/api` 代理到 `api-server`。空库的 schema migration 不插入用户；独立 bootstrap 在 local/test 缺少密码文件时创建开发账号 `admin` / `111111111111`，首次登录后应立即修改密码。生产环境没有固定默认密码。

## 首个管理员 bootstrap

生产环境通过权限为 `0400` 或 `0600` 的 Secret 文件创建首个管理员，密码不会出现在命令参数、普通环境变量、shell history 或日志中：

```bash
APP_ENV=production \
INITIAL_ADMIN_PASSWORD_FILE=/run/secrets/initial_admin_password \
python -m app.cli.bootstrap_admin --non-interactive
```

CLI 固定创建 `admin` / `Administrator`；也可在 TTY 中二次确认交互输入。已有任意启用的平台管理员时幂等退出，不重置密码或角色。完整步骤见 [空库与初始管理员](../operations/schema-baseline-bootstrap.md)。

## 用户与外部身份绑定

推荐顺序：

1. 在“用户与外部身份”创建内部用户。
2. 在“渠道与触发器”创建钉钉企业和应用连接，通过真实测试消息确认 Corp ID。
3. 让用户从该企业任一受信应用发送消息，平台按“企业 + Staff ID”形成待绑定候选。
4. 管理员在人员详情选择受信候选；Staff ID、Corp ID、昵称和来源应用不能手工输入。
5. 用户如需 ONES，在“我的外部身份”输入邮箱和一次性密码，选择验证结果中的默认 Team。

钉钉身份按“企业 + Staff ID”唯一；每名内部用户在同一企业最多一个当前身份，但可
拥有不同企业的身份。同企业换绑必须单独确认，旧当前身份软解绑；历史身份只能通过
匹配的受信候选恢复给原人员。应用观察只记录首次／最近受信时间，用于解释该身份曾
从哪些应用出现，不表示应用授权。

ONES 本人验证从一次登录响应提取 User ID、`user.name`、Team 名称与 ID。邮箱、密码、
登录 Token 和原始响应只存在于本次验证请求中，不进入数据库、Challenge、缓存、日志、
审计或 API 响应。平台只保存身份事实、默认 Team 和验证时间，不保存长期业务调用凭据。
重新验证会整体替换 Team 候选；切换默认 Team 必须重新验证。未来 ONES MCP 的调用凭据
必须独立设计，不能反向污染身份绑定模型。

系统不会按昵称、手机号或邮箱自动匹配，也不会在收到未知钉钉用户时自动创建账号。
企业未验证、Corp ID 不一致、候选不可信、身份冲突、已解绑或已停用时，在创建
session/job 和发布队列消息前 fail closed。

停用用户会立即阻止 Web 与钉钉新请求并撤销相关 Web session。停用或解绑外部身份会阻止该钉钉身份继续解析，但不会合并或改写历史 job/session/audit。

### 本人视图与治理视图

“我的外部身份”始终是本人视图：钉钉只读展示昵称、企业、状态、最近使用，并把
Staff ID／Corp ID 收纳在展开区；ONES 展示用户名称、综合可用状态、默认 Team、
最近验证和最近成功使用。用户只能在这里验证自己的 ONES 密码和默认 Team。

“人员管理 → 人员详情”始终是治理视图，即使管理员查看自己：管理员从受信候选绑定
钉钉、停用或软解绑身份；可查看身份 Revision、绑定确认和按应用名称汇总的观察，
以及 ONES 身份状态、已验证 Team、默认 Team、验证时间和安全错误码。页面和
API 均不返回 Connector ID、Token、密码、密文、认证 Header、Client Secret、
Session Webhook 或 Challenge 内部字段。

## 权限模型

授权计算展开用户的所有启用角色，并按管理后台能力、业务应用访问、MCP Tool identifier 和明确数据范围求交集。用户、角色、membership、应用授权或外部身份停用时立即失效。

主要管理资源包括：

- `user:manage`、`role:manage`、`identity:manage`
- `agent:edit`、`agent:publish`、`agent:use`
- 业务应用内精确 MCP Tool identifier 使用权
- `platform_config:read/manage`
- `secret:read/manage`
- `audit:read`
- environment / base / workshop 明确数据范围

Agent 最终可用工具是以下集合的交集：代码 MCP Manifest、Agent Publication Envelope、Application Publication 显式子集、角色的应用内 Tool 授权、当前数据范围和已发布 Resource Revision。Web 管理员能给 Agent 分配工具，不代表任意用户都能调用这些工具。

## Web session 安全

- 浏览器只保存高熵 session token 的 HttpOnly cookie；数据库只保存 token hash。
- session 同时受 idle expiry 和 absolute expiry 限制，支持用户自助或管理员按设备撤销。
- 写请求要求可信 Origin 和 CSRF cookie/header 双提交。
- 修改密码、停用用户和管理员撤销都会使既有 session 失效。
- 登录失败使用通用错误并有限速，避免用户名枚举。
- API 和审计不得记录密码、hash、cookie、CSRF token、secret 明文或完整钉钉 payload。

出现异常登录时，先停用用户或在用户详情撤销活动 session，再检查安全审计；不要仅依赖浏览器清 cookie。

## Agent 草稿、发布与回滚

管理流程：

1. 编辑业务角色、业务指令、模型、轮次/超时、工具、Skill、Ingress 和 Delivery。
2. 保存草稿，携带 expected revision 防止并发覆盖。
3. 执行服务端校验。未注册/禁用/可写工具、未知模型或 Skill、方向不符的 connector、secret 明文、覆盖平台安全规则的指令都会被拒绝。
4. 确认发布，生成包含 schema version 与 SHA-256 hash 的不可变 snapshot。
5. 新 job 固定使用当时 current publication；worker 不读取“最新草稿”。

回滚只把 current publication 指针移动到已有历史快照，不修改历史 publication，也不改变已创建或重试中的 job。发布历史显示 revision、hash、actor 和时间。

业务指令不能关闭外层只读工具、权限校验、数据范围、无内建 Bash/文件写入等平台安全规则。

## 故障恢复

登录后全部接口返回 401：确认 `FEATURE_WEB_ADMIN=true`，检查 session 是否
idle/absolute 过期、用户是否停用，并确认浏览器访问的是 `admin-web` 同源入口。

写操作返回 403：先检查 Origin/CSRF；若错误码为权限拒绝，再检查用户、角色、membership、显式 deny 和管理 action。不要开启 test identity header 绕过。

写操作返回 409：页面数据 revision 已过期，刷新详情后重新应用变更，不能强制覆盖。

钉钉绑定后仍被拒绝：检查企业是否 `ACTIVE`、消息 Corp ID 是否匹配、来源应用是否
受信、解析字段是否为 `senderStaffId`、身份/用户是否启用，以及项目和工具数据范围。
未知或冲突身份应只形成候选或拒绝审计，且 queue publish 为零。

Agent 无法发布：先查看字段级校验错误；确认模型、工具、Skill、connector 都仍在服务端 catalog 中，且没有明文 secret 或安全覆盖指令。

publication 数据损坏或 hash 不一致时运行时会 fail closed。恢复应选择一个已验证历史 publication 回滚，或从草稿重新校验并发布；不得直接修改 snapshot/hash。PostgreSQL 是事实源，管理端静态资源可以重新构建。

权限异常必须从当前角色成员关系、业务应用访问、MCP Tool 授权和数据范围追踪，不得恢复已退役的 `permission_policy`、`platform_access_grant` 或 shadow-mode 双轨授权。
