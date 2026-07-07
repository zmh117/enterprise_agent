## Context

当前后端已经形成只读诊断 Agent 的主链路：

```text
DingTalk / Debug API
  -> FastAPI api-server
  -> PostgreSQL agent_session / agent_job / agent_message
  -> RabbitMQ agent.job.queue
  -> agent-worker
  -> Claude Code Agent Runtime
  -> Internal API Platform read-only tools
  -> report / steps / tool-calls / audit
  -> DingTalk callback
```

这个链路的执行、重试、审计和只读工具边界是正确的，但入口和出口仍被 DingTalk 命名和 DingTalk callback client 固定住：

- `CreateAgentJobCommand` 直接接收 `dingding_conversation_id` / `dingding_user_id`。
- `agent_session` 表直接存 DingTalk conversation/user 字段。
- `AgentExecutor` 成功后直接发送 DingTalk markdown。
- `AgentJobWorker` dead-letter 后直接发送 DingTalk failure notice。

新需求要求 DingTalk 应用、DingTalk webhook 机器人、DingTalk 企业机器人、Grafana alert webhook、email 等都能作为入口或出口，并且通过请求报文里的 `from` 与 `delivery` 字段区分。Grafana 只处理 `firing` 告警，环境/基地/车间/服务映射使用专用 label 字段。长报告先采用分片发送。

## Goals / Non-Goals

**Goals:**

- 建立通用 Channel 入站契约，支持 `from`、`delivery`、`routing`、`message` 的稳定请求模型。
- 让 DingTalk 企业机器人、DingTalk webhook 机器人、Grafana alert webhook、email/debug 等入口通过 adapter 归一化为同一种 Agent job 创建命令。
- 建立通用 Result Delivery 契约，支持 DingTalk webhook 机器人、DingTalk 企业机器人、email、generic webhook、none 等投递方式。
- 支持同一个 connector 配置 ingress、delivery 或两者都允许。
- 将 Agent session/job 从 DingTalk 专用字段迁移到通用 source channel、requester、external event/conversation、reply route。
- 保持 RabbitMQ 只作为内部任务基础设施，队列消息仍只携带 `job_id` 和 `correlation_id`。
- Delivery 失败或单个分片失败不重新执行 Agent，只记录投递状态并按 Delivery 策略重试。
- 保持只读诊断边界，不新增任何写操作、自动修复或生产变更能力。

**Non-Goals:**

- 不把 RabbitMQ 暴露为外部服务接入协议；外部系统通过 HTTP webhook/API 接入。
- 不实现 Web 管理后台；connector 可先通过 migration seed、配置文件或环境变量初始化。
- 不实现完整 email 收信服务；email 可作为 delivery adapter，email ingress 可作为预留或最小可测 adapter。
- 不实现审批、取消任务、人工接管、多轮长期会话或 Agent 主动订阅。
- 不改变 Claude runtime 和 Internal API Platform 的只读工具契约。

## Decisions

### 1. 用 ChannelEvent 作为入口归一化边界

每个入口 adapter 只负责把外部 payload 变成内部 `ChannelEvent`：

```text
DingTalk/Grafana/Debug/Email payload
  -> adapter verify / parse / normalize
  -> ChannelEvent
  -> CreateAgentJobService
  -> persisted job
  -> RabbitMQ job_id
```

建议内部 DTO：

```text
ChannelEvent
  source_type
  source_connector_id
  external_event_id
  external_conversation_id
  requester_id
  message
  routing
  delivery
  raw_payload_summary
  idempotency_key
  correlation_id
```

`CreateAgentJobCommand` 应从 DingTalk 专用命名演进为：

```text
CreateAgentJobCommand
  idempotency_key
  requester_id
  requester_display_name?
  source_channel
  source_connector_id?
  external_event_id?
  external_conversation_id?
  user_message
  project_code
  routing_context
  reply_route
  correlation_id?
```

替代方案：继续在每个入口里直接调用现有 `CreateAgentJobCommand`，只把 `dingding_*` 字段塞成 Grafana/email 的值。这个方案短期改动小，但会让数据库、审计、权限和投递都持续误用 DingTalk 语义，后续新增 Channel 会越来越难维护。

### 2. `from` 和 `delivery` 是两个独立概念

外部请求契约应显式区分来源和投递目标：

```json
{
  "from": {
    "type": "grafana_alert",
    "connector_id": "grafana-prod",
    "event_id": "group-key-or-fingerprint",
    "actor_id": "grafana",
    "metadata": {"status": "firing"}
  },
  "delivery": {
    "type": "dingtalk_webhook_robot",
    "connector_id": "ops-alert-robot",
    "target": {"webhook_id": "ops-alerts"}
  },
  "routing": {
    "project_code": "default",
    "environment": "prod",
    "base": "guanlan",
    "workshop": "GL001",
    "service": "order-service"
  },
  "message": "告警内容或用户问题"
}
```

这样 Grafana 可以作为入口、DingTalk 作为出口；DingTalk 可以作为入口、email 作为出口；Debug API 可以使用 `delivery.type=none`。

替代方案：以 Channel 类型决定默认回调目标，例如 Grafana 永远发 DingTalk、DingTalk 永远回原会话。这个方案无法表达跨平台投递，也不满足用户要求的 `from` / `delivery` 字段区分。

### 3. 新增 `channel` 与 `delivery` 模块，避免污染 Agent runtime

建议模块边界：

```text
backend/app/modules/
  channel/
    api/
      channel_webhook_controller.py
      grafana_webhook_controller.py
    application/
      channel_ingress_service.py
      channel_event_mapper.py
    domain/
      channel_event.py
      reply_route.py
      routing_context.py
    infrastructure/
      connector_registry.py
      signature_verifier.py
  delivery/
    application/
      result_delivery_service.py
      report_chunker.py
    domain/
      delivery_attempt.py
      delivery_status.py
    infrastructure/
      dingtalk_robot_client.py
      dingtalk_enterprise_client.py
      email_client.py
      webhook_client.py
```

`dingding` 模块可以保留具体 DingTalk 适配逻辑，也可以逐步迁到 `channel` / `delivery` 下。关键是 AgentExecutor 不再 import DingTalk client。

替代方案：在现有 `dingding` 模块里继续加 Grafana/email。这个方案会让 DingTalk 模块变成泛集成模块，命名和边界都不准确。

### 4. ResultDeliveryService 接管成功、失败和长报告分片

成功路径：

```text
AgentExecutor
  -> save result/artifact/messages
  -> mark SUCCEEDED
  -> ResultDeliveryService.deliver_job_result(job_id)
```

失败 dead-letter 路径：

```text
AgentJobWorker
  -> retry_service.handle_failure(...)
  -> if dead:
       ResultDeliveryService.deliver_job_failure(job_id, safe_message)
```

Delivery 层负责：

- 读取 job/session/reply_route。
- 按 delivery type 选择 adapter。
- 按目标平台字符限制分片。
- 记录 `delivery_attempt` 和 `delivery_chunk`。
- 失败时按 delivery 策略重试或标记 delivery failed。

Agent job 状态表示 Agent 执行结果；Delivery 状态表示结果投递结果。二者不能混为一谈。

替代方案：让 AgentExecutor 直接根据 `delivery.type` if/else 调不同 client。这个方案会把外部平台细节带回 Agent runtime，违背模块边界。

### 5. Grafana adapter 只接受 `firing`

Grafana webhook adapter 行为：

```text
if status != "firing":
  record audit_event: channel.grafana.ignored
  return accepted=false or ignored=true
  do not create Agent job

if status == "firing":
  extract dedicated labels
  build diagnostic message
  create idempotency key
  create Agent job
```

推荐专用 label：

```text
ea_project_code
ea_environment
ea_base
ea_workshop
ea_service
ea_delivery_connector_id
ea_delivery_type
```

`event_id` 优先使用 Grafana `fingerprint`、`groupKey` 或外部请求提供的稳定 ID。幂等键建议：

```text
grafana:{connector_id}:{fingerprint_or_group_key}:firing
```

替代方案：对 `resolved` 也触发 Agent 生成恢复报告。用户已明确只处理 `firing`，所以恢复事件只审计不建 job。

### 6. Connector 配置控制入口和出口方向

Connector 记录应至少表达：

```text
connector_id
connector_type
enabled
allow_ingress
allow_delivery
secret_ref / token_ref
endpoint_ref / callback_url_ref
host_allowlist
metadata
created_at / updated_at
```

配置来源可先复用已有 configuration/seed 表，或新增 `channel_connector` 表；敏感值不直接写入 audit payload 或 job metadata。delivery 发送 HTTP 请求前必须执行 host allowlist 或 connector allowlist 校验。

替代方案：继续使用全局 `DINGTALK_CALLBACK_URL` / `DINGTALK_SECRET`。这个方案只能表达一个 DingTalk 目标，无法支持每个请求指定不同 delivery。

### 7. 数据迁移采用兼容字段过渡

建议迁移策略：

1. 新增通用字段，不立即删除旧 DingTalk 字段。
2. 读模型优先读取通用字段；旧记录缺失时从 `dingding_conversation_id` / `dingding_user_id` 回填。
3. 新入口写通用字段；旧 DingTalk endpoint 通过 adapter 写同一套通用字段。
4. 测试和文档稳定后，再考虑后续 change 删除旧字段。

建议新增或演进：

```text
agent_session:
  source_channel
  source_connector_id
  external_conversation_id
  requester_id
  requester_display_name
  routing_context_json
  reply_route_json

agent_job:
  source_channel
  source_connector_id
  external_event_id
  requester_id
  routing_context_json
  reply_route_json

delivery_attempt:
  id
  job_id
  route_type
  connector_id
  target_summary
  status
  error_message
  created_at
  finished_at

delivery_chunk:
  id
  attempt_id
  chunk_index
  chunk_count
  status
  payload_summary
  error_message
  created_at
```

替代方案：一次性重命名旧字段并删除 DingTalk 列。这个方案对现有测试、历史数据和回滚风险太高，不适合作为第一步。

### 8. 权限和审计以 requester + connector 为主

权限检查应同时考虑：

- `requester_id` 是否允许创建 job。
- `source_connector_id` 是否允许 ingress。
- `delivery.connector_id` 是否允许 delivery。
- `project_code` / routing context 是否允许访问。
- Grafana 等机器来源是否使用服务账号权限。

审计事件应覆盖：

```text
channel.received
channel.signature_verified / channel.signature_failed
channel.normalized
channel.ignored
permission.channel_checked
job.created
queue.dispatched
delivery.started
delivery.chunk_sent
delivery.failed
delivery.completed
```

替代方案：只沿用现有 user allowlist。这个方案无法区分“用户有权创建任务”和“这个 connector 是否允许把结果发到某个目标”。

## Risks / Trade-offs

- [Risk] 通用字段和旧 DingTalk 字段并存导致读写不一致 -> 使用明确优先级：新字段优先，旧字段只做 fallback；测试覆盖旧 DingTalk payload。
- [Risk] Delivery 失败被误认为 Agent 失败 -> job status 和 delivery status 分表记录；查询接口清晰展示两种状态。
- [Risk] 长报告分片造成上下文断裂 -> 分片标题带 `part x/y`，第一片包含摘要和 job_id，每片记录 attempt/chunk 序号。
- [Risk] 外部 webhook 重放导致重复 job -> 每个 adapter 必须生成稳定 idempotency key；重复请求返回已有 job 或 ignored 状态。
- [Risk] Grafana label 缺失导致 Agent 查错环境 -> 缺少必填 `ea_*` routing label 时拒绝建 job，返回安全错误并审计。
- [Risk] Connector secret 泄露到审计或日志 -> audit payload 只记录 connector_id 和安全摘要，不记录 token/webhook secret。
- [Risk] 多个 delivery adapter 同步阻塞 worker -> 第一版可同步发送，但必须有超时；后续可把 delivery 单独队列化。
- [Risk] Email delivery 依赖 SMTP/第三方配置不稳定 -> 第一版用接口和 fake adapter 覆盖契约，真实 SMTP 可按配置启用。

## Migration Plan

1. 新增或演进 connector 配置结构，支持 `allow_ingress`、`allow_delivery`、secret ref、endpoint ref 和 host allowlist。
2. 新增通用 session/job 字段和 delivery attempt/chunk 表，保留旧 DingTalk 字段兼容。
3. 新增 Channel domain DTO、ingress service、reply route/routing context parser。
4. 将 Debug API 和现有 DingTalk endpoint 改为通过 Channel ingress service 创建 job。
5. 新增 Grafana webhook endpoint，覆盖 `firing` 建 job、`resolved` ignored、缺少专用 labels 拒绝。
6. 新增 ResultDeliveryService 和 DingTalk webhook/enterprise/email/webhook/none adapter 接口。
7. 将 AgentExecutor 成功回调和 AgentJobWorker dead-letter 回调替换为 ResultDeliveryService。
8. 新增分片发送和 delivery attempt/chunk 持久化。
9. 更新测试、README、curl 示例和 OpenSpec 验证。

Rollback：保留旧 DingTalk 字段和旧 DingTalk adapter 的兼容路径。如果新 Channel/Delivery 装配出现问题，可关闭新 endpoints，继续让 DingTalk adapter 写旧路径；已经执行完成但未投递成功的 job 可通过 delivery attempt 重新投递。

## Open Questions

- Email 第一版是否需要真实 SMTP adapter，还是先保留 fake/接口和配置契约。
- DingTalk 企业机器人和 DingTalk webhook 机器人在当前部署中的验签、access token 获取方式是否完全一致，是否需要两个 connector type。
- Delivery 是否需要独立队列。如果真实平台响应慢或分片多，后续可能需要 `delivery.job.queue`，但第一版可先同步投递并设置超时。
- 查询接口是否需要立即返回 delivery attempts/chunks，还是先只在审计/测试中可见。
