## Why

当前 `dingtalk-stream-ingress` 只能从启动配置加载一个钉钉应用并维护一条 Stream 长连接，新增机器人需要修改环境变量并重启服务，无法支撑 Web 管理多个钉钉应用机器人。系统已经具备 Connector、受管 Secret、业务应用 Trigger、Channel Ingress 和可靠 Webhook Inbox/Outbox，本次应在这些边界上增加动态多连接能力，而不是新建第二套 Agent、路由或投递体系。

## What Changes

- 将钉钉应用机器人建模为受管 Channel Connector；管理员可保存、启用、停用、更新凭据和请求重连，真实 Client Secret 复用现有受管 Secret 加密存储。
- 增加单实例 TypeScript `dingtalk-runtime`，在同一容器内为每个已启用钉钉应用维护一个独立 Stream Client，并根据配置修订自动启动、停止或重建单个连接。
- 增加 Connector 运行状态、已加载配置修订、注册状态、心跳、最近消息和安全错误摘要，使控制 API 能区分期望状态与实际状态。
- 将钉钉回调通过内部受控入口写入可靠 Channel Inbox/Outbox，再交给现有 Python Channel Ingress；消息幂等范围包含 Connector，RabbitMQ 仅携带事件标识和关联标识。
- 保留现有身份映射、RBAC、Business Application 路由、Session/Execution Policy、Agent Job 和结果投递实现；本次不修改 Agent 执行能力、不增加 Agent 并行执行，也不新建 `agent.reply` 投递链路。
- 后端完成并验证后，在左侧导航“业务应用”分组中把“渠道与触发器”作为“应用列表”下方的独立页面，而不是放进某个应用详情。第一版只展示和配置两类入口：受管 Webhook、钉钉应用机器人；Channel 启用且符合入口资格后，才会出现在应用设置的 Trigger Binding 选择器中。
- 初次部署增加固定的 `dingtalk-runtime` 服务；此后从 Web 新增或修改机器人不修改 Compose、不动态创建容器，也不向后端暴露 Docker Socket。
- **BREAKING**：现有单连接 Python `dingtalk-stream-ingress` 运行方式由多连接 Runtime 取代；切换前必须把当前钉钉应用凭据迁移或登记为受管 Connector，避免同一应用被两个 Stream Client 重复连接。

## Capabilities

### New Capabilities

- `managed-channel-administration`: 受管 Webhook 与钉钉应用机器人 Channel 的后台管理、Secret 录入、期望状态、运行状态和 Trigger 可选目录。
- `multi-dingtalk-stream-runtime`: 单个 Runtime 内动态管理多个钉钉 Stream Client、配置协调、独立重连、状态观测和单实例保护。
- `business-application-channel-trigger-management`: “业务应用”导航下独立的“渠道与触发器”页面，以及应用设置中已启用 Channel 到 Trigger Binding 的受控选择行为。

### Modified Capabilities

- `channel-connector-configuration`: 将钉钉应用机器人和受管 Webhook 纳入 Web 管理的入口 Connector，并约束凭据、启停状态和 Trigger 可选条件。
- `dingtalk-stream-ingress`: 从启动时单 Connector 改为数据库驱动的多 Connector Runtime，并增加独立生命周期与状态语义。
- `channel-ingress-contract`: 钉钉 Stream 事件在确认前进入可靠 Inbox/Outbox，并保持 Connector 级幂等和现有 Channel/业务应用边界。

## Impact

- 后端：Connector/Secret 管理 API、运行状态读模型、内部 Channel 接入、Inbox/Outbox dispatcher、RBAC 和审计。
- 新服务：增加 TypeScript `dingtalk-runtime` 目录、镜像、健康检查和单实例运行保护；保留现有 Python API 与 Agent Worker。
- 数据库：在现有 `integration_connector`、`platform_secret` 基础上增加运行状态与可靠 Channel 事件表；迁移保持 PostgreSQL 与 SQLite 测试兼容。
- 前端：后端验收完成后，在“业务应用”侧边栏分组的“应用列表”下增加独立“渠道与触发器”页面；应用详情只保留 Trigger Channel 选择器，不增加其他管理模块。
- 部署：Compose 初次增加一个固定 Runtime 服务，继续使用现有 PostgreSQL 18 和 RabbitMQ 4。
- 明确排除：Agent Profile、Agent 执行器、Agent 并行、多 Runtime 分片、动态容器、AI 卡片、邮件/企业微信等其他 Channel 类型。
