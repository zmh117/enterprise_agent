## Why

现有管理 Web 已经能够静态展示“一个 Agent Runtime、多个 Agent Profile、多个业务应用”的目标产品模型，但后端仍只有彼此独立的 Agent、Workflow、Channel、Webhook 和权限配置，缺少把这些资源装配成可治理业务应用的事实模型。现在需要先建立业务应用控制面底座，使后续钉钉、Webhook、ONES 身份和 API Capability 都能绑定到稳定、可版本化、可审计的应用边界，而不是继续依赖全局默认配置或前端静态数据。

## What Changes

- 新增 Business Application 聚合，管理稳定应用标识、名称、用途、项目、生命周期和负责人，并支持草稿修订。
- 允许应用草稿引用现有 Agent 发布版本、Workflow 发布版本、Channel/Trigger 配置、会话策略、投递策略以及预留的 API Capability 编码；不复制这些资源的内部配置。
- 新增发布前完整校验和不可变应用发布快照，冻结所有组件引用、策略、配置哈希和发布审计信息。
- 新增环境级激活状态和确定性解析读模型，为后续入口事件按应用路由、运行时加载发布快照和回溯历史版本提供基础。
- 新增受 RBAC、CSRF、乐观并发和审计保护的管理 API，覆盖应用列表、详情、创建、草稿编辑、校验、发布、停用和发布历史查询。
- 将前端业务应用区域从纯静态原型演进为真实列表与详情工作区，第一版开放概览、组成配置、校验和发布历史；流程画布及其他平台模块继续保留规划状态。
- 保持 Agent Runtime、Workflow 执行、钉钉/Webhook 入口和现有默认 Agent 路径不变；应用发布不会在本变更中自动切换生产入口或触发 Agent Job。
- 不在本变更中实现 API Capability 目录、任意 OpenAPI 导入、ONES 业务查询、底层数据库/Redis/Loki 配置、Secret 明文展示或高风险写能力。

## Capabilities

### New Capabilities

- `business-application-control-plane`: 定义业务应用聚合、草稿修订、组件引用、生命周期、并发控制和控制面治理边界。
- `business-application-publication`: 定义发布校验、不可变快照、环境级激活、版本历史和供后续运行时使用的确定性解析读模型。
- `business-application-admin-workbench`: 定义受权限保护的管理 API，以及业务应用真实列表、详情、组成配置、校验和发布历史 Web 工作区。

### Modified Capabilities

无。现有 Agent、Workflow、Channel、入口、权限和运行时规格继续有效；本变更先增加装配与发布底座，不改变现有数据面行为。

## Impact

- 数据库：新增业务应用定义、草稿修订、发布快照、环境激活、组件绑定和审计相关表与索引。
- 后端：新增独立的业务应用领域、应用、基础设施和 API 模块，并在现有依赖容器与管理 API 中注册；复用 Agent、Workflow、Channel、Identity、Permission 和 Audit 的公共契约。
- 前端：新增业务应用路由、查询模型、表单和发布历史视图；保留 shadcn/ui 与现有 bounded-context 目录，不恢复旧的数据库/Redis/Loki 工具管理信息架构。
- 运行时：只提供已发布应用解析接口和读模型，不改写钉钉、Webhook、RabbitMQ、Agent Worker 或 Delivery 的现有默认执行路径。
- 安全：所有写操作要求已认证内部用户、明确权限、CSRF 和审计；发布快照只保存 Secret 引用或非敏感组件标识，不保存真实凭据。
