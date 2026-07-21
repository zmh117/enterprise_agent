# 管理后台重构迁移基线

本文记录 `refactor-admin-web-ddd-shadcn-mvp` 实施前的真实前端、后端与运行时边界，用于逐页迁移和最终清理验收。记录日期：2026-07-20（Asia/Shanghai）。

## 当前前端入口

| 路由 | 页面 | 当前 capability | 后端入口 | 迁移要求 |
|---|---|---|---|---|
| `/login` | 登录 | 无 | `/api/auth/login`、`/api/auth/me`、`/api/auth/logout` | 保留 Cookie/CSRF、统一失败提示和原路返回 |
| `/admin/users` | 用户与身份 | `users_manage` | `/api/admin/users*`、roles、DingTalk tenants/identities、sessions | 内部用户仍是唯一权限主体 |
| `/admin/roles` | 角色与权限 | `roles_manage` | `/api/admin/roles*`、`/api/admin/permissions` | deny 优先和 revision 语义保持不变 |
| `/admin/agents/default-diagnostic-agent` | 默认诊断 Agent | `agent_edit` | `/api/admin/agents/{code}/*` | 底层多 Agent；MVP 写操作只开放默认 Agent |
| `/admin/webhooks*` | Webhook 管理 | `webhook_read/edit/publish/...` | `/api/admin/webhook-triggers*`、`/api/admin/webhook-events*` | 保留修订、预览、发布、回滚、轮换与事件证据链 |
| `/admin/audit` | 安全审计 | `audit_read` | `/api/admin/audit-events` | 只显示内部 actor 和脱敏摘要 |

当前 `App.tsx`、`layout.tsx`、`auth.tsx` 直接组合路由、权限和页面；`lib/api.ts` 负责 Cookie/CSRF 与基本错误映射；`lib/types.ts` 集中保存全部领域与 DTO 类型；`components/ui.tsx` 是手写组件，不是 shadcn registry 组件。

## 当前构建和运行入口

- 包管理：npm，锁文件为 `frontend/package-lock.json`。
- 开发：`npm run dev`，Vite `127.0.0.1:5173`，`/api` 代理到 `127.0.0.1:8000`。
- 构建：`npm run build`，执行 `tsc -b && vite build`。
- 容器：`frontend/Dockerfile` 使用 Node 22、`npm ci`、Nginx，并由 Compose 服务 `admin-web` 暴露 `8080`。
- 2026-07-20 基线：5 个 Vitest 测试通过，ESLint 通过，生产构建通过；产物 JS 327.27 kB（gzip 101.44 kB），CSS 15.82 kB（gzip 4.16 kB）。
- Compose 配置校验通过，`admin-web`、`api-server`、`agent-worker`、`attachment-worker`、`webhook-worker`、`dingtalk-stream-ingress`、`internal-api-platform`、PostgreSQL、RabbitMQ 和 MinIO 均处于运行状态。

## 已有后端能力与本变更边界

### 统一身份与授权

- `/api/auth/*` 和 `/api/admin/users|roles|permissions|audit-events|dingtalk-tenants|identity-conflicts` 已落地。
- 钉钉外部身份只映射到内部 `app_user`；Web 与钉钉必须共享角色和平台访问范围。
- 新后台只能增加 capability 裁剪和管理查询，不得复制主体或创建平行权限系统。

### Agent 配置

- `/api/admin/agents/{agent_code}` 已支持草稿、校验、发布、回滚、发布历史和有效配置。
- 运行中 Job 固定 publication snapshot；前端重构不得改变或重新选择重试 Job 的 Agent 版本。
- 新 Skill Catalog 只读展示服务端已加载 Skill，Web 不编辑 Skill 文件。

### Webhook

- Managed Webhook 已支持 definition、revision、无副作用 preview、publication、rollback、public ID 轮换、服务账号和事件详情。
- Connector 表达通信与凭据，Trigger 表达业务映射和发布；二者不得在新页面合并。
- 外部 payload 不能选择 Agent、工具或任意 delivery target。

### 连续会话与附件

- Session、Message、Attachment 和对象存储链路已落地，附件凭证和对象存储凭据不得进入管理 API。
- 本变更只增加只读浏览；不得恢复暂停中的 DOCX/XLSX/PPTX/Markdown 提取链路。

### 重试与失败投递

- Job 状态包括 `WAITING_INPUT`、`PENDING`、`RUNNING`、`RETRY_WAIT`、`SUCCEEDED`、`FAILED`、`TIMEOUT`。
- 重试保持原内部请求人、Agent publication、会话和 reply route；中间重试不发送失败通知。
- 新运维页面只能查看主队列、延迟重试、死信和 Delivery 证据，不开放 purge、delete、publish 或 replay。

## 工作树与迁移策略

实施前工作树无未提交修改。OpenSpec 产出物已经跟踪，因此后续每次迁移仍需在编辑前重新检查工作树，遇到与用户修改重叠时停止并单独处理。

采用以下切换策略：

1. 旧前端保留为行为参照，先在暂存目录生成 shadcn monorepo。
2. 新应用按 identity/authorization、Agent、Webhook、catalog、operations 顺序迁移。
3. 每个页面完成 API、权限、浏览器和窄屏对齐后，才允许删除对应旧页面。
4. 所有页面完成后再切换 Dockerfile/Compose/CI 到 pnpm，并删除 npm lock、旧 `lib/types.ts` 和手写 UI。
5. 新增后端管理查询不改变现有运行时写链路；前端可通过旧镜像独立回滚。

## 回归门槛

- 登录成功、失败、会话恢复、退出和原路返回。
- 用户创建/启停、角色分配、钉钉身份绑定/停用、会话撤销。
- 角色创建/启停、allow/deny 策略和 revision 冲突。
- 默认 Agent 草稿、服务端校验、发布、回滚和工具/Skill/Channel 绑定。
- Webhook 创建、修订、无副作用 preview、发布、回滚、轮换、事件到 Job/Tool/Delivery 证据链。
- 审计只显示脱敏摘要；无 capability 的直接路由和 API 调用均被拒绝。

## Migration 009 回滚

`009_admin_web_read_models.sql` 增加读模型索引和 `integration_connector.revision` 并发控制列。优先保留这些向后兼容对象；如必须完全回退，先停止新版本 Connector 写请求，再删除：`idx_agent_job_created_status`、`idx_agent_job_project_created`、`idx_agent_job_session_created`、`idx_agent_job_source_created`、`idx_agent_session_updated`、`idx_agent_session_requester_updated`、`idx_agent_message_session_created`、`idx_message_attachment_created`、`idx_delivery_attempt_created_status`、`idx_integration_connector_type_enabled`，最后执行 `ALTER TABLE integration_connector DROP COLUMN revision`。不得删除或更新任何 Job、Session、Message、Attachment、Delivery 数据。

回滚演练应在隔离 schema 或临时数据库执行：先建立只含必要列和哨兵行的影子表，应用 migration 009，执行上述逆向 DDL，确认哨兵行仍存在，再整体回滚事务。禁止直接在运行库演练破坏性 DDL。

2026-07-20 已在运行 PostgreSQL 内的隔离事务和临时 schema `admin_web_rollback_drill` 完成一次演练：应用后检测到 10 个索引和 1 个 revision 列；逆向后索引与 revision 列均为 0，哨兵 Job 行仍为 1；最终 `ROLLBACK` 后临时 schema 数量为 0。演练未修改运行表、Job、Session 或消息。
