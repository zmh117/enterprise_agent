## 实施基线

记录时间：2026-07-26（Asia/Shanghai）

### 代码契约

- 身份与角色事实：`app_user`、`user_external_identity`、`rbac_role`、`rbac_user_role`。
- 旧授权事实：`permission_policy`、`platform_access_grant`，继续作为兼容与高级例外读取。
- 业务应用上下文已经稳定持久化到 `agent_session` 和 `agent_job`，包括 application、publication、deployment、route 和 config hash。
- 现有角色 API 允许列表、详情、创建、更新、成员分配和原始权限写入；新页面改用分区 typed API，旧原始权限 API 仅用于兼容。
- 当前 principal 通过 `AdminCapabilityService` 计算能力摘要；现有能力目录字段不足，将扩展为中文名称、风险、依赖和资源范围。
- 前端导航当前为静态配置；人员详情只显示基本资料与外部身份；钉钉候选绑定 DTO 尚不支持初始角色。
- 授权模式新增 `BUSINESS_APPLICATION_AUTHORIZATION_MODE`，合法值为 `compatibility` 和 `strict_application_role`，默认 `compatibility`。

### 现场只读数量基线

| 表 | 数量 |
|---|---:|
| `app_user` | 7 |
| `user_external_identity` | 7 |
| `user_session` | 16 |
| `rbac_role` | 2 |
| `rbac_user_role` | 4 |
| `permission_policy` | 54 |
| `platform_access_grant` | 5 |
| `business_application` | 2 |
| `agent_job` | 5 |
| `delivery_attempt` | 5 |
| `audit_event` | 1063 |

本 change 的 migration 和实现不得降低上述旧身份、授权和历史表数量；测试或真实验收产生的新记录可以增加数量。

## 实施与验证结果

记录时间：2026-07-26（Asia/Shanghai）

### 数据库与恢复准备

- 已在 migration 前创建 PostgreSQL custom-format 备份：`/private/tmp/enterprise-agent-auth-backup.3ysZbN/enterprise_agent_before_role_authorization.dump`。
- `pg_restore -l` 可正常读取该备份，共 678 个 TOC 条目。
- migration 已在真实 PostgreSQL 18.4 上完成，并重复通过容器启动执行；新增 4 张角色授权表、7 个角色字段和 3 个成员字段。
- `platform-admin` 已回填为受保护系统角色，说明统一为中文；没有自动增加业务应用访问。

### 自动化验证

- 后端完整测试：396 passed，12 skipped，2 warnings，4 subtests passed。
- 角色授权中心专项测试：14 passed。
- 前端完整测试：10 files，43 passed。
- Ruff：通过。
- TypeScript typecheck：通过。
- ESLint：通过。
- 前端 production build：通过；仅保留既有的 chunk size 提示。
- OpenSpec strict validation：通过。

### 容器验证

- 已重建 `api-server`、`admin-web`、`agent-worker`、`channel-dispatch-worker`、`attachment-worker`、`webhook-worker` 和 `dingtalk-runtime` 镜像，并强制重建对应容器。
- `api-server`、`channel-dispatch-worker`、`webhook-worker`、`dingtalk-runtime`、PostgreSQL、RabbitMQ 均为 healthy；其余 worker 正常运行。
- API 容器内 `/api/health` 返回 200，`admin-web` 静态入口返回 200。
- RabbitMQ consumer 已启动；钉钉 Stream 日志存在 `connect success`，未出现连接错误。
- 运行模式为 `compatibility`。

### 真实浏览器验收

- 使用已有 `platform-admin` 安全会话验证“用户与外部身份 → 角色与授权”菜单和 `/users/roles` 页面可见。
- 创建了 `authorization-browser-e2e-20260726` 验收角色；使用“业务应用只读角色”模板，模板只预填用途和中文说明，没有隐式授权。
- 勾选 `applications.create` 时自动补齐 `applications.read`，并通过分区 revision 原子保存。
- 授权“生产诊断助手”，只选择 `agent_test/mysql` 明确范围并填写高风险变更原因；未使用动态全部。
- 为既有人员账号分配角色并设置到期时间，保存后 membership revision 增加。
- 权限模拟返回允许，来源角色明确为该验收角色。
- 操作记录页面真实发现并修复 PostgreSQL `LIKE` 字面 `%` 与 psycopg 占位符冲突；复验后显示创建、后台能力、业务范围和成员更新 4 条中文安全记录。

### 兼容与严格模式求值

- 真实 PostgreSQL/容器内兼容模式：旧授权用户访问既有应用返回 `allowed=true`、`reason=legacy_compatible`、`legacy_compatible=true`。
- 受控 strict evaluator：验收成员访问授权应用和 `agent_test/mysql` 允许；无角色用户拒绝；跨应用拒绝；`database.write` 被应用能力安全上限拒绝。
- 在真实 PostgreSQL 上临时撤销验收成员后，`worker_start`、`tool_call`、`delivery` 三个阶段均返回 `allowed=false`、`reason=no_application_role`；随后通过同一成员服务恢复角色与原到期时间，成员保持启用。自动化四阶段测试同时证明模型、Internal API Platform 和业务结果投递不会在拒绝后继续执行。

### 历史数据保留结果

| 表 | 变更前 | 验收后 |
|---|---:|---:|
| `app_user` | 7 | 7 |
| `user_external_identity` | 7 | 7 |
| `user_session` | 16 | 16 |
| `rbac_role` | 2 | 3 |
| `rbac_user_role` | 4 | 5 |
| `permission_policy` | 54 | 54 |
| `platform_access_grant` | 5 | 5 |
| `business_application` | 2 | 2 |
| `agent_job` | 5 | 5 |
| `delivery_attempt` | 5 | 5 |
| `audit_event` | 1063 | 1069 |

旧用户、身份、会话、角色成员、旧策略、平台 grant、运行记录和投递记录均未减少。新增角色、成员、4 条浏览器验收审计和 2 条受控撤权/恢复审计来自本次验证。

### 安全检查

- 最近相关容器日志敏感字段模式命中数为 0，fatal/traceback/internal server error 命中数为 0。
- 角色授权审计中 Client Secret、Token、模型 API Key、密码和消息正文模式命中数为 0。
- 页面、字段错误和权限拒绝均使用中文；内部 capability code、reason 和 correlation id 保持稳定英文编码。

### 仍需外部事件才能完成的验收

- 真实钉钉私聊完整链路需要用户发送一条新的私聊消息。
- 真实钉钉群聊完整链路需要用户在已配置群中发送一条新的群聊消息。
- “候选绑定并原子分配初始角色 / 仅绑定”真实验收需要出现一个新的未绑定钉钉候选；当前候选列表为空。
