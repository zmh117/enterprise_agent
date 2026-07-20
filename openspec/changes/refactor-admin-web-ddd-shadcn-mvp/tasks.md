## 1. 现状基线与变更隔离

- [ ] 1.1 盘点现有前端路由、页面、API 调用、权限判断、Docker 构建和运行入口，形成迁移矩阵
- [ ] 1.2 为登录、用户与钉钉绑定、角色授权、默认 Agent、Webhook 和审计建立当前行为回归测试基线
- [ ] 1.3 核对统一身份/RBAC、Webhook、连续会话和 retry/failure delivery 活跃变更的已落地接口，记录本变更复用与不得覆盖的边界
- [ ] 1.4 检查工作树现有用户修改并制定逐文件迁移策略，确保不覆盖无关改动
- [ ] 1.5 记录当前前端 npm 安装、类型检查、生产构建和 Compose 启动结果，作为切换验收基线

## 2. shadcn pnpm monorepo 初始化

- [ ] 2.1 固定实施使用的 pnpm 与 shadcn CLI 版本，并执行 preset decode 验证 `b0`
- [ ] 2.2 在独立暂存目录运行 `pnpm dlx shadcn@latest init --preset b0 --template vite --monorepo --pointer`，验证生成结果且不覆盖现有前端
- [ ] 2.3 将生成骨架整理为 `frontend/apps/admin-web`、`frontend/packages/ui`、`frontend/packages/api-client` 和 `frontend/packages/config`
- [ ] 2.4 配置 `pnpm-workspace.yaml`、Turbo 任务、TypeScript project references、路径别名和锁定的 packageManager 字段
- [ ] 2.5 配置各 workspace 的 `components.json`、Tailwind 样式、主题 token、字体、暗色模式策略和 pointer cursor 行为
- [ ] 2.6 安装并导出 MVP 所需 Sidebar、Breadcrumb、Card、Table、Form、Dialog、AlertDialog、Sheet、Tabs、Badge、DropdownMenu、Tooltip、Command、Skeleton、Sonner、Pagination 和 Chart 组件
- [ ] 2.7 增加 ESLint/import-boundary 规则，禁止共享 UI 依赖业务上下文并禁止 presentation 直接依赖裸 HTTP DTO
- [ ] 2.8 配置 Vitest、Testing Library、MSW 和前端测试公共设施，确保 workspace 测试可独立运行

## 3. 管理 API 公共契约与授权

- [ ] 3.1 定义管理 API 的统一错误模型、field errors、correlation id、稳定分页和时间窗口契约
- [ ] 3.2 定义管理模块及动作 capability 编码，并映射到现有统一身份、角色、权限策略和平台数据范围
- [ ] 3.3 实现当前登录主体的 capability 摘要 API，确保不返回未授权资源或敏感策略内部数据
- [ ] 3.4 为所有新增管理 API 接入服务端 RBAC 和租户/项目/环境/基地/车间范围过滤
- [ ] 3.5 增加 capability 直接调用绕过、范围越权、聚合计数泄漏和拒绝审计测试
- [ ] 3.6 为管理写接口统一 revision/并发冲突行为，并覆盖 409 响应契约测试
- [ ] 3.7 复核新增查询所需数据库索引，只通过可逆迁移增加必要索引或稳定字段

## 4. Dashboard 后端读模型

- [ ] 4.1 定义 Dashboard summary、任务状态、Delivery 失败、队列状态、最近 Webhook 和会话活动 DTO
- [ ] 4.2 实现权限裁剪的用户、启用 Agent、Channel、当日任务和异常事件聚合查询服务
- [ ] 4.3 实现最近 24 小时及受限自定义窗口的 Job、重试、超时、最终失败和 Delivery 失败汇总
- [ ] 4.4 实现最小权限 RabbitMQ 管理只读 adapter、队列 allowlist、超时和脱敏错误映射
- [ ] 4.5 实现 Dashboard 区域级可用性与降级，使 RabbitMQ 不可用时其他指标仍可返回
- [ ] 4.6 提供单一 Dashboard 管理 API，返回统计窗口、generated_at 和有权限的详情引用
- [ ] 4.7 增加 Dashboard 范围过滤、默认窗口、区域降级、无隐式外部连接测试和性能上限测试

## 5. Agent、Skill、工具资源与 Channel 后端

- [ ] 5.1 复核多 Agent 定义/修订/发布接口，并在 MVP 管理写路径强制仅允许默认诊断 Agent
- [ ] 5.2 提供 Agent 列表与详情读模型，明确非默认 Agent 的只读或未开放管理状态
- [ ] 5.3 基于受控 Skill Loader 实现 Skill Catalog 列表/详情 API，返回来源、加载状态和安全错误
- [ ] 5.4 在 Agent 草稿校验和发布时验证 Skill 绑定仍然存在且加载成功，禁止通过 Web 修改 Skill 文件
- [ ] 5.5 建立 database、redis、loki Resource Provider Registry，声明配置 schema、运行时 availability 和只读探测器
- [ ] 5.6 在数据库 Provider 中按实际运行时能力声明 PostgreSQL、MySQL、SQL Server 等 dialect，确保 Oracle 不因旧枚举自动显示为可用
- [ ] 5.7 实现类型化工具资源的分页、详情、创建、更新、启停、绑定和 revision 冲突 API，复用平台 Secret 引用
- [ ] 5.8 实现数据库、Redis、Loki 的显式连接测试应用服务，加入 allowlist、短超时、只读命令、脱敏和审计
- [ ] 5.9 增加未知资源、任意 HTTP、脚本、Shell、写工具、明文凭据和 SSRF 目标的拒绝测试
- [ ] 5.10 建立 Channel Provider Catalog，声明钉钉 Stream、Callback、Delivery 的 schema、方向和 availability
- [ ] 5.11 实现 Connector 分页、详情、创建、更新、启停、Agent 绑定、revision 和 Secret 脱敏管理 API
- [ ] 5.12 实现 Connector 配置校验 API，验证必填字段、Secret ref、方向和 endpoint allowlist 且不发送真实消息
- [ ] 5.13 增加邮件/企业微信 unavailable、Connector 并发冲突、方向违规、Secret 泄漏和审计测试

## 6. 队列、会话、附件与 Job 运维后端

- [ ] 6.1 实现允许队列的 ready、unacked、consumer、重试/死信关系、采集时间和 availability 只读 API
- [ ] 6.2 验证管理 API 不暴露 RabbitMQ purge、delete、publish、message body 或 replay 写入口
- [ ] 6.3 扩展 Job Debug API，支持受限默认时间窗口、稳定分页及按状态、用户、Agent、Channel、项目、会话和 correlation id 筛选
- [ ] 6.4 实现 Job 状态汇总 API，并关联 Session、Message、Steps、Tool Calls、Retry、Webhook Event 和 Delivery 安全摘要
- [ ] 6.5 实现会话列表和详情查询，支持按时间、Channel、内部用户、外部会话标识、Agent 和任务状态筛选
- [ ] 6.6 实现消息、附件、Job、Tool Call 和 Delivery 的稳定顺序与关联引用，限制内容和摘要大小
- [ ] 6.7 实现附件列表和详情查询，支持会话、用户、MIME、时间和处理状态过滤，并隐藏对象存储凭据和永久 URL
- [ ] 6.8 确保附件查询只读取现有元数据/文本预览，不启动或恢复 DOCX/XLSX/PPTX/Markdown 提取任务
- [ ] 6.9 实现 Webhook Event、Job、重试和 Delivery attempt 的关联查询，支持“入口已收但未回复”链路排查
- [ ] 6.10 增加会话/附件越权、只读不可变、raw payload 脱敏、无界查询限制和 RabbitMQ 区域失败测试

## 7. 前端应用基础与统一 Shell

- [ ] 7.1 在 `packages/api-client` 实现统一 transport、认证、correlation id、错误映射、分页和 DTO mapper 基础
- [ ] 7.2 在 admin-web 建立 app providers、React Router、TanStack Query、错误边界、Sonner 和全局加载状态
- [ ] 7.3 实现登录恢复、刷新/失效处理和 capability 查询，确保 Secret 或 token 不写入日志和错误 UI
- [ ] 7.4 实现前端 Capability Gate、受保护路由和无权限页面，并用直接 URL 访问验证交互裁剪
- [ ] 7.5 构建响应式后台 Shell、分组侧边栏、移动端 Sheet、面包屑、页面标题和用户菜单
- [ ] 7.6 配置 Dashboard、用户、授权、Agent、Skill、API 工具、Channel、Webhook、队列、历史对话、附件和审计路由
- [ ] 7.7 实现统一 DataTable、筛选栏、分页、详情 Sheet、确认 Dialog、表单字段、Skeleton、空状态和错误重试模式
- [ ] 7.8 建立各 bounded context 的 domain/application/infrastructure/presentation 目录和可执行依赖边界测试

## 8. 身份、授权、Agent 与 Webhook 页面迁移

- [ ] 8.1 将登录页面迁移至新设计系统并通过成功、失败、会话过期和重定向回归测试
- [ ] 8.2 实现用户列表/详情/启停、Web 凭据状态、钉钉身份绑定和会话撤销页面
- [ ] 8.3 实现授权工作区，管理角色、权限策略、用户角色和平台资源授权，并展示最终内部用户主体
- [ ] 8.4 实现底层多 Agent 列表和默认诊断 Agent 编辑器，迁移草稿、校验、发布、回滚与 revision 状态
- [ ] 8.5 实现默认 Agent 的工具、Skill 和 Channel 绑定 UI，并禁止编辑非默认 Agent
- [ ] 8.6 迁移 Webhook 列表、详情、修订、校验、发布、禁用、Secret 更新和事件查询页面
- [ ] 8.7 迁移审计页面并统一主体、动作、资源、结果、时间和 correlation id 筛选
- [ ] 8.8 对身份、授权、Agent、Webhook、审计执行新旧页面功能对齐检查，满足后再标记旧页面可移除

## 9. Catalog 管理页面

- [ ] 9.1 实现 Skill Catalog 列表、详情、来源、加载状态和失败摘要页面，确认无上传/编辑/删除入口
- [ ] 9.2 实现 API 工具资源列表、类型/作用域筛选、详情、创建、编辑、启停和 revision 冲突处理
- [ ] 9.3 实现 database、redis、loki 类型化表单，只展示 Provider Registry 声明为 available 的字段和 dialect
- [ ] 9.4 实现 Secret 引用选择/创建流程，保证明文值仅存在于 write-only 表单提交且提交后立即清除
- [ ] 9.5 实现显式连接测试交互，展示耗时、结果、脱敏错误和 correlation id，不在页面加载时自动测试
- [ ] 9.6 实现 Channel 列表、详情、钉钉 Provider 表单、方向、Secret ref、endpoint allowlist、启停和 revision 冲突处理
- [ ] 9.7 实现 Connector 配置校验交互，并确保邮件、企业微信等 unavailable Provider 不可创建

## 10. Dashboard 与只读运维页面

- [ ] 10.1 实现 Dashboard 汇总卡片、任务状态图、Delivery 失败、队列状态和最近事件组件
- [ ] 10.2 实现 Dashboard 时间窗口、区域降级、generated_at 和有权限详情跳转
- [ ] 10.3 实现队列只读页面，展示队列用途、ready/unacked、消费者及重试/死信关系且无破坏性操作
- [ ] 10.4 实现历史会话列表、筛选和详情时间线，关联消息、附件、Job、工具调用和 Delivery
- [ ] 10.5 实现附件列表和详情，展示安全元数据、处理状态及已有文本预览且不提供永久对象 URL
- [ ] 10.6 实现 Job/Delivery/Webhook 运维详情链路，使用户可从入口事件追踪到最终失败或成功投递
- [ ] 10.7 为 Dashboard、队列、会话和附件页面补齐 loading、empty、partial unavailable、error 和 forbidden 状态

## 11. 安全、质量、浏览器与可访问性验证

- [ ] 11.1 运行后端单元和 API 契约测试，覆盖分页、范围过滤、revision、连接测试、队列降级和关联查询
- [ ] 11.2 运行 Secret/敏感信息专项测试，检查 API、审计、日志、前端状态和错误提示均不泄漏凭据或原始 payload
- [ ] 11.3 运行前端单元和集成测试，覆盖 mapper、表单 schema、Capability Gate、路由、错误/空状态和 query invalidation
- [ ] 11.4 使用真实浏览器验证桌面和窄屏的导航、表格、Dialog、Sheet、Toast、表单及滚动行为
- [ ] 11.5 使用真实后端数据执行登录、用户钉钉绑定、授权、默认 Agent 发布、Skill 分配、资源/Channel 配置和 Webhook 生命周期 E2E
- [ ] 11.6 使用真实后端数据执行 Dashboard、队列、历史会话、附件、Job/Delivery 故障链路只读 E2E
- [ ] 11.7 验证键盘导航、焦点管理、无障碍名称、颜色对比、响应式断点和危险动作确认
- [ ] 11.8 验证范围受限用户无法通过导航、直接 API、聚合计数、分页元数据或关联详情获取越权数据

## 12. 构建切换、清理与交付

- [ ] 12.1 更新前端 Dockerfile、Compose、CI 和开发命令为 pnpm frozen-lockfile workspace 构建
- [ ] 12.2 运行 pnpm lint、typecheck、test 和 production build，并验证 clean install 可重复成功
- [ ] 12.3 构建 Compose 镜像并验证 Web、API、Worker、RabbitMQ、PostgreSQL 及管理页面健康链路
- [ ] 12.4 在新页面全部通过迁移矩阵后删除旧扁平页面、手写 UI、全局巨型类型、npm lock 和废弃构建脚本
- [ ] 12.5 更新 README/运维文档，说明目录边界、开发命令、管理权限、MVP 写入限制、连接测试和队列只读边界
- [ ] 12.6 记录数据库迁移、前后端镜像和配置回滚步骤，并执行一次不破坏运行中 Job/会话的回滚演练
- [ ] 12.7 执行 `openspec validate refactor-admin-web-ddd-shadcn-mvp --strict` 并逐项核对所有规格场景和任务证据
