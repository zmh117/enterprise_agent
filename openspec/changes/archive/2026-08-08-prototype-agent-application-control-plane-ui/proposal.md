## Why

当前 `frontend/` 仅是通用 shadcn Dashboard 模板，无法表达 Agent 平台采用独立 API 平台后的产品边界，也无法用于评审业务应用、工作流、API Capability、运行中心和多外部系统身份关联的整体信息架构。需要先交付一个不连接后端、不执行任何操作的静态界面原型，在投入领域建模和接口开发前验证页面层级、业务术语和关键关系是否合理。

## What Changes

- 将现有模板改造成“Agent 应用平台”静态 Dashboard，移除 Revenue、Visitors、Documents、Projects 等无关演示内容。
- 展示业务应用控制台的信息架构，包括应用概览、Agent Profile、Workflow、渠道与触发器、API Capability 授权和发布版本关系。
- 展示三个代表性业务应用：钉钉私聊诊断助手、钉钉群聊诊断助手和 Webhook 告警分析助手。
- 展示 Agent 平台到独立 API 平台的调用边界，强调前端不配置数据库、Redis、Loki，不暴露 SQL、Redis 命令、LogQL、Shell 或任意 HTTP 工具。
- 展示系统管理的信息架构，包括外部系统接入、用户与外部身份、角色与授权、Webhook/服务账号、审计和环境管理。
- 展示内部用户与钉钉、ONES及未来其他系统账号的一对多关联，以及“身份关联不等于授权”的权限交集关系。
- 使用明确的“原型数据”“规划中”“不可操作”状态，避免用户将示例指标、按钮或列表误认为真实运行数据和已实现功能。
- 保留当前单体 Vite + shadcn 结构，按前端 bounded context 规划目录，不在本变更中引入登录、路由业务页面、API Client、状态持久化或后端改造。
- **BREAKING**：本原型的产品术语和菜单不再沿用旧管理 Web 的 Database/Redis/Loki Tool Resource 信息架构；旧变更不得作为新界面的产品基线继续扩展。

## Capabilities

### New Capabilities

- `agent-control-plane-dashboard-prototype`: 定义静态 Dashboard Shell、导航、平台概览、业务应用、运行链路、Capability、安全边界和建设状态的展示要求。
- `business-application-ui-prototype`: 定义业务应用、Agent Profile、Workflow、渠道与触发器、能力授权和发布版本之间关系的静态展示要求。
- `external-identity-ui-prototype`: 定义内部用户关联钉钉、ONES及其他外部账号，以及身份状态、用途、冲突和授权边界的静态展示要求。

### Modified Capabilities

无。本变更仅创建静态前端原型，不修改现有运行时、权限、Channel、Workflow、API 或数据模型的行为契约。

## Impact

- 前端：影响 `frontend/src/App.tsx`、Dashboard 页面、Sidebar/Header、模板卡片、图表、表格、静态数据和展示组件；规划新的 `app/`、`contexts/`、`shared/` 目录边界。
- 后端：不修改后端代码、接口、数据库迁移、权限和运行配置，也不调用现有管理 API。
- 运行时：不影响钉钉入口、Agent Job、RabbitMQ、模型调用、内部 API 平台、Delivery 或历史数据。
- 安全：不读取或展示真实 Secret、连接地址、用户数据和业务数据；所有示例信息必须是非敏感、可识别为原型的静态数据。
- 关联变更：新的产品边界将取代 `refactor-admin-web-ddd-shadcn-mvp` 中 database/redis/loki 工具资源管理的前端方向，但本变更不自动修改或归档该旧变更。
