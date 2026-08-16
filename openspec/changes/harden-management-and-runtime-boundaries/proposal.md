## Why

默认关闭管理 Web 的部署仍挂载部分管理 API、启动 `admin-web`，且兼容 actor Header 可以绕过可信认证上下文；同时 RabbitMQ consumer 对 handler 异常无限 requeue，运行中心查询在有限窗口后于 Python 过滤，前端错误被误判为无权限，非本地对象存储仍可落入已知默认凭据。这些缺口会分别造成未授权管理访问、毒消息热循环、查询结果不完整和不安全部署默认值，需要在继续结构重构前一次收口。

## What Changes

- **BREAKING** 将所有管理 Router、调试 Job 入口与 `admin-web` 部署统一受管理面开关控制；关闭时管理 Web/API 不暴露并返回 404。
- **BREAKING** 删除生产路径对 `x-admin-user-id`、`x-agent-user-id` 等客户端 actor Header 的信任；测试 Header 仅在显式 test/local 测试适配器中可用。
- 为平台拓扑、Secret、Agent Workflow 与调试 Job 建立统一权限矩阵，稳定区分未登录 401、已登录无权限 403、授权访问 200。
- 将 RabbitMQ envelope 解码、结构校验、可重试基础设施异常和 poison message 分类；poison message 有界进入 DLQ/隔离并记录指标或日志，不参与数据库 Job 业务重试。
- 保持数据库 Job retry、Job Dispatch Outbox 与 Delivery Outbox 为执行和投递重试的唯一业务权威，不用 broker delivery 次数复制业务重试状态机。
- 将运行中心 Job 范围、状态与查询条件下推数据库，并使用与过滤条件一致的稳定分页，避免先截断再过滤造成漏数。
- 增加前端路由/查询错误边界，分别呈现 401、403、网络/5xx 和渲染异常，不再把服务失败显示为无权限。
- 非 local/test 环境在对象存储凭据缺失或仍为仓库默认占位值时启动失败；Compose 的本地 MinIO 默认值仅允许显式本地开发形态。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `identity-access`: 收紧管理 actor 来源，并为 Workflow、平台配置和调试 Job 统一定义认证与细粒度 action 判定。
- `agent-model`: 明确 Workflow 读取、编辑与发布分别使用 Agent read/edit/publish 权限。
- `execution-delivery`: 增加 poison-message broker 边界和数据库权威重试约束，并要求 Job 查询在持久层完成过滤与稳定分页。
- `platform-operations`: 统一管理面开关覆盖 Router、调试入口和 `admin-web`，规定前端错误状态与非本地对象存储凭据失败关闭。

## Impact

- 后端应用装配、身份依赖、平台配置/Workflow/调试 Job Router 与权限能力映射。
- Docker Compose 的 `admin-web`、RabbitMQ 主队列/DLQ 拓扑和 MinIO 本地开发配置。
- RabbitMQ consumer、Job read repository、运行中心 API 查询契约。
- React Router、CapabilityGate、查询错误处理与全局 Error Boundary。
- 管理面、RabbitMQ、运行中心、前端和配置启动测试；现有客户端 actor Header 兼容调用将停止工作。
