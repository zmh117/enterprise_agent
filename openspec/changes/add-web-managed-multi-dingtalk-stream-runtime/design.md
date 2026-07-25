## Context

当前系统已经以 `integration_connector` 表达 Channel 入口和 Delivery 出口，以 `platform_secret` / `platform_secret_version` 保存受管密钥，以 Business Application Revision/Publication/Deployment 固定 Trigger、Agent Publication 和运行策略。DingTalk Stream 当前由 Python `dingtalk-stream-ingress` Worker 启动一个 SDK Client，Connector ID 和凭据主要在进程启动时确定，因此无法由 Web 动态增加第二个机器人。

已有 Managed Webhook 已实现公开入口、认证、Inbox/Outbox、幂等和异步 dispatch，可作为可靠接入的实现参考。已有 `ChannelIngressService` 负责身份映射、RBAC、Business Application 路由、会话与 Job 创建；已有 `ResultDeliveryService` 负责原会话回复。本次不复制或替换这些边界。

本变更跨越 FastAPI 控制 API、PostgreSQL/SQLite 兼容迁移、新 TypeScript Runtime、RabbitMQ 接入、Compose 和 React 管理页面。实施必须严格分两段：后端及 Runtime 完成全部自动化与运行验证后，才能开始前端页面。

## Goals / Non-Goals

**Goals:**

- 允许管理员通过受保护 API 管理多个钉钉应用机器人，并使用受管 Secret 保存 Client Secret。
- 单个固定 `dingtalk-runtime` 容器动态维护多个独立 Stream Client，不因新增、停用或轮换一个机器人而重启 Compose 或影响其他机器人。
- 暴露可信的期望状态、实际注册状态、心跳、最近消息和安全错误摘要。
- 在 ACK 钉钉前可靠持久化 Connector 级幂等 Inbox/Outbox，再异步进入现有 Channel Ingress。
- 将受管 Webhook 和钉钉应用机器人统一投影为 Business Application Trigger 可选 Channel。
- 后端完成后提供“业务应用 → 渠道与触发器”页面；只允许配置和选择 Webhook、钉钉应用机器人。
- 保持现有 Agent Publication、Agent Job、执行策略和结果投递行为不变。

**Non-Goals:**

- 不新增或修改 Agent Profile、模型连接、Agent 执行器、工具调用和 Agent 并行能力。
- 不新增 `agent.reply`、`dingtalk.reply` 或 TypeScript 结果投递消费者。
- 不实现多个 Runtime、副本分片、跨 Runtime 迁移或租户独立容器。
- 不动态修改 Compose、不调用 Docker API、不挂载 Docker Socket。
- 不实现邮件、企业微信、AI 卡片、任意 HTTP、任意脚本等其他 Channel。
- 不把钉钉应用直接绑定到一个 `agent_id`；Agent 仍由 Business Application Publication 决定。

## Decisions

### 1. 复用 Connector、Secret 和 Business Application，不新增平行聚合

钉钉应用机器人继续使用 `integration_connector`，类型为 `dingtalk_enterprise_stream`。`enabled` 表达管理员期望该 Connector 可用，现有 `revision` 作为 Runtime 的加载版本；重连操作递增 revision。非敏感的 Client ID、tenant/corp、robot code 和聊天开关保存在受校验 metadata 中，Client Secret 只通过 `platform_secret` 引用。

受管 Webhook 继续复用现有 Webhook Trigger 和 Connector。管理 API 提供统一 Channel DTO，但内部仍由各自领域服务维护，不把两类配置强行塞进一张新表。

Business Application Trigger 保存并冻结 Channel/Connector 引用。一个钉钉机器人可以被不同的私聊或群聊路由绑定到不同业务应用，因此 Connector 本身不保存默认 Agent。

备选方案是新建 `dingtalk_application` 并保存 `agent_id`、密文字段。该方案会复制 Connector、Secret 和 Publication 的事实来源，拒绝采用。

### 2. TypeScript Runtime 是连接适配器，不是 Agent 编排器

新增独立 `dingtalk-runtime/`，负责：

- 通过受保护的内部控制 API获取可加载 Connector 和短暂使用的解密凭据；
- 为每个已启用 Connector 创建一个 SDK Client；
- 协调启动、停止、重建和自动重连；
- 上报已加载 revision、WebSocket/注册状态、心跳、最近消息和安全错误；
- 把 SDK 回调提交到内部 Channel Inbox API；
- 在 Inbox/Outbox 事务成功后向钉钉 ACK。

Runtime 不直接读取业务表，不访问 Agent Publication，不创建 Agent Job，不消费结果队列，也不保存平台主密钥。Runtime 使用 Compose Secret 提供的内部服务凭据认证控制 API；敏感配置响应不得记录、缓存到磁盘或暴露到健康接口。

备选方案是让 Runtime 直接访问 PostgreSQL、RabbitMQ 并持有平台主密钥。虽然组件更少，但会复制数据库/加密实现并扩大敏感权限和 Schema 耦合，拒绝采用。

### 3. 使用显式 Client 状态机和串行化协调

每个 Managed Client 使用以下状态：

```text
STOPPED
  └─ enable/start ─→ STARTING
STARTING
  ├─ registered ───→ READY
  ├─ transient ────→ RECONNECTING
  └─ credential ───→ AUTH_FAILED
READY
  ├─ disconnect ───→ RECONNECTING
  ├─ disable ──────→ STOPPING ─→ STOPPED
  └─ revision变更 ─→ STOPPING ─→ STARTING
任意非终态
  └─ unexpected ───→ ERROR
```

`connect()` 返回只表示 WebSocket 打开，不等于订阅注册成功；只有 SDK `registered=true` 或等价 REGISTERED 事件后才能上报 `READY`。每个 Connector 的 start/stop/restart 必须通过独立互斥或串行操作队列执行，避免 reconcile 与 SDK 自动重连交叉创建重复连接。

配置 API 暂时不可用时，Runtime 保留当前健康 Client，不因一次拉取失败全部停用。只有成功取得新的期望快照后才能执行差异删除。

### 4. 期望状态与观测状态分离

Connector 配置是期望状态；新增 `channel_connector_runtime` 保存最近一次观测：

```text
connector_id
runtime_id
observed_status
loaded_revision
connected
registered
connected_at
disconnected_at
last_message_at
last_heartbeat_at
last_error_code
last_error_summary
updated_at
```

数据库中的 `READY` 不是永久事实。控制 API 根据 `last_heartbeat_at` 计算 `STALE`，Runtime 停止或租约过期时不得继续向前端显示“已连接”。错误只保存稳定 code 和脱敏摘要，不保存 Client Secret、endpoint ticket、sessionWebhook 或完整 SDK 响应。

### 5. 单 Runtime 通过控制面租约保护

Runtime 启动后通过内部 API 获取名为 `dingtalk-runtime-singleton` 的短租约并持续续约。已有未过期租约时第二实例必须退出且不得加载 Connector。控制面在事务中比较 runtime ID 和过期时间。

使用 API 租约而不是 Runtime 直接持有 PostgreSQL advisory lock，可以避免为 TypeScript Runtime开放数据库权限，并保留未来演进为 Connector 级租约的空间。本次仍只允许一个 Runtime。

### 6. 钉钉消息采用可靠 Channel Inbox/Outbox

内部接入 API在一个数据库事务中：

1. 校验 Runtime 服务身份和 Connector 是否允许 ingress；
2. 解析并校验有界消息；
3. 使用 `(connector_id, external_event_id)` 幂等；
4. 写入 `channel_ingress_event`；
5. 写入 `channel_ingress_outbox`；
6. 返回可 ACK 结果。

Inbox 只保存 payload hash、安全摘要和后续处理必需的标准化事件。`sessionWebhook` 等回复凭据必须使用现有加密能力受控保存，不能进入审计或 RabbitMQ payload。

Outbox Publisher 只发布：

```json
{
  "channel_event_id": "...",
  "correlation_id": "..."
}
```

Python Dispatcher 加载事件并调用现有 `ChannelIngressService`。既有外部身份、权限、Business Application 路由、Job 创建和配置错误回复保持唯一实现。相同事件重试复用 Inbox/Job，不创建第二个 Job。

### 7. Webhook 和钉钉使用统一 Channel 目录、不同提供者适配器

控制 API 暴露统一只读目录项：

```text
channel_id
provider_type: WEBHOOK | DINGTALK_APP_ROBOT
name
enabled
ingress_eligible
supported_trigger_types
runtime_summary
revision
```

- `DINGTALK_APP_ROBOT` 来自 `dingtalk_enterprise_stream` Connector，支持 `dingtalk_private`、`dingtalk_group`。
- `WEBHOOK` 来自现有受管 Webhook Trigger/Connector，支持 `webhook`。

创建/编辑仍委托各自领域服务，避免把 Webhook 的签名、映射、public ID 和 DingTalk 的长连接配置混成一个通用 JSON 表单。Business Application 保存草稿和发布前必须由服务端再次校验 Channel 已启用、允许 ingress 且支持目标 trigger type，不能信任前端下拉结果。

### 8. 后端与前端设置强制阶段门

后端阶段必须先完成：

- 双数据库迁移和自动化测试；
- Channel 管理与 eligible catalog API；
- Runtime 多 Client、租约和状态；
- DingTalk Inbox/Outbox 故障恢复；
- Compose 构建和真实双机器人验证（有凭据时）。

这些验收未完成前，不开始 React 页面。前端阶段只新增“业务应用 → 渠道与触发器”，包含 Channel 列表、钉钉应用机器人配置、受管 Webhook 配置入口和 Trigger Binding 选择，不扩展其他菜单或功能。

### 9. 保留现有基础设施版本与测试兼容性

继续使用当前 Compose 的 PostgreSQL 18 和 RabbitMQ 4。迁移使用项目现有的 TEXT/INTEGER/JSON 字符串惯例和应用生成 ID，不引入只支持 PostgreSQL 的 `pgcrypto`、UUID DEFAULT、JSONB 或 TIMESTAMPTZ，确保 SQLite 内存测试仍能执行同一迁移。

## Risks / Trade-offs

- [单 Runtime 是单点故障] → Compose 使用 `restart: unless-stopped`，Runtime 重启后从期望状态恢复全部 Client；状态通过心跳过期显示 STALE，未来再演进 Connector 租约分片。
- [一个错误 Client 影响事件循环] → 每个 Connector 独立状态机、超时、退避和错误边界，禁止未捕获 Promise 终止 Runtime。
- [控制 API短时不可用] → 保留现有 Client，停止 destructive reconcile，只上报服务降级；API恢复后继续差异协调。
- [Secret 明文在内部 API短暂传输] → 仅 Compose 内网、服务认证、响应禁止日志和磁盘缓存；生产升级项为 mTLS，但不纳入本次 MVP。
- [SDK `connect()` 与实际 REGISTERED 不一致] → READY 只由注册状态驱动，并测试连接建立但注册失败场景。
- [同一钉钉应用被旧 Worker 和新 Runtime 同时连接] → 迁移阶段先登记 Connector，再停旧 Worker、启新 Runtime；运行手册禁止并行。
- [Webhook 与 DingTalk 配置模型差异大] → 只统一管理目录和 Trigger 选择，不统一底层 provider-specific 配置。
- [RabbitMQ 故障造成消息丢失] → ACK 前持久化 Inbox/Outbox，Outbox 支持重试和 dead 状态；队列 payload 只含 ID。
- [一个 Agent Worker 不并行] → 本次验收只要求事件和 Job 独立、不丢失、不串会话，不要求 Agent 同时执行。

## Migration Plan

1. 增加 SQLite/PostgreSQL 兼容迁移、受管 Channel API、Runtime 内部 API、租约、状态和 Inbox/Outbox，保持旧 Worker 运行。
2. 完成 TypeScript Runtime、单元测试、契约测试和 Compose 服务定义，但默认不与旧 Worker 同时启用。
3. 将现有环境变量中的钉钉应用登记为 `dingtalk_enterprise_stream` Connector，并把 Client Secret 写入现有受管 Secret。
4. 停止旧 `dingtalk-stream-ingress`，启动 `dingtalk-runtime`，确认 READY、消息幂等、Business Application 路由及原会话回复。
5. 验证新增第二个机器人、独立停用、Secret 轮换、Runtime 重启、RabbitMQ 故障恢复。
6. 后端验收通过后实现“业务应用 → 渠道与触发器”页面，并验证只有 eligible Channel 可绑定。
7. 稳定后删除旧单连接 Worker 的 Compose 服务和启动配置；保留迁移说明，不保留双运行模式。

回滚时停止新 Runtime，恢复旧单连接 Worker所需环境变量并只启用一个既有机器人。Inbox/Outbox 和运行状态表可以保留，不影响旧数据面；不得同时运行新旧连接。

## Open Questions

无。MVP 已明确使用单 Runtime、内部控制 API、现有 Secret/Connector/Business Application、后端先行，并排除 Agent 功能和执行并行。
