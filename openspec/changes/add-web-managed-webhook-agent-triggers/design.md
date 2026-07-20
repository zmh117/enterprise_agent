## Context

仓库已经具备两类 Webhook 入口：`/webhooks/grafana/alert` 把 Grafana Alertmanager 报文转换为 `ChannelEvent`，`/webhooks/channel/agent` 接收调用方已经标准化的 `from/delivery/routing/message`。两者随后复用 `ChannelIngressService -> CreateAgentJobService -> RabbitMQ -> Agent worker -> 只读工具 -> ResultDeliveryService`。现有实现已经具备 connector 方向校验、简单 token 认证、Grafana `firing` 过滤、幂等键、Agent publication 固定和钉钉投递，但配置来自代码与 seed，通用入口还要求外部系统理解内部协议。

管理端已具备用户/RBAC、默认诊断 Agent 草稿与发布能力；该能力仍处于独立 OpenSpec change 中，本 change 的实现必须以统一身份和 Agent publication 模型已经可用为前提。第一版 UI 继续只开放默认诊断 Agent，后端数据模型保留多 Agent 扩展能力。

主要约束如下：

- Agent 仍然只能执行代码注册、已启用、Agent 已分配、主体已授权且满足平台数据范围的只读工具。
- 外部 Webhook payload 是不可信数据，不能成为系统指令，不能决定权限、工具或任意投递目标。
- RabbitMQ 载荷保持最小化，不携带原始 Webhook payload、secret 或完整 Agent 上下文。
- 不新增 Redis 依赖；幂等、持久化 Inbox、限流和防重放状态优先使用 PostgreSQL。
- 原始 payload 默认不持久化；只保存 hash、受控提取字段和脱敏有界摘要。
- 现有 Grafana URL 需要兼容迁移，不能在本 change 部署时突然失效。

## Goals / Non-Goals

**Goals:**

- 让管理员通过 Web 创建、校验、发布、回滚和停用 Grafana/通用 JSON Webhook Trigger。
- 对不同第三方 JSON 使用安全、可测试、可版本化的声明式映射，并归一化到现有 Channel event。
- 为 Webhook 建立 fail-closed 认证、防重放、限流、幂等、持久化 Inbox 和可恢复异步分发。
- 使用不可登录的服务账号承载 Trigger 的 Agent、项目、工具和数据范围权限。
- 在事件接收时固定 Trigger publication、Agent publication、routing 和 Delivery 语义。
- 复用现有 Agent job、RabbitMQ worker、只读工具和结果投递链路。
- 在 Web 中提供配置预览、发布历史、事件状态、关联 job 和安全错误摘要。

**Non-Goals:**

- 不允许管理员动态创建任意 HTTP API、MCP、Python、JavaScript、Shell、写 SQL 或其他执行器。
- 不允许 Webhook payload 动态增加 Agent 工具、扩大数据范围、切换服务账号或指定任意 Delivery endpoint。
- 不实现工作流编排、告警自动修复、重启、部署、写数据库或其他变更型操作。
- 不把完整第三方 payload、附件或大对象作为长期证据仓库；需要保留原始告警时由来源系统负责。
- 不在第一版支持 XML、表单、multipart、CloudEvents 全套协议或厂商插件市场。
- 不在第一版开放多 Agent 选择 UI；Trigger publication 模型仍保存通用 Agent 引用。

## Decisions

### 1. 在现有 Channel ingress 前增加受管 Trigger 层，不新建第二条 Agent 执行链

公共入口统一为：

```text
POST /webhooks/v1/{public_id}
  -> WebhookIngressService
  -> 已发布 Trigger + Connector + 服务账号
  -> 认证/过滤/映射/Inbox
  -> Webhook dispatcher
  -> ChannelIngressService
  -> Agent job / RabbitMQ / worker
  -> ResultDeliveryService
```

Trigger 层只负责外部协议治理；一旦生成 `ChannelEvent`，继续调用现有应用服务。这样 connector 方向、job 幂等、Agent publication、工具权限、审计和 Delivery 不会出现两套实现。

**替代方案：** 为 Grafana、Sentry、Jenkins 分别创建 controller 和 job service。否决，因为每个适配器都会重复认证、权限、幂等和投递逻辑，后续无法通过 Web 统一治理。

### 2. Connector 表达通信与凭证，Trigger 独立表达业务映射和发布生命周期

保留 `integration_connector` 作为来源 connector、方向、secret reference、endpoint 和 host allowlist 的事实。新增：

```text
webhook_trigger_definition
  id, code, name, trigger_type, public_id, connector_id,
  service_account_id, status, current_publication_id, revision

webhook_trigger_revision
  id, trigger_id, revision, config_json, config_hash,
  validation_status, validation_errors, created_by, created_at

webhook_trigger_publication
  id, trigger_id, revision_id, schema_version,
  snapshot_json, config_hash, published_by, published_at

webhook_event
  id, trigger_id, trigger_publication_id, agent_publication_id,
  external_event_id, dedup_key, payload_hash, safe_summary_json,
  normalized_event_json, correlation_id, job_id, status,
  auth_result, filter_result, error_code, error_summary,
  received_at, dispatched_at, completed_at

webhook_replay_nonce
  trigger_id, nonce_hash, expires_at
```

Trigger publication 保存完整有效快照，不在执行时回读草稿。`integration_connector.metadata` 不承载大段映射或 Trigger 生命周期，以免配置无法校验、比较和回滚。

**替代方案：** 把所有字段都放进 connector metadata。否决，因为 connector 既可能用于 ingress 也可能用于 delivery，映射 revision、Agent 绑定和事件过滤属于 Trigger 而不是通信 endpoint。

### 3. Trigger publication 固定具体 Agent publication，而不仅保存 Agent code

发布 Trigger 时，后端解析并校验所选 Agent 当前 publication，把 `agent_code/publication_id/revision/config_hash` 写入 Trigger snapshot。Webhook event 接收时复制这些引用，dispatcher 创建 job 时要求使用该固定 publication，而不是再次读取“当前 Agent”。

这样即使告警进入 Inbox 后管理员发布或回滚 Agent，已接收事件仍按接收时可审计的配置执行。管理员要让 Trigger 使用新 Agent 版本，必须创建并发布新的 Trigger revision。

Trigger 页面只展示 Agent publication 的有效工具摘要，不能建立独立的工具增量列表；最终工具集合仍由 Agent publication、代码 registry、服务账号 RBAC 和平台数据范围取交集。

**替代方案：** 仅保存 Agent code，dispatcher 创建 job 时读取当前 publication。否决，因为排队期间配置变化会让同一事件产生不可复现结果。

### 4. 使用声明式 JSON Pointer 映射，不执行用户脚本

第一版提供两种 adapter schema：

- `grafana_alertmanager_v1`：内置读取 `status/groupKey/commonLabels/commonAnnotations/alerts`，一个 group 创建一个事件。
- `generic_json_v1`：管理员用受限 JSON Pointer 配置 `event_id/status/title/description/entities` 等提取路径。

条件表达式只支持 `exists/equals/in/not_equals` 和 AND 组合；消息模板只能引用已声明的提取变量，输出有字符上限并按不可信数据处理。禁止脚本、任意函数、网络访问、文件访问和模板动态属性遍历。

Routing 每个字段使用以下策略之一：

```text
fixed(value)
extract(json_pointer, allowed_values)
```

`project_code/environment/base/workshop` 若使用 extract，必须配置非空 allowlist；`service` 至少必须满足 allowlist 或受控 code pattern。Trigger 发布时拒绝无界 routing。

**替代方案：** 使用 Jinja、JavaScript 或 Python 转换。否决，因为外部 payload 与管理员模板组合后会形成代码执行、资源耗尽和越权风险。

### 5. 公共入口按原始字节执行 fail-closed 认证

每个 Trigger publication 必须选择一种认证策略：

- `bearer_v1`：读取 `Authorization: Bearer <token>`，与 secret reference 解析结果做常量时间比较。
- `hmac_sha256_v1`：读取时间戳、nonce 和签名 header，以 `timestamp + "." + raw_body` 作为签名内容；默认只接受正负 5 分钟时间窗，并通过 nonce 唯一约束拒绝重放。

公共入口还必须执行：HTTPS 部署要求、JSON Content-Type、请求体上限、JSON 深度/集合数量上限、固定 public ID 格式、每 Trigger 速率/并发限制和安全日志。未配置或无法解析 secret 的 Trigger 不得发布；运行时 secret 解析失败返回安全错误，不能退化成匿名允许。

认证失败只保存 trigger ID、payload hash、请求大小、远端安全摘要和错误码，不保存正文。未知 public ID 使用统一 404/拒绝响应，避免枚举配置状态。

**替代方案：** 沿用“secret 为空就跳过验证”。否决，因为受管公共入口必须默认拒绝。

### 6. 同步完成认证、映射和 Inbox 事务，异步创建 Agent job

接收流程：

1. 有界读取 raw body，解析 Trigger publication 并完成认证。
2. 解析 JSON，执行 adapter、filter、routing 约束和稳定 dedup key 生成。
3. 在一个 PostgreSQL 事务内写入 `webhook_event` 和 outbox dispatch 记录。
4. 对需要执行的事件返回 `202 Accepted`；对合法但被过滤的 Grafana `resolved` 返回兼容的 ignored acknowledgement。
5. Outbox publisher 把 `webhook_event_id/correlation_id` 发布到专用队列；恢复扫描器可重新投递未发送 outbox。
6. Webhook dispatcher 按 event 固定快照生成 `ChannelEvent`，调用现有入口和 job 创建逻辑，关联 `job_id`。

RabbitMQ 仍不携带 raw payload、normalized body、secret 或 Agent 配置。事件重复投递、outbox 重发和 dispatcher 重试都以 event/dedup 唯一约束保持幂等。

**替代方案：** HTTP 请求内直接创建 job 并发布 RabbitMQ。否决，因为数据库成功而消息发布失败时缺少可靠恢复，也会把外部重试与内部任务创建耦合。

### 7. Grafana firing-only 和一个 group 一个 job 保持为默认语义

`grafana_alertmanager_v1`：

- `status=firing` 时用 `groupKey`，缺失时使用排序后的 alert fingerprints 构造 dedup key。
- 同一 Trigger、同一稳定事件身份和 firing 语义只创建一个 job。
- `resolved` 和其他状态只写事件/审计并标记 `IGNORED`，不创建 job。
- 消息包含 bounded 的公共 annotations、labels 和最多配置数量的 alert 摘要；不把完整 payload 直接送入 Agent。

这样与当前行为和既有运维约定兼容，并避免一组告警产生大量并发诊断。

### 8. 外部 payload 不能选择 Agent、服务账号、工具或 Delivery

Trigger publication 固定：

- `service_account_id`
- Agent publication
- source connector
- routing policy
- delivery type、connector 和安全目标

外部 payload 中即使存在同名字段也不参与这些决策。第一版不支持 payload 选择任意钉钉群；若将来需要动态目标，只能增加显式枚举映射到已发布的目标 profile，不能接收 URL、token 或 connector ID。

ResultDeliveryService 继续负责分片、attempt/chunk 审计和失败隔离。Delivery 失败只影响投递状态，不重新执行 Agent。

### 9. 每个 Trigger 默认拥有专用不可登录服务账号

在现有 `app_user` 增加 `account_type=human|service`；service 类型不得创建密码凭证、Web session 或外部人类身份绑定。创建 Trigger 时默认事务创建专用服务账号，管理员通过现有角色/策略和平台 grant 分配最小权限。

job 的 `internal_user_id/requester_id` 使用该服务账号 ID，权限求值继续复用统一 RBAC。Trigger 或服务账号任一被禁用时，新事件 fail closed；已创建 job 保留历史主体和 publication 证据，但是否继续执行遵循现有 job 生命周期策略。

**替代方案：** 继续使用字符串 `grafana` 或让所有 Trigger 共用管理员账号。否决，因为无法禁用单一来源、无法进行最小权限授权，也会把非人类行为归到自然人。

### 10. Web 管理采用草稿/发布和显式预览，不直接编辑运行配置

新增管理 API：

```text
GET/POST       /api/admin/webhook-triggers
GET/PATCH      /api/admin/webhook-triggers/{code}
POST           /api/admin/webhook-triggers/{code}/revisions
POST           /api/admin/webhook-triggers/{code}/revisions/{id}/validate
POST           /api/admin/webhook-triggers/{code}/revisions/{id}/preview
POST           /api/admin/webhook-triggers/{code}/revisions/{id}/publish
POST           /api/admin/webhook-triggers/{code}/publications/{id}/rollback
POST           /api/admin/webhook-triggers/{code}/rotate-public-id
GET            /api/admin/webhook-triggers/{code}/events
GET            /api/admin/webhook-events/{id}
```

预览接收管理员提供的测试 JSON，返回过滤结果、提取变量、routing、消息安全预览、dedup key 和将使用的 Agent/Delivery 摘要；不创建 event/job、不调用 Agent、不发送钉钉，也不持久化原始样本。所有写操作使用 session actor、独立 action、expected revision、CSRF 和审计。

前端页面：

```text
/admin/webhooks
/admin/webhooks/new
/admin/webhooks/:code
/admin/webhooks/:code/events
```

第一版 UI 只允许绑定 `default-diagnostic-agent` 的已发布版本，但 API/表结构使用通用 agent code/publication ID。

### 11. 事件记录只保存诊断所需的最小数据

`webhook_event.normalized_event_json` 只包含已声明提取字段、受控 routing、生成后的 bounded message 和固定 route 引用；`safe_summary_json` 使用统一脱敏并限制大小。原始 body 不写数据库、日志、审计、RabbitMQ 或 Agent artifact。

事件状态至少包括：

```text
REJECTED_AUTH
IGNORED
ACCEPTED
DISPATCH_PENDING
JOB_CREATED
DISPATCH_FAILED
```

Agent 执行和 Delivery 状态通过关联的 `agent_job`、`audit_event`、`delivery_attempt` 展示，不复制整份报告。事件保留期由非敏感 runtime config 管理，清理不删除关联 job/audit 的事实。

### 12. 兼容旧 Grafana 路由并逐步迁移

部署时创建一个等价的默认 Grafana Trigger publication 和专用服务账号。旧 `/webhooks/grafana/alert` controller 暂时保留，但只负责把请求转发到同一 `WebhookIngressService`，不再维护独立映射逻辑；响应格式保持兼容并增加弃用提示。管理员验证新 public URL 后可切换 Grafana Contact Point。

本 change 不删除旧路由；未来移除必须另立带 BREAKING 标记的 change。

## Risks / Trade-offs

- [映射错误导致 Agent 调查错误范围] → routing fixed/allowlist、发布前 sample preview、字段级校验、Trigger publication 固定和 job 中保留版本证据。
- [Webhook 告警风暴耗尽 Agent worker] → 每 Trigger 限流与并发上限、group 级幂等、冷却窗口、数据库 Inbox 削峰和现有 RabbitMQ prefetch。
- [HMAC 实现与厂商签名格式不一致] → 第一版提供平台统一 HMAC 规范；厂商特殊算法通过后续 typed adapter 增加，不允许管理员脚本实现。
- [PostgreSQL Inbox/限流增加数据库压力] → 有界索引、按 received_at 清理、只保存摘要、事件列表分页；规模达到明确阈值后再评估 Redis 或专门事件网关。
- [服务账号权限配置过大] → 一 Trigger 一账号、默认无权限、deny 优先、发布前权限预检、事件页展示有效授权摘要。
- [Trigger 固定 Agent publication 导致 Agent 升级不自动生效] → 这是可复现性的有意取舍；UI 提示 Agent 有新版本并引导创建新 Trigger revision。
- [旧 Grafana 路由和新入口行为漂移] → 旧 controller 只做兼容参数转换并调用同一应用服务，测试两条 URL 产生等价 event/job。
- [Outbox/dispatcher 增加运行组件] → 复用现有 RabbitMQ 连接与 worker 部署模式，队列只承载 event ID；提供数据库恢复扫描和积压指标。
- [安全摘要仍可能含业务敏感字段] → 默认仅保存显式提取字段，统一 key/value 脱敏、长度限制、管理端 RBAC 和可配置短保留期。

## Migration Plan

1. 先确认统一身份/RBAC、默认 Agent publication 和现有 Channel/Delivery migrations 已部署，并记录当前 Grafana connector、权限和 Delivery 配置。
2. 以加法 migration 创建 Trigger/revision/publication/event/nonce/outbox 数据结构，为 `app_user` 增加 account type，并为 job 增加可空的 Webhook 来源引用；旧 job 不回填伪造来源。
3. Seed 专用 Grafana 服务账号、最小权限、默认 Trigger 和 publication；从现有 connector secret reference、`ea_*` routing 和钉钉 Delivery 生成兼容快照，不复制 secret 明文。
4. 部署 Webhook ingress、outbox publisher、dispatcher 和管理 API；旧 Grafana route 切换为调用同一应用服务，新 public route 暂不对外切流。
5. 部署 Web UI，使用脱敏 fixture 完成 preview、firing、resolved、重复投递、限流、认证失败、Agent job 和钉钉投递验证。
6. 在 Grafana Contact Point 切换到新 public URL，小流量观察 webhook event、RabbitMQ、job、tool call 和 delivery 指标；确认稳定后停用旧兼容配置但保留路由代码。
7. 回滚时将 Grafana Contact Point 切回旧 URL并停用新 Trigger；加法表和可空列保留，避免删除事件/job 审计证据。应用版本回滚不得要求降级数据库或删除新表。

## Open Questions

- 当前没有阻塞 proposal 的问题。第一版固定采用 firing-only、一个 Grafana group 一个 job、Bearer/HMAC 两种认证、专用服务账号、固定 Delivery 和现有只读工具。
- 厂商专用适配器、动态目标 profile、CloudEvents、mTLS、Redis 限流和动态只读 HTTP API 工具均在实际接入需求或规模指标出现后另立 change。
