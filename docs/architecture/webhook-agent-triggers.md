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

现有统一身份/RBAC提供 `app_user`、角色、管理能力、业务应用访问、应用内 MCP Tool
identifier/data scope 和 Web Session。Webhook 使用 `account_type=service` 的专用内部账号
复用这些权限，不使用可伪造的固定字符串主体。

现有 connector 兼容输入：

- `connector-grafana-default`：Grafana ingress，凭证必须迁移为 secret reference；本地测试值不得作为生产值。
- `connector-debug-api`：受控标准化调试入口，不是公开匿名 Webhook。
- `connector-dingtalk-stream-default`：钉钉 Stream ingress。
- `connector-dingtalk-enterprise-default`、`connector-dingtalk-webhook-default`：固定结果 Delivery。

## 新模块边界

`app.modules.webhook` 只负责 Trigger 配置、公共请求认证、声明式映射、Inbox/Outbox 和 dispatcher。它可以调用 `ChannelIngressService`，但不得直接导入 Agent executor、内部工具实现或 Delivery adapter。

当前固定名称：

- Trigger schema：`grafana_alertmanager_v1`、`generic_json_v1`
- 认证：仅 `bearer_v1`
- 事件状态：`REJECTED_AUTH`、`IGNORED`、`ACCEPTED`、`DISPATCH_PENDING`、`JOB_CREATED`、`DISPATCH_FAILED`
- RabbitMQ queue：`agent.webhook.dispatch.queue`、`agent.webhook.dead.queue`
- 管理资源：`webhook_trigger`
- 管理 actions：`read`、`edit`、`publish`、`rotate`、`manage_service_account`

## 入口规则

- 新入口为 `POST /webhooks/v1/{public_id}`。
- 旧 `/webhooks/grafana/alert`、`X-Grafana-Token` 翻译和未绑定的
  `/webhooks/channel/agent` 已删除。
- Grafana 只处理 `firing`；`resolved` 只记录为 ignored。
- 一个 `groupKey` 或稳定 fingerprint group 只创建一个 job。
- 外部 payload 不能覆盖服务账号、Agent、工具、Connector、secret 或 Delivery target。
- 只使用代码注册并由 Agent/Application Publication 冻结的 MCP Tool；当前没有动态
  HTTP API Tool、Handler 或任意 Server 配置。

## 安全与排障证据

原始 body、Bearer secret 和完整 Webhook URL 不得进入数据库、RabbitMQ、普通日志或 Agent prompt。事件只保存 payload hash、请求大小、显式提取字段和脱敏有界摘要。

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

1. 启用 ingress Connector，并为每个 binding 配置独立、至少 32 字符的高熵
   Bearer Token 引用。当前新配置和 local seed 都使用
   `secret://platform/grafana_webhook_token`；`env:` 不可直接作为运行引用，必须先受控
   导入凭据中心。Trigger snapshot 不保存明文值。
2. 启动 `api-server`、`rabbitmq`、`agent-worker`、`webhook-worker` 和固定 Delivery 所需配置。
3. 在“渠道与触发器”（`/applications/channels`）新建 Webhook，自动创建不可登录的 `account_type=service` 执行账号。新建流程允许先保留未完成草稿；保存不等于可接收或可执行。
4. 在 Agent 配置中分配这个 Webhook 入口及所需投递渠道并发布，回到 Webhook 选择该 Agent 版本，配置映射、凭据引用与结果接收人，完成校验/预览并发布，再启用接收。
5. 在业务应用中绑定该入口及投递策略，发布并激活；给服务账号分配业务角色、应用访问、工具和数据范围。服务账号是执行主体，不是钉钉机器人，也不是结果接收人，不能用个人外部身份绑定来代替授权。
6. Trigger、来源 Connector、服务账号和发布版本有效时才允许受理；受理后 Dispatcher 仍须通过当前业务应用路由与授权检查才能创建 Job。旧服务账号若已停用，不会因重发请求或启用 Trigger 自动恢复，应核对独立账号状态。

如果 source Connector 或发布 binding 的 Bearer Secret 缺失、停用或无法解析，
管理端将其显示为 `MISCONFIGURED`，入口返回通用不可用/认证失败响应且不会创建
Inbox 事件。修复时重新绑定平台 Secret、重新验证并发布 Trigger，再执行渠道
“测试配置”；不得生成临时 Token、使用空值或绕过认证。

`202 Accepted` 只表示事件和 outbox 已在 PostgreSQL 中持久化，Agent 尚不一定执行完成。调用方不得因超时自行改写 event ID；重复发送相同稳定身份会返回同一个 event。

## 钉钉多接收人结果投递

选择“钉钉机器人（多个接收人）”时，Trigger 发布保存 1–20 个接收人，每项包含机器人 Connector、目标类型 `group`/`user`、目标 ID 和可选备注。群填写 `openConversationId`，个人填写对应机器人企业内的 `userId`；同一机器人下的相同类型/目标不能重复，不接受 URL。

先在渠道页面配置并启用应用机器人，在 Agent 发布中分配这些机器人的投递权限；业务应用投递绑定选择“使用 Webhook 配置的接收人”，连接器选择该 Webhook 入口。接收人来自冻结的 Trigger 发布，外部 payload 不能增加或改写目标。

Agent 只执行一次，结果按接收人分别记录投递进度；单个目标失败只重试其投递，不重新运行 Agent 或重发已经完成的目标。验收需逐个核对实际接收结果，Webhook `202`、Job 成功或机器人容器健康均不能单独证明全部投递完成。

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

当前应用层只实现 Bearer，不实现 HMAC、timestamp 或 nonce。Compose 的 HTTP 入口只适合
本地功能验证，不能表述为公网生产安全；仓库代码也未提供生产 TLS 终止。

## 通用 JSON Trigger

`generic_json_v1` 只支持 JSON Pointer、`exists/equals/in/not_equals` 的 AND 条件、声明变量和有界模板。动态 scope 只能使用 `extract + allowed_values`，外部 payload 中的 Agent、tool、connector、URL、token 或 Delivery target 字段不会覆盖 publication snapshot。

示例 fixture 位于 `backend/tests/fixtures/webhooks/generic_event.json`。管理端 preview 不写 event、不投队列、不创建 job。

## 运维与故障恢复

- `webhook_event` 是 Inbox 事实，`webhook_outbox` 是可靠发布事实；RabbitMQ 消息只有 `webhook_event_id` 和 `correlation_id`。
- publisher confirm 失败时 outbox 指数退避；超过 `WEBHOOK_OUTBOX_MAX_ATTEMPTS` 后进入 `dead` 并在事件页可见。恢复 RabbitMQ 后，先处理配置或连接问题，再将经审核的 dead 记录重新置为 pending。
- dispatcher 重投递先检查 event 是否已有 job；Delivery 失败只重试投递，不重新运行 Agent。
- 无 job 的 rejected/ignored/dispatch-failed 事件按 `WEBHOOK_EVENT_RETENTION_DAYS` 清理，已有 job/audit/delivery 证据不级联删除。
- 安全负路径只记录 public ID hash、payload hash、大小、error code 和远端地址 hash。普通日志、数据库和队列不得出现原始 Authorization、签名、完整 endpoint 或 payload 正文。
- Trigger 列表返回最近事件状态及累计 accepted/rejected/failed 计数；当前不依赖额外
  Prometheus 指标，事件详情和结构化日志用于继续下钻。

常用检查：

```bash
docker compose ps
docker compose logs --tail=200 api-server webhook-worker agent-worker rabbitmq
docker compose exec rabbitmq rabbitmq-diagnostics check_running
docker compose exec rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged
```
