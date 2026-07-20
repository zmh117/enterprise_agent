# Web 管理 Webhook Agent Trigger

## 现有可复用链路

本功能必须复用以下稳定边界，不建立第二套 Agent 执行或结果投递实现：

```text
WebhookIngressService
  -> 持久化 webhook_event / webhook_outbox
  -> Webhook dispatcher（仅传 event_id/correlation_id）
  -> ChannelIngressService
  -> CreateAgentJobService（固定 Agent publication）
  -> RabbitMQ agent job queue（仅传 job_id/correlation_id）
  -> Agent worker / 现有只读工具
  -> ResultDeliveryService / delivery_attempt / chunks
```

现有统一身份/RBAC提供 `app_user`、角色、permission policy、平台范围 grant和管理 session；默认诊断 Agent 已提供 definition、revision、publication、工具/Skill/Channel binding。Webhook 使用 `account_type=service` 的专用内部账号复用这些权限，不再使用可伪造的固定字符串 `grafana`。

现有 connector 兼容输入：

- `connector-grafana-default`：Grafana ingress，凭证必须迁移为 secret reference；本地测试值不得作为生产值。
- `connector-debug-api`：受控标准化调试入口，不是公开匿名 Webhook。
- `connector-dingtalk-stream-default`：钉钉 Stream ingress。
- `connector-dingtalk-enterprise-default`、`connector-dingtalk-webhook-default`：固定结果 Delivery。

## 新模块边界

`app.modules.webhook` 只负责 Trigger 配置、公共请求认证、声明式映射、Inbox/Outbox 和 dispatcher。它可以调用 `ChannelIngressService`，但不得直接导入 Agent executor、内部工具实现或 Delivery adapter。

第一版固定名称：

- Trigger schema：`grafana_alertmanager_v1`、`generic_json_v1`
- 认证：`bearer_v1`、`hmac_sha256_v1`
- 事件状态：`REJECTED_AUTH`、`IGNORED`、`ACCEPTED`、`DISPATCH_PENDING`、`JOB_CREATED`、`DISPATCH_FAILED`
- RabbitMQ queue：`agent.webhook.dispatch.queue`、`agent.webhook.dead.queue`
- 管理资源：`webhook_trigger`
- 管理 actions：`read`、`edit`、`publish`、`rotate`、`manage_service_account`

## 兼容规则

- 新入口为 `POST /webhooks/v1/{public_id}`。
- 旧 `/webhooks/grafana/alert` 保留，并委托同一 WebhookIngressService。
- Grafana 只处理 `firing`；`resolved` 只记录为 ignored。
- 一个 `groupKey` 或稳定 fingerprint group 只创建一个 job。
- 外部 payload 不能覆盖服务账号、Agent、工具、Connector、secret 或 Delivery target。
- 第一版只使用代码注册的现有只读工具；动态 HTTP API 工具另立 change。

## 安全与排障证据

原始 body、Bearer/HMAC secret、签名原文和完整 Webhook URL不得进入数据库、RabbitMQ、普通日志或 Agent prompt。事件只保存 payload hash、请求大小、显式提取字段和脱敏有界摘要。

排障顺序：

```text
webhook_event auth/filter/status
  -> webhook_outbox status/attempt
  -> webhook dispatch queue
  -> agent_job status/publication
  -> agent_tool_call / audit_event
  -> delivery_attempt / chunks
```

## 启动和发布

1. 在 `.env` 设置 `FEATURE_WEBHOOK_TRIGGERS=true`，并为 connector 的 `secret_ref` 提供真实 secret。默认 Grafana connector 引用 `env:GRAFANA_WEBHOOK_TOKEN`，SQL seed 和 Trigger snapshot 均不保存值。
2. 启动 `api-server`、`rabbitmq`、`agent-worker`、`webhook-worker` 和固定 Delivery 所需配置。
3. 管理员在 `/admin/webhooks` 创建草稿，完成 preview、validate 后再 publish。新 Trigger 会创建一个不可登录的 service account；需通过统一 RBAC 明确授予 Agent、project、工具和平台数据范围。
4. 只有已启用 Trigger、已启用 service account、已发布 Trigger revision 和固定 Agent publication 同时有效时，公共 URL 才接受事件。

`202 Accepted` 只表示事件和 outbox 已在 PostgreSQL 中持久化，Agent 尚不一定执行完成。调用方不得因超时自行改写 event ID；重复发送相同稳定身份会返回同一个 event。

## Grafana Contact Point

URL 使用管理端发布后显示的 `/webhooks/v1/{public_id}`，方法为 POST，Content-Type 为 `application/json`。Bearer 模式添加：

```text
Authorization: Bearer <从密钥系统注入的值>
```

Grafana payload 必须提供允许范围内的 `ea_project_code`、`ea_environment`、`ea_base`、`ea_workshop`、`ea_service` labels。只处理 `status=firing`；`resolved` 返回 `200` 和 `ignored=true`，不会创建 Agent job。

本地脱敏 smoke：

```bash
curl -i \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${GRAFANA_WEBHOOK_TOKEN}" \
  --data-binary @backend/tests/fixtures/webhooks/grafana_firing.json \
  http://127.0.0.1:8000/webhooks/v1/<public_id>
```

旧 `/webhooks/grafana/alert` 仍委托同一 ingress service，响应带弃用提示；回退时可以短期恢复旧 Contact Point，但不能绕开受管 Trigger。

## HMAC-SHA256 规范

请求头默认使用：

```text
X-Webhook-Timestamp: Unix 秒
X-Webhook-Nonce: 调用方生成的单次随机值
X-Webhook-Signature: 十六进制小写 HMAC-SHA256
```

签名输入是原始字节，不能先解析再序列化：

```text
canonical = timestamp ASCII bytes + "." + exact raw request body bytes
signature = hex(HMAC-SHA256(secret, canonical))
```

时间戳超出 Trigger 窗口、nonce 重复、secret 无法解析或签名不一致都会拒绝，且不会建立第二个 event/job。验证 HMAC 时必须让发送程序直接读取 fixture 字节；不要用会改变空白或换行的 JSON 格式化工具。

## 通用 JSON Trigger

`generic_json_v1` 只支持 JSON Pointer、`exists/equals/in/not_equals` 的 AND 条件、声明变量和有界模板。动态 scope 只能使用 `extract + allowed_values`，外部 payload 中的 Agent、tool、connector、URL、token 或 Delivery target 字段不会覆盖 publication snapshot。

示例 fixture 位于 `backend/tests/fixtures/webhooks/generic_event.json`。管理端 preview 不写 event、不投队列、不创建 job。

## 运维与故障恢复

- `webhook_event` 是 Inbox 事实，`webhook_outbox` 是可靠发布事实；RabbitMQ 消息只有 `webhook_event_id` 和 `correlation_id`。
- publisher confirm 失败时 outbox 指数退避；超过 `WEBHOOK_OUTBOX_MAX_ATTEMPTS` 后进入 `dead` 并在事件页可见。恢复 RabbitMQ 后，先处理配置或连接问题，再将经审核的 dead 记录重新置为 pending。
- dispatcher 重投递先检查 event 是否已有 job；Delivery 失败只重试投递，不重新运行 Agent。
- HMAC nonce 按到期时间清理；无 job 的 rejected/ignored/dispatch-failed 事件按 `WEBHOOK_EVENT_RETENTION_DAYS` 清理，已有 job/audit/delivery 证据不级联删除。
- 安全负路径只记录 public ID hash、payload hash、大小、error code 和远端地址 hash。普通日志、数据库和队列不得出现原始 Authorization、签名、完整 endpoint 或 payload 正文。
- Trigger 列表返回最近事件状态及累计 accepted/rejected/failed 计数，作为第一版无额外 Prometheus 依赖的运维指标；事件详情和结构化日志用于继续下钻。

常用检查：

```bash
docker compose ps
docker compose logs --tail=200 api-server webhook-worker agent-worker rabbitmq
docker compose exec rabbitmq rabbitmq-diagnostics check_running
docker compose exec rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged
```
