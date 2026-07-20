## Why

现有 Web 管理界面采用扁平页面目录和自定义基础组件，业务模型、HTTP DTO、状态查询与展示逻辑相互混杂，既没有形成清晰的前端领域边界，也无法稳定承载用户、Agent、工具、Channel、Webhook、队列、会话和附件等持续扩展的管理需求。需要先建立基于 shadcn/ui、pnpm monorepo 和前端 DDD 边界的管理后台 MVP，并同步补齐页面真实运行所需的后端只读投影与受控管理 API。

## What Changes

- 将现有前端重构为位于 `frontend/` 内的 pnpm monorepo，使用指定的 shadcn CLI preset、Vite、共享 UI package 和统一构建配置；迁移期间保持登录和现有管理能力可回归验证。
- 按 bounded context 组织前端代码，每个上下文区分 domain、application、infrastructure、presentation；移除全局巨型类型文件和页面直接拼装 HTTP 请求的方式。
- 建立统一后台 Shell、响应式侧边导航、面包屑、错误边界、鉴权 Provider、Capability Gate、查询缓存和通用数据表/表单模式。
- 新增 Dashboard，展示用户、默认 Agent、任务状态、队列积压、Delivery 失败、Webhook 事件和最近会话的聚合只读视图。
- 提供用户与钉钉身份、授权、默认诊断 Agent、Skill 分配、数据库/Redis/Loki 只读工具资源、钉钉 Channel、Webhook 的真实管理页面。
- 提供队列、历史会话和附件的只读运维页面；MVP 不开放队列清空/重放、不允许在 Web 编辑 Skill 文件、不允许修改历史消息或附件内容。
- API 工具管理仅覆盖类型化的数据库、Redis、Loki 只读资源、Secret 引用和受审计的连接测试；不提供任意 HTTP URL、脚本、Shell 或动态可执行工具创建能力。
- Channel 模型保留邮件、企业微信等 Provider 扩展点，但 MVP 仅实现钉钉 Stream、Callback 和 Delivery Connector，界面不展示不可用的伪配置。
- 增加管理后台所需的 Dashboard、Skill Catalog、工具资源、Channel、队列、会话与附件 API，并统一分页、过滤、错误响应、权限检查和敏感字段脱敏。
- 更新前端容器构建、锁文件、CI 检查和测试基线，从 npm 单包构建迁移为可复现的 pnpm workspace 构建。

## Capabilities

### New Capabilities

- `admin-web-workbench`: 管理后台 pnpm monorepo、shadcn/ui 设计系统、前端 DDD 边界、路由导航、鉴权和通用交互规范。
- `admin-dashboard-read-model`: Dashboard 聚合指标、最近事件、健康状态和权限裁剪后的只读查询能力。
- `admin-catalog-management`: 默认 Agent、Skill、类型化 API 工具资源和钉钉 Channel 的后台管理体验及其 MVP 写入边界。
- `admin-operations-browser`: 队列、历史会话、消息、任务、Delivery、Webhook 事件和附件的分页检索、详情及只读运维能力。

### Modified Capabilities

- `platform-access-control`: 管理后台页面、操作和数据范围必须复用统一用户身份与 RBAC 权限，并支持前端 Capability Gate 和后端强制授权。
- `platform-config-api`: 增加适合 Web 管理的数据库、Redis、Loki 类型化资源查询、编辑、Secret 引用和受审计连接测试契约。
- `channel-connector-configuration`: 增加钉钉 Stream、Callback、Delivery Connector 的 Web 管理契约，并保持 Provider 可扩展性和密钥脱敏。
- `agent-job-debug-api`: 增加面向运维后台的任务列表、筛选、状态汇总和关联会话/Delivery 查询，同时保持只读诊断边界。

## Impact

- 前端：`frontend/` 目录布局、包管理器、构建脚本、Dockerfile、路由、页面、API Client、类型组织、测试和样式全部受影响。
- 后端：管理 API 路由、应用查询服务、仓储查询、DTO、权限策略、审计事件和聚合只读模型需要扩展；不改变 Agent 运行时的只读诊断边界。
- 数据：优先复用现有用户/RBAC、Agent、Connector、配置、Webhook、Session、Message、Attachment、Job、Delivery 与审计表；仅在缺少稳定查询字段或索引时新增迁移。
- 依赖：引入 pnpm workspace、shadcn/ui、Tailwind CSS、Radix 组件、TanStack Table、React Hook Form 与 Zod，保留 React Router 和 TanStack Query。
- 兼容性：现有登录、默认诊断 Agent、用户/RBAC、Webhook 页面能力必须在新界面完成迁移后才能移除旧实现；已发布配置和运行中的 Agent Job 不受前端重构影响。
- 关联变更：需要兼容 `add-unified-user-identity-and-rbac`、`add-web-managed-webhook-agent-triggers`、`add-continuous-dingtalk-multimodal-conversations` 和 `fix-agent-runtime-retry-and-failure-delivery` 已建立或正在收尾的契约。
