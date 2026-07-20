## Context

当前仓库以 Python 后端和单包 Vite React 前端组成。前端使用 npm、扁平 `pages/`、单一 API helper、巨型共享类型文件和手写基础组件，已实现登录、用户、角色、默认 Agent、Webhook 和审计等部分页面，但业务边界、权限裁剪、错误处理、表格/表单模式与组件视觉不一致。后端已具备统一内部用户与钉钉身份、RBAC、底层多 Agent 配置、Webhook 生命周期、平台资源配置、Job/Delivery/审计和连续会话/附件等主要数据基础，但 Dashboard、队列、Skill、会话和附件缺少面向管理后台的稳定查询契约。

本变更横跨前端架构、构建链路、管理 API、权限、Secret 安全和运行观测。实施必须保持默认诊断 Agent 的只读边界，并兼容仍在收尾的统一身份/RBAC、Webhook、连续会话和运行时重试/失败投递变更。DOCX/XLSX/PPTX/Markdown 提取链路继续暂停，附件页面只展示已经存在的元数据和处理结果。

## Goals / Non-Goals

**Goals:**

- 建立可持续扩展的 pnpm monorepo、真实 shadcn/ui 组件基线和前端 DDD 目录约束。
- 交付可运行的后台 MVP，而不是仅包含导航和 mock 数据的空壳页面。
- 让用户、授权、默认 Agent、Skill 分配、类型化只读工具、钉钉 Channel 和 Webhook 能在统一界面管理。
- 让 Dashboard、队列、历史会话、附件、Webhook/Delivery 事件成为受权限保护的只读运维入口。
- 统一分页、筛选、并发控制、错误响应、审计、Secret 脱敏和 capability 发现。
- 保持底层多 Agent、Channel Provider 和工具资源类型可扩展，MVP UI 仅开放已经实现和验证的能力。

**Non-Goals:**

- 不提供任意 HTTP API、脚本、Shell、MCP Server 或写操作工具的动态创建能力。
- 不在 Web 上传、编辑或删除 Skill 文件；仅管理已加载 Skill 与 Agent 的绑定。
- 不提供 RabbitMQ purge/delete/publish/replay，不修改或删除历史会话、消息、任务和附件。
- 不实现邮件、企业微信 Channel，不展示能够保存但运行时不可用的配置。
- 不恢复或扩展暂停中的 Office/Markdown 文本提取链路。
- 不把第一版 UI 扩展为任意多 Agent 编辑器；后端模型继续支持多 Agent，写操作仅开放默认诊断 Agent。

## Decisions

### 1. 在 `frontend/` 内建立独立 pnpm monorepo

目标结构为：

```text
frontend/
├── apps/admin-web/
├── packages/ui/
├── packages/api-client/
├── packages/config/
├── pnpm-workspace.yaml
└── turbo.json
```

使用用户指定的 `pnpm dlx shadcn@latest init --preset b0 --template vite --monorepo --pointer`，但先在独立暂存目录生成。生成前执行 preset decode/校验；若 `b0` 在当前 CLI 中不可解析则停止，不静默替换。审查生成结果后迁移到 `frontend/`，再逐页迁移现有能力。

选择前端内 monorepo而不是仓库根 monorepo，是为了不让 Node workspace 接管 Python 后端的根构建和依赖边界。选择暂存生成而不是原地 `--force`，是为了避免覆盖用户已有页面和未提交修改。

### 2. shadcn 只承担设计系统，不承担领域组织

`packages/ui` 保存 Button、Card、Dialog、Form、Table、Sidebar、Breadcrumb、Tabs、Badge、Sheet、Sonner、Skeleton、Chart 等通用组件、样式和无业务 hook。它不得导入业务 DTO、权限编码或 API Client。

`apps/admin-web/src/contexts/*` 按业务上下文组织：

```text
context/
├── domain/          # 实体、值对象、只包含业务语义的类型
├── application/     # 查询/命令用例、port、表单模型
├── infrastructure/  # HTTP DTO、repository、mapper、query keys
└── presentation/    # routes、pages、features、widgets
```

`app/` 仅负责路由、Provider、Shell、导航和跨上下文组合；`shared/` 负责 auth、HTTP transport、错误模型、测试和配置。禁止重新产生全局 `lib/types.ts`，并用 lint/import boundary 测试约束依赖方向。

替代方案是仅将现有 CSS 替换为 shadcn 组件，但这无法解决页面直接依赖 DTO、目录随业务增长失控的问题，因此不采用。

### 3. 管理后台采用查询/命令分离的后端契约

Dashboard、队列、会话、附件、Job 搜索属于跨聚合管理读模型，由独立 application query service 组合现有仓储和安全适配器，不把 Dashboard 定义为领域聚合，也不让前端并行调用十几个内部接口自行拼指标。

写操作继续进入现有领域服务：用户/RBAC、Agent draft/publish、Webhook lifecycle、platform config、Connector config。新 API 只做 transport 和权限适配，不绕过已有不变量、revision、审计与 Secret 管理。

统一管理 API 契约：

- 列表默认使用受限时间窗口、稳定排序和 cursor 或稳定分页结构。
- 写操作携带 revision/ETag 等并发令牌，冲突返回 409。
- 错误返回稳定 error code、用户安全摘要、field errors 和 correlation id。
- DTO 与 domain model 之间必须显式 mapper，避免数据库字段直接成为前端契约。

### 4. 权限采用“服务端强制 + 前端裁剪”双层模型

登录响应或 `/api/admin/capabilities` 返回当前内部用户的模块、动作和数据范围摘要。前端 Capability Gate 控制导航、按钮和查询启用状态，仅改善体验；所有 API 独立调用统一授权服务，服务端决定最终允许/拒绝。

用户的 Web 凭据和钉钉外部身份都映射到同一 `app_user`，角色与平台资源授权不复制到外部身份表。Dashboard 计数和列表都必须先应用相同范围过滤，防止通过数量、错误或分页元数据推断无权资源。

### 5. MVP 功能按风险分级开放

| 模块 | MVP 写入边界 |
|---|---|
| 用户与授权 | 复用现有受审计 CRUD、钉钉绑定、会话撤销 |
| 默认诊断 Agent | 草稿、校验、发布、回滚、绑定 |
| Skill | Catalog 只读；允许分配已加载 Skill，不编辑文件 |
| API 工具 | 类型化 database/redis/loki 资源、Secret ref、显式连接测试 |
| Channel | 钉钉 Stream/Callback/Delivery Connector 管理和校验 |
| Webhook | 复用 revision/publish/disable 和事件查看 |
| 队列 | 只读状态，不做队列或消息写操作 |
| 会话/附件/审计 | 只读、脱敏、范围过滤 |

这一边界比“每页都做 CRUD”更符合现有只读 Agent 安全模型，也保留未来分别设计 Skill 发布、消息重放、附件下载和动态 HTTP 工具的空间。

### 6. 工具资源使用注册表与类型化 schema

后端 Resource Provider Registry 声明 `database`、`redis`、`loki` 的配置 schema、允许字段、连接测试器、只读探测和运行时支持状态。数据库可以再通过 dialect 区分 PostgreSQL、MySQL、SQL Server 等当前已支持类型；Oracle 是否显示由运行时 registry 决定，不能因存在旧枚举就默认可用。

Web 表单由 API 返回的受控 schema 或本地对应 presentation schema 驱动，但提交仍由后端校验。连接测试只能引用已保存 Secret，采用短超时、目标 allowlist、最小只读命令和审计，不在 Dashboard 隐式执行，也不回传连接串或上游原文。

### 7. Channel 使用 Provider Catalog，配置与运行能力一致

Channel Provider Catalog 返回 provider code、允许 ingress/delivery 方向、配置 schema、`available` 状态和所需 Secret 类型。MVP 只把钉钉 Stream、Callback 和 Delivery Provider 标为 available；邮件、企业微信保留扩展代码或文档但不可创建。

Connector 负责通信方式、凭据引用和方向；Webhook Trigger 继续负责业务映射、发布和入口行为，两者不合并。普通 Connector 校验只验证字段、Secret ref 和 endpoint allowlist，不发送测试消息；测试发送若未来需要，必须作为独立、显式、限流、受审计能力提出。

### 8. Dashboard 和队列状态采用可降级聚合

Dashboard 聚合数据库中的用户、Agent、Job、Delivery、Webhook、会话状态，并通过受限 RabbitMQ management adapter 读取队列指标。每个区域带 `generated_at`、统计窗口和 availability；RabbitMQ 不可用时只降级队列区域，不能拖垮整个 Dashboard。

Dashboard 刷新不解析业务资源 Secret，也不主动连接数据库、Redis、Loki 或钉钉。外部资源健康由显式连接测试或后续独立健康采集任务更新。

### 9. 前端迁移采用并行骨架、逐页切换而非一次性删除

先为当前登录、用户、角色、Agent、Webhook、审计建立 API/浏览器回归基线；创建新 workspace 和 Shell 后，按 identity/authorization、Agent、Webhook、catalog、operations 顺序迁移。旧页面在对应新流程通过测试前保留，最终切换 Docker/CI 到 pnpm workspace，再删除 npm lock 和手写 UI。

API 尽量向后兼容；新增管理查询接口不会影响运行时入口。若前端发布失败，可回滚至旧 frontend 镜像；若后端新查询接口失败，可回滚 API 而不回滚业务数据。新迁移必须以可逆索引和可空字段为主，避免破坏运行中的 Job 与会话。

### 10. 验证覆盖架构、权限、安全和真实页面

- domain/application 单元测试：mapper、状态显示、scope、表单模型。
- 后端契约测试：分页、范围过滤、并发冲突、Secret 脱敏、显式连接测试。
- 前端集成测试：路由、Capability Gate、加载/错误/空状态、表单提交。
- 浏览器 E2E：登录，用户/钉钉绑定，授权，默认 Agent 发布，Skill 分配，资源和 Channel 配置，Webhook 生命周期，以及只读队列/会话/附件。
- 构建验证：pnpm frozen lockfile、lint、typecheck、test、production build、Docker Compose build/health。
- 视觉与可访问性：桌面和窄屏侧栏、键盘焦点、Dialog/Sheet、表格溢出、表单错误、颜色对比和无障碍名称。

## Risks / Trade-offs

- [前后端范围同时扩大，MVP 工期增加] → 先完成 Shell 与契约骨架，再按风险分批交付，但每批必须包含真实 API 和验证，禁止只交付 mock 页面。
- [shadcn latest 或 `b0` preset 变化导致生成结果漂移] → 实施时记录 CLI 版本、decode preset、提交生成配置和 lockfile；无法解析时停止并请求确认。
- [重构期间旧新前端行为分叉] → 建立关键流程回归矩阵和逐页切换门槛，切换后立即删除重复路径。
- [DDD 分层被过度模板化] → 只为有业务语义的上下文建立完整层次；简单展示组件保留在 presentation，不为每个按钮创建领域对象。
- [Dashboard 聚合查询影响主库] → 限定默认窗口和页大小、补充必要索引、为聚合设置超时；规模增长后再引入预聚合，不在 MVP 引入新中间件。
- [RabbitMQ 管理接口不可用或暴露过多] → 使用最小权限只读凭据和队列 allowlist，区域级降级，不返回消息正文。
- [连接测试成为 SSRF 或凭据泄漏入口] → 仅测试已保存类型化资源，后端 allowlist、短超时、只读探测、审计和脱敏，禁止请求临时 URL/凭据。
- [历史会话和附件暴露敏感数据] → 服务端范围过滤、内容大小限制、敏感字段脱敏、对象 URL 不持久暴露，MVP 不提供批量导出。

## Migration Plan

1. 记录现有前端路由、权限、API、关键流程和 Docker 构建回归基线。
2. 在暂存目录校验 `b0` preset 并使用指定命令生成 shadcn monorepo，固定 pnpm/CLI/lockfile。
3. 将生成骨架整理为 `frontend/apps/admin-web` 与共享 packages，建立 import boundary 和 CI。
4. 建立统一 API Client、auth/capability、Shell、错误模型和 DDD 上下文模板。
5. 补齐 Dashboard、Catalog、Operations、Job 搜索和 Connector/Resource 管理 API 及后端测试。
6. 迁移身份/授权、默认 Agent、Webhook 等现有页面，完成行为对齐。
7. 实现 Skill、工具资源、Channel、Dashboard、队列、会话和附件页面。
8. 执行单元、集成、浏览器、权限/脱敏、生产构建和 Docker Compose 验证。
9. 切换容器和文档至 pnpm workspace，删除旧 npm lock、旧页面和手写 UI；保留可回滚的前端镜像与后端兼容 API。

## Open Questions

无。MVP 默认采用 proposal 中的范围：API 工具只管理 database/redis/loki 类型化只读资源；Skill、队列、会话和附件遵循上述受控只读边界；monorepo 限定在 `frontend/` 内。
