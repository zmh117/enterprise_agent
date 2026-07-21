# Admin Web MVP

管理端采用 pnpm workspace 与受控 shadcn/ui 组件，入口位于 `frontend/apps/admin-web`。

## 目录边界

```text
frontend/
  apps/admin-web/               # 路由、会话、管理端页面
    src/app/                    # Providers、错误边界与后台 Shell
    src/contexts/identity/      # 登录、内部用户、钉钉身份与会话
    src/contexts/authorization/ # 角色、权限策略与审计
    src/contexts/agent-management/ # 默认 Agent 草稿与发布
    src/contexts/webhooks/      # Webhook 生命周期与事件证据
    src/contexts/catalog/       # Skill、工具资源、Channel
    src/contexts/operations/    # Dashboard、队列、Job、会话、附件
    src/shared/presentation/    # 基于 shadcn 的跨上下文组合组件
  packages/api-client/          # HTTP、CSRF、correlation id、错误与分页契约
  packages/ui/                  # 无业务依赖的 shadcn/ui 组件和主题
  packages/config/              # 共享 TypeScript 配置
```

新页面按 `domain -> application -> infrastructure -> presentation` 依赖方向组织。共享 UI 不得引用业务 context，presentation 不得直接依赖裸 HTTP DTO。

## 本地开发与验证

需要 Node.js 22 与 pnpm 11.9.0：

```bash
cd frontend
corepack enable
pnpm install --frozen-lockfile
pnpm dev
```

完整前端检查：

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

容器验证：

```bash
docker compose build admin-web
docker compose up -d postgres rabbitmq api-server admin-web
```

## MVP 权限与安全边界

- 页面可见性只改善交互；所有读写权限与租户/项目/环境/基地/车间范围仍由服务端校验。
- Web 只允许编辑和发布 `default-diagnostic-agent`；底层继续按多 Agent definition/revision/publication 建模。
- Skill Catalog 只读，不提供上传、编辑或删除 Skill 文件。
- API 工具只接受 registry 中的 database、Redis、Loki 类型；数据库只显示 PostgreSQL、MySQL、SQL Server，不显示 Oracle。
- 连接测试必须由用户显式触发，只执行 `SELECT 1`、`PING` 或 `GET /ready`，并使用短超时、目标 allowlist、脱敏错误和审计。
- Secret 只在写入接口接收明文，资源与 Connector 只保存并展示 `env:`、`secret://`、`vault:` 或 `kms:` 引用。
- 工具和 Channel 表单可以选择已有受控 Secret，或创建 encrypted-db Secret；创建提交后前端立即清空明文状态，后续只保留 `secret://...` 引用。
- Channel 只开放已实现的钉钉 Stream、Callback、Enterprise Delivery 与 Webhook Delivery；邮件和企业微信显示 unavailable 且不可创建。
- 队列、会话、附件、Job/Delivery 页面只读。队列页不提供 purge/delete/publish/replay，附件读取不会启动 DOCX/XLSX/PPTX/Markdown 提取。

## 数据库迁移与回滚

迁移 `009_admin_web_read_models.sql` 只增加管理查询索引和 `integration_connector.revision`。发布顺序：先迁移数据库，再部署 API，最后部署 Web。

回滚时先回退 Web 镜像，再回退 API。新增索引和 `integration_connector.revision` 字段可保留，不影响旧服务；如果必须删除，先确认没有新版本实例和 Connector 写请求，再按 [admin-web-migration-baseline.md](admin-web-migration-baseline.md) 的逆向 SQL 执行。回滚不得清理 Agent Job、Session、Message、Delivery 或 RabbitMQ 消息。
