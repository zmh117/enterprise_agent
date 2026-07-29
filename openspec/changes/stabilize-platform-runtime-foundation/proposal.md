## Why

现有平台已经能够运行 Agent、内部只读工具、Webhook、DingTalk 与管理配置，但关键链路仍存在信任边界可伪造、迁移并发不安全、数据库事务边界共享、任务发布与结果投递非原子、资源契约漂移以及 Secret 引用规则不一致等基础问题。若直接继续建设 API 工具能力配置界面，这些问题会被固化到新的管理模型中，因此需要先稳定运行时基础。

## What Changes

- **BREAKING** 全局切换到 `strict_application_role`，移除 `compatibility` 配置、代码与权限回退；备份后清理旧 `permission_policy`、`platform_access_grant`，不自动迁移旧权限，同时保留现有身份、新角色与新 RBAC 数据。
- **BREAKING** 调试 Job API 改为登录用户专用入口，必须具备 `agent.debug.execute`，不得提交任意 `user_id`、Agent、资源、连接器或路由；新增“运行中心 → 发起调试”界面。
- 为 Internal API Platform 增加必需的可轮换服务 Token 和服务端 Job 事实校验，拒绝仅凭可伪造上下文 Header 获得权限。
- 引入一次性 Migrator 服务、迁移账本、checksum、PostgreSQL advisory lock 和逐版本整事务；应用进程只验证迁移 head，不再启动时自动迁移。
- 将数据库访问改为同步连接池与操作级 Unit of Work，消除全局共享连接和事务深度，禁止跨模型调用、外部网络或 RabbitMQ 持有数据库事务。
- 为 Job dispatch 与 Delivery 建立事务 Outbox、独立状态机、幂等消费者、有限重试、DLQ、显式 CLI 恢复和一次性切换流程，提供 at-least-once 语义。
- 建立 DB、Redis、Loki 资源的草稿、技术验证、不可变发布版本、应用发布绑定、热加载、Last Known Good 与资源状态管理，并提供“平台治理 → 工具资源”界面。
- 提供显式 `resource-reset report/prepare/apply/verify` 维护操作，删除当前全部 DB、Redis、Loki 资源配置后从空配置重新建立；保留 Provider 定义、Secret、身份、应用、Job、投递、审计和历史快照。
- 强化“平台治理 → 凭据中心”：新资源只保存 `secret://platform/<code>`，明文只在写入时出现且永不回显；兼容导入现有 `env:` 引用，`vault:`、`kms:` 仅作为未实现预留 Provider，禁止创建或发布。
- 使用仓库外固定 Master Key 文件加密平台 Secret，移除 Compose 中的硬编码回退；本次不引入在线多密钥 keyring、有效期或周期轮换。
- 统一 MySQL、SQL Server、Oracle 资源契约；Oracle 目标为 11.2.0.4 单实例，使用结构化 Host、Port、Service Name/SID、python-oracledb Thick 与 Instant Client 19c，并强制可验证的只读账户和查询边界。
- 建立代码注册的不可变 Capability Handler、逻辑资源槽与业务应用发布时的具体 Resource Revision 绑定；Job 创建时固化不可变 Execution Scope。
- **BREAKING** 新会话只允许按应用发布版本、连接器、外部会话与 Execution Scope 隔离；停用 `application`、`actor` 连续会话模式，新 Job 不再附着旧模式会话。
- **BREAKING** 所有外部 Webhook 统一使用独立强 Bearer Token；移除空 Secret、认证回退和旧 Grafana Token 兼容入口。本次本地 HTTP 验证不增加 HMAC、HTTPS、timestamp 或 nonce。
- CI 统一使用 npm/`npm ci`，建立 PR 快速门禁、Compose 集成门禁和真实本地端到端验收；真实 Oracle 连接验收因本地无 Oracle 明确延期，不得声称已验证。
- 明确不包含：身份与授权全量重置、Capability Catalog/Handler 管理界面、生产 HTTPS、网络区域与 Egress Policy、Debug Trace 保留期重构、Worker 执行租约/fencing、崩溃中 `RUNNING` 自动恢复及任务取消。

## Capabilities

### New Capabilities

- `platform-schema-migration-runtime`: 独立 Migrator、迁移账本、checksum、全局锁、逐版本事务和应用启动 head 校验。
- `transactional-runtime-outbox`: Job 与 Delivery Outbox、独立状态机、幂等消费、DLQ、CLI 恢复及一次性切换。
- `governed-tool-resource-management`: DB、Redis、Loki 资源草稿、验证、发布、绑定、热加载、LKG、重置和管理界面。
- `governed-capability-handler-runtime`: 代码注册 Handler、不可变版本、逻辑资源槽、应用发布绑定和固化 Execution Scope。
- `runtime-session-isolation`: 外部会话、Webhook 和 Debug 会话按发布版本及 Execution Scope 隔离。
- `platform-runtime-acceptance`: npm CI、Compose 集成门禁、本地真实端到端验收及明确延期项。

### Modified Capabilities

- `agent-job-debug-api`: 调试入口改为受登录态、权限、应用发布和 Execution Scope 约束的安全 API 与 Web 流程。
- `agent-job-lifecycle`: Job 创建固化授权事实、资源范围与会话范围，Job 和 Delivery 生命周期分离。
- `platform-access-control`: 删除 compatibility 回退并强制全局严格应用角色授权和双人平台管理员不变量。
- `internal-tool-platform-integration`: Internal API 调用必须同时通过服务 Token 和 Job 事实授权。
- `platform-secret-management`: 只允许创建 `secret://platform/` Secret，使用固定外部 Master Key，限制旧 Provider 的兼容范围。
- `platform-config-api`: 资源配置管理改为草稿、验证、发布和有效版本查询契约。
- `platform-config-registry`: Provider 与资源字段契约对齐实际运行时，并禁止未实现 Provider 被声明可用。
- `platform-runtime-config`: PostgreSQL 已发布 Resource Revision 成为运行时唯一事实源，YAML/env 仅用于 bootstrap/import。
- `readonly-tool-platform`: 工具只消费已发布、已授权且已生效的资源快照，并维持数据库、Redis、Loki 的只读和结果边界。
- `multi-dialect-database-gateway`: 对齐 MySQL、SQL Server、Oracle 11g 的结构化连接、只读校验与查询执行要求。
- `base-scoped-redis-loki`: Redis、Loki 改为版本化资源绑定和 Secret 引用，并服从固化 Execution Scope。
- `internal-platform-topology`: 环境、基地、车间拓扑绑定不可变 Resource Revision，不再由运行时 YAML 直接决定。
- `channel-ingress-contract`: 外部 Webhook 统一强 Bearer Token，身份与范围从已发布绑定解析。
- `channel-connector-configuration`: 缺失 Secret 的连接器必须进入 MISCONFIGURED 并停用，移除认证回退与旧 Grafana Token 入口。
- `rabbitmq-agent-job-execution`: RabbitMQ 发布改由事务 Outbox 驱动，并按 at-least-once 和幂等消费者处理。
- `result-delivery-routing`: Agent 成功与投递成功分离，所有投递经 Delivery Outbox、独立重试和 DLQ。
- `real-tools-runtime`: Compose 验收必须验证真实本地 Grafana、Webhook、Agent、只读工具和 DingTalk 投递链路。

## Impact

- 后端：身份与授权、Debug Job、会话、业务应用发布、内部工具客户端与服务端、资源与 Secret 管理、数据库基础设施、迁移启动流程、消息总线、Job/Delivery 状态机、Webhook 与 DingTalk 链路。
- 前端：新增凭据中心、工具资源和受限调试入口；Capability Catalog/Handler 配置界面保持为后续变更。
- 数据：新增迁移账本、资源草稿/版本/绑定、Outbox/DLQ 等结构；备份后删除旧授权回退数据，并通过显式维护操作清空现有 DB、Redis、Loki 资源配置。
- 运行环境：Compose 增加一次性 Migrator 依赖；固定 Master Key 通过仓库外文件注入；Oracle 镜像改用匹配架构的 Instant Client 19c Thick 模式。
- 运维：需要维护窗口完成严格授权切换、Outbox 切换和资源清空；所有破坏性 apply 均需再次展示精确影响并获得人工确认。
- 兼容性：不保留旧 authorization compatibility、旧 Grafana Token、应用级/用户级跨会话复用、运行时 YAML 资源回退或旧消息拓扑的长期双写。
