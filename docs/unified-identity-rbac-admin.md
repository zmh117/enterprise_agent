# 统一身份、RBAC 与 Agent 管理端

该能力把 Web 管理员和钉钉用户统一映射为内部 `app_user`。权限只授予内部用户或角色，钉钉 `senderStaffId` 只是受信 tenant/connector 下的外部身份键，不能直接充当授权主体。

第一版 Web 只显示 `default-diagnostic-agent`，但数据库、服务和运行时使用多 Agent 的 definition、draft revision、immutable publication 模型。新 job 在创建时固定 publication ID、revision 和 hash，后续发布或回滚不会改变已经创建的 job。

## 功能开关与启动

本地 HTTP 验收可在 `.env` 中设置：

```env
FEATURE_UNIFIED_IDENTITY=true
FEATURE_WEB_ADMIN=true
FEATURE_PUBLISHED_AGENT_RUNTIME=true
FEATURE_TEST_IDENTITY_HEADERS=false
FEATURE_PERMISSION_SHADOW_MODE=true
WEB_COOKIE_SECURE=false
WEB_ALLOWED_ORIGINS=http://localhost:8080,http://127.0.0.1:8080
ADMIN_WEB_PORT=8080
DINGTALK_TENANT_CODE=default
DEFAULT_AGENT_CODE=default-diagnostic-agent
```

生产必须使用 HTTPS，并把 `WEB_COOKIE_SECURE` 设为 `true`。`WEB_ALLOWED_ORIGINS` 只配置明确可信的 Origin，不使用通配符。生产不得启用 `FEATURE_TEST_IDENTITY_HEADERS`。

启动管理端与 API：

```bash
docker compose up -d --build postgres rabbitmq api-server admin-web
```

访问 `http://localhost:8080`。`admin-web` 由 Nginx 提供静态资源，并把同源 `/api` 代理到 `api-server`。Compose 本地 seed 的账号仅用于开发：`local-user` / `local-admin-change-me`；首次登录后应立即修改密码。生产 migration 不创建默认密码。

## 首个管理员 bootstrap

生产或没有本地 seed 的环境使用交互式 CLI 创建首个管理员，密码不会出现在命令参数、shell history 或日志中：

```bash
docker compose exec api-server \
  python -m app.cli.bootstrap_admin \
  --username platform-admin \
  --display-name "平台管理员"
```

CLI 要求至少 12 位密码、二次确认，并拒绝重复 bootstrap。管理员创建后再开启对外管理入口。

## 用户、角色和钉钉绑定

推荐顺序：

1. 在“用户与身份”创建内部用户。
2. 在“角色与权限”创建职责角色并配置策略。
3. 回到用户详情分配角色。
4. 选择受信钉钉 tenant/connector，手工录入该用户的 `senderStaffId`。
5. 让用户从钉钉发送一条测试消息，确认审计中的内部 requester、external identity 与工具范围。

系统不会按昵称、手机号或邮箱自动匹配，也不会在收到未知钉钉用户时自动创建账号。`provider + tenant_code + external_subject_id` 唯一；冲突、未知、已解绑或已停用身份在创建 session/job 和发布队列消息前 fail closed。

停用用户会立即阻止 Web 与钉钉新请求并撤销相关 Web session。停用或解绑外部身份会阻止该钉钉身份继续解析，但不会合并或改写历史 job/session/audit。

## 权限模型

授权计算展开用户直接策略和所有启用角色，支持资源、resource code、action 与通配符。任何命中的显式 `deny` 优先于 `allow`；用户、角色、membership 或外部身份停用时立即失效。

主要管理资源包括：

- `user:manage`、`role:manage`、`identity:manage`
- `agent:edit`、`agent:publish`、`agent:use`
- `tool:use`
- `platform_config:read/manage`
- `secret:read/manage`
- `audit:read`
- `project:<code>` 与 platform access grant 数据范围

Agent 最终可用工具是以下集合的交集：代码注册且启用、publication 已分配、用户/角色允许、平台数据范围允许。Web 管理员能给 Agent 分配工具，不代表任意用户都能调用这些工具。

迁移旧主体时先只生成对账报告：

```bash
docker compose exec api-server python -m app.cli.reconcile_legacy_identities
```

人工确认报告中没有歧义后才应用：

```bash
docker compose exec api-server python -m app.cli.reconcile_legacy_identities --apply
```

只有 tenant 可唯一确认的旧 policy/grant 会迁移；未匹配和歧义项必须人工处理。

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

登录后全部接口返回 401：确认 `FEATURE_UNIFIED_IDENTITY` 与 `FEATURE_WEB_ADMIN` 在 `api-server` 中同时开启，检查 session 是否 idle/absolute 过期、用户是否停用，并确认浏览器访问的是 `admin-web` 同源入口。

写操作返回 403：先检查 Origin/CSRF；若错误码为权限拒绝，再检查用户、角色、membership、显式 deny 和管理 action。不要开启 test identity header 绕过。

写操作返回 409：页面数据 revision 已过期，刷新详情后重新应用变更，不能强制覆盖。

钉钉绑定后仍被拒绝：检查 connector 是否受信、tenant 是否一致、解析字段是否为 `senderStaffId`、身份/用户是否启用，以及项目和工具数据范围。未知或冲突身份应在审计中有拒绝事件且 queue publish 为零。

Agent 无法发布：先查看字段级校验错误；确认模型、工具、Skill、connector 都仍在服务端 catalog 中，且没有明文 secret 或安全覆盖指令。

publication 数据损坏或 hash 不一致时运行时会 fail closed。恢复应选择一个已验证历史 publication 回滚，或从草稿重新校验并发布；不得直接修改 snapshot/hash。PostgreSQL 是事实源，管理端静态资源可以重新构建。

切换统一 RBAC 前保持 `FEATURE_PERMISSION_SHADOW_MODE=true`，观察旧/新决策差异并完成旧主体对账；验证一致后再按部署窗口切换，避免把 shadow 结果误当作真正授权。
