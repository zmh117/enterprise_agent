# Admin Web 当前实现

Admin Web 是单一 Vite + React + TypeScript 应用，代码位于 `frontend/src/`。仓库使用
`frontend/package.json` 与 `frontend/package-lock.json`，没有 pnpm workspace、
`frontend/apps/admin-web` 或独立共享 package。

## 目录边界

```text
frontend/src/
  app/                         # Providers、路由、错误边界与后台 Shell
  contexts/
    agent-profiles/            # Python Agent 与模型连接
    applications/              # Business Application 与受管渠道
    auth/                      # 登录、当前 Session 与能力门禁
    authorization/             # 角色、成员、应用/工具/数据范围授权
    dingtalk-identity-discovery/
    external-identities/       # 本人外部身份
    operations/                # Job、会话、文件与运行状态
    overview/
    platform-governance/       # Tool Manifest、Resource、Secret、Runtime Config
    users/
    workflows/
  shared/api/                  # HTTP、CSRF、correlation id 与错误契约
  shared/presentation/         # 跨领域展示组件
  components/ui/               # shadcn/ui 组件
```

前端会通过同源 `/api` 调用后端，不是静态 Mock-only 原型。页面可见性只改善交互；
服务端 Session、RBAC、CSRF、revision 和字段校验仍是授权事实。

## 本地开发与验证

容器构建使用 Node.js 22 和 npm：

```bash
cd frontend
npm ci
npm run dev
```

完整前端检查：

```bash
npm run lint
npm run typecheck
npm run test
npm run build
```

Compose 中 `admin-web` 属于默认服务集合，但镜像入口要求显式开启功能：

```bash
FEATURE_WEB_ADMIN=true docker compose up -d --build \
  postgres rabbitmq migrator api-server admin-web
```

仓库当前没有 `admin` Compose profile。`FEATURE_WEB_ADMIN=false` 时，API 不注册管理
路由，`admin-web` 容器入口也会退出；显式点名服务不能绕过该开关。

## 当前管理边界

- 可以创建和治理多个 `python-v1` Agent；`default-diagnostic-agent` 只是 bootstrap
  内置 Agent，不是唯一可管理 Agent。历史 `typescript-v1` 事实只读。
- Agent、Workflow、Business Application、Resource 和 Webhook 使用追加式 Revision 与
  不可变 Publication；前端必须携带 expected revision，不能覆盖历史快照。
- 工具目录来自代码 MCP Manifest，只读展示；不提供动态 Handler、Release、任意 MCP
  Server 或任意 URL/脚本实现。
- DB、Redis、Loki Resource 在同一 Draft 中配置连接、数据范围与
  `secret://platform/<code>`，再执行验证和发布。Oracle 已有代码 Provider；是否可用
  由驱动和 Resource 验证结果决定，不应从 UI 文档中宣称全局禁用。
- 新 Secret 绑定只接受 `secret://platform/<code>`。`env:` 需要先显式导入，
  `vault:` / `kms:` 当前未实现并会被拒绝。
- 渠道包含受管钉钉企业/应用连接和 Webhook；队列、Job、Delivery、文件处理与审计页面
  主要用于治理和只读诊断，不提供无界 purge、任意 replay 或直接数据库写入。
- 文档处理状态来自 File Service、RabbitMQ 与 Docling readiness；读取文件运维页不会
  隐式启动新的解析任务。

## 部署与验收

数据库 schema 由 `migrator` 统一推进，Admin Web 没有独立的当前迁移。发布时先运行
migrator，再更新 API 和 Web。回退前端镜像不会回退 schema，也不能删除 Job、Session、
File、Delivery 或审计事实。

容器可访问只证明静态资源和代理启动。业务验收至少还要覆盖登录/CSRF、一个受授权读
请求、一个带 revision 的治理写请求，以及对应数据库与审计事实。
