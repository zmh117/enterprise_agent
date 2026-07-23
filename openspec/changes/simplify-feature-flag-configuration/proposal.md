## Why

当前部署需要同时理解并组合多个相互依赖的 `FEATURE_*` 环境变量，管理后台、统一身份和业务应用控制面甚至可能被配置成互相矛盾的状态。需要把面向部署人员的开关收敛为少量清晰的安全边界，同时保留真实模型、真实工具和已发布 Agent Runtime 等高风险数据面能力的独立控制。

## What Changes

- 将 `FEATURE_WEB_ADMIN` 定义为管理面的唯一总开关；开启时统一身份、Web Session、RBAC 和业务应用控制面自动生效，不再要求部署人员同时配置 `FEATURE_UNIFIED_IDENTITY` 与 `FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE`。
- 保留 `FEATURE_PUBLISHED_AGENT_RUNTIME`、`FEATURE_REAL_CLAUDE` 和 `FEATURE_REAL_INTERNAL_TOOLS` 三个会改变数据面执行或外部调用边界的显式安全开关，且不因开启管理后台而自动开启。
- 将 `FEATURE_TEST_IDENTITY_HEADERS` 限定为测试环境内部设置；生产环境即使误配也必须拒绝启动或强制关闭。
- 将 `FEATURE_PERMISSION_SHADOW_MODE` 从普通部署模板移出，改由受审计的运行时配置或迁移状态管理，并保留安全的默认行为。
- 将 Webhook 是否接收事件下沉到已发布 Connector/Trigger 配置；将连续会话和附件能力下沉到业务应用或 Agent 发布策略，逐步取消相应全局功能开关。
- 引入统一的“有效功能配置”解析与只读诊断输出，明确每个值来自安全默认值、环境变量、数据库运行时配置还是发布快照，并检测矛盾配置。
- 为旧环境变量提供一个受限兼容期：输出去敏弃用告警、保持原有数据面默认值，不静默扩大权限或开启外部调用。
- 收敛 `.env.example`、Compose 环境面和运维文档，只展示普通部署必须理解的四个开关；数据库、RabbitMQ、主加密密钥等 bootstrap 配置继续独立保留。
- **BREAKING**：兼容期结束后移除 `FEATURE_UNIFIED_IDENTITY`、`FEATURE_BUSINESS_APPLICATION_CONTROL_PLANE`、`FEATURE_WEBHOOK_TRIGGERS`、`FEATURE_CONTINUOUS_CONVERSATION` 和 `FEATURE_MESSAGE_ATTACHMENTS` 的直接部署入口；调用方必须迁移到总开关或受治理的发布配置。

## Capabilities

### New Capabilities

- `feature-configuration-simplification`: 定义面向部署人员的四个顶层开关、派生规则、旧配置兼容期、冲突处理、来源诊断以及安全收敛要求。

### Modified Capabilities

- `platform-runtime-config`: 将功能配置按 bootstrap、安全数据面开关和受治理运行策略分类，并规定确定性的来源优先级与安全回退。
- `platform-config-api`: 提供有效功能配置、来源和弃用状态的只读接口，并限制高风险或测试专用配置的修改方式。
- `platform-access-control`: 管理后台启用时统一启用身份、Web Session 与 RBAC，禁止形成无身份保护的管理入口。
- `channel-connector-configuration`: 使用已发布 Connector/Trigger 状态控制 Webhook 接入，不再依赖全局 Webhook 功能开关。

## Impact

- 后端配置模型、runtime config overlay、Bootstrap 依赖注入、管理后台认证和业务应用控制面开关判断。
- Webhook Worker、连续会话、附件处理等功能的配置读取边界，但本变更不得自动迁移或接管现有钉钉/Webhook 路由。
- `.env.example`、`docker-compose.yml`、本地/生产部署文档、健康检查和配置诊断 API。
- 现有测试、Compose profile、Worker 启动路径和运维脚本需要覆盖旧开关兼容、矛盾配置、安全默认值和迁移后的行为。
