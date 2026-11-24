# Webhook Agent Trigger

## 链路边界

Webhook 复用统一 Channel / Job / Delivery 链路，不另建第二套 Agent 执行或结果投递实现：

```text
POST /webhooks/v1/{public_id}
  -> WebhookIngressService（认证、映射、限流、去重）
  -> 持久化 webhook_event / webhook_outbox
  -> Webhook dispatcher（消息含 webhook_event_id / correlation_id）
  -> ChannelIngressService
  -> CreateAgentJobService（Agent 来自业务应用活动 Publication）
  -> RabbitMQ agent job queue（消息含 job_id / correlation_id / event_id）
  -> Agent worker / 现有只读工具
  -> ResultDeliveryService / delivery_attempt / chunks
```

`app.modules.webhook` 只负责 Trigger 配置、公共入口认证、固定适配器映射、Inbox/Outbox 与 dispatcher。它可以调用 `ChannelIngressService`，但不得直接导入 Agent executor、内部工具实现或 Delivery adapter。

现有 connector 兼容输入：

- `connector-grafana-default`：Grafana ingress；凭证必须是凭据中心引用，本地测试值不得当作生产值。
- `connector-debug-api`：受控标准化调试入口，不是公开匿名 Webhook。
- `connector-dingtalk-stream-default`：钉钉 Stream ingress。
- `connector-dingtalk-enterprise-default`、`connector-dingtalk-webhook-default`：结果 Delivery 连接器。

结果投递、入口与 Agent 的装配见 [Business Application 控制面](business-application-control-plane.md)；Webhook Trigger 本身不保存投递目标。

## 执行主体

- 执行主体是 Trigger 发布快照中的 `execution_user_id`：必须是已启用的 `account_type=human` 用户。
- 新建 Webhook 不会自动创建服务账号；管理端从启用 human 用户目录中选择执行用户。
- 业务应用入口绑定 Webhook 时使用 `actor_policy=BOUND_USER`，执行用户与 Trigger 发布保持一致；应用不能另写执行用户。
- 外部 payload 不能覆盖执行用户、Agent、工具、Connector、secret 或 Delivery target。
- 执行用户停用后，入口不可用；重发请求或仅启用 Trigger 不会自动恢复主体。

## 配置与发布冻结面

当前固定名称：

- Trigger schema / adapter：`grafana_alertmanager_v1`、`generic_json_v1`
- 配置契约：`schema_version=3`
- 认证：`none`、`bearer_v1`
- 事件状态：`REJECTED_AUTH`、`REJECTED`、`IGNORED`、`ACCEPTED`、`DISPATCH_PENDING`、`JOB_CREATED`、`DISPATCH_FAILED`
- RabbitMQ queue：`agent.webhook.dispatch.queue`；死信默认 `agent.webhook.dispatch.dead.queue`
- 管理资源：`webhook_trigger`
- 管理 actions：`read`、`edit`、`publish`、`rotate`

Trigger 发布只固定：

1. `schema_version=3`
2. adapter（与 Trigger 类型匹配）
3. 源连接器（`source_connector_id` / definition `connector_id`）
4. 执行用户（`execution_user_id`）
5. 认证（`authentication.type` / `secret_ref`）

不包含 Agent、结果投递或自定义映射。Agent Publication 与按入口的结果投递由业务应用活动 Publication 提供；同一 Webhook 入口在 `per_trigger` 模式下至多配置一个投递。

保存草稿不等于可接收；须校验、发布，再启用。启用要求当前发布有效，且源连接器与执行用户可用。

## 认证

- 仅当发布配置显式 `authentication.type=none` 且无凭据引用时，入口免鉴权。
- 否则按 `bearer_v1` 校验 `Authorization: Bearer <token>`。
- Bearer 明文规则：长度 1–4096 字节、可打印 ASCII、无空白；**没有**强制 32 字符下限。
- 启用中的 binding 之间 Bearer Token（含相同 secret 引用或相同解析值）必须唯一。
- `secret_ref` 必须是凭据中心引用（如 `secret://platform/...`）；`env:` 不可直接作为运行引用，须先受控导入。Trigger snapshot 不保存明文 Token。
- 当前应用层只实现 Bearer / 显式免鉴权，不实现 HMAC、timestamp 或 nonce。
- 源连接器或 Bearer Secret 缺失、停用或无法解析时，渠道面可显示为 `MISCONFIGURED`；入口返回通用不可用/认证失败，且不会创建可执行 Inbox 事件。修复方式是重新绑定 Secret、重新验证并发布 Trigger，再做渠道“测试配置”；不得生成临时 Token、使用空值或绕过认证。

## 公共入口

- 入口：`POST /webhooks/v1/{public_id}`。
- 旧 `/webhooks/grafana/alert`、`X-Grafana-Token` 翻译和未绑定的 `/webhooks/channel/agent` 已删除。
- `202 Accepted` 仅表示事件与 outbox 已在 PostgreSQL 中持久受理；不表示 Agent 已执行完成。
- 调用方不得因超时自行改写 event ID；相同稳定身份在冷却窗口内重复发送会落到同一 dedup，返回既有 event。
- 只使用代码注册、并由 Agent / Application Publication 冻结的 MCP Tool；没有动态 HTTP API Tool、Handler 或任意 Server 配置。

代码常量限流与去重（非环境变量）：

- 冷却去重窗口：`300` 秒
- 每 Trigger 请求上限：`60` / 分钟
- 在途事件上限：`10`（状态为 `ACCEPTED` / `DISPATCH_PENDING`）
- Grafana 单次 alerts 上限：`20`

超限记为 `REJECTED`（如 `webhook_rate_limited`），不创建 Job。

## Grafana Alertmanager

适配器：`grafana_alertmanager_v1`。

- 只对 `status=firing` 创建 Agent Job。
- `resolved` 持久为 `IGNORED`，HTTP `200` 且 `ignored=true`，不建 Job。
- 稳定身份优先 `groupKey`，否则用 fingerprint 集合哈希；同一冷却窗口内同一稳定身份只受理一次。
- payload 中的 `ea_*` labels（如 `ea_project_code`、`ea_environment`、`ea_base`、`ea_workshop`、`ea_service`）仅进入脱敏摘要，**不**作为授权或路由依据。

Grafana Contact Point：

- URL：管理端发布后显示的 `/webhooks/v1/{public_id}`
- 方法：`POST`，`Content-Type: application/json`
- Bearer 模式：`Authorization: Bearer <从密钥系统注入的值>`

本地脱敏 smoke：

```bash
curl -i \
  -H 'Content-Type: application/json' \
  -H "Authorization: Bearer ${GRAFANA_WEBHOOK_TOKEN}" \
  --data-binary @backend/tests/fixtures/webhooks/grafana_firing.json \
  http://127.0.0.1:8000/webhooks/v1/<public_id>
```

Compose 的 HTTP 入口只适合本地功能验证，不能表述为公网生产安全；仓库代码也未提供生产 TLS 终止。

## 通用 JSON

适配器：`generic_json_v1`。

正文必须恰好是两个字段的 JSON 对象：

- `id`：非空字符串，最长 512
- `message`：非空字符串，最长 4000（与 `WEBHOOK_MAX_MESSAGE_CHARS` 默认一致）

不支持 JSON Pointer、条件表达式、声明变量或模板映射。额外字段、空字符串或超长值一律映射失败并 `REJECTED`。管理端 preview 只做映射预览，不写 event、不投队列、不创建 job。

## 安全与排障证据

原始 body、Bearer secret 和完整 Webhook URL 不得进入数据库、RabbitMQ、普通日志或 Agent prompt。事件只保存 payload hash、请求大小、显式提取字段和脱敏有界摘要。

安全负路径只记录 public ID hash、payload hash、大小、error code 和远端地址 hash。普通日志、数据库和队列不得出现原始 Authorization、签名、完整 endpoint 或 payload 正文。

排障顺序：

```text
webhook_event auth/filter/status
  -> webhook_outbox status/attempt
  -> webhook dispatch queue
  -> agent_job status / application publication
  -> agent_tool_call / audit_event
  -> delivery_attempt / chunks
```

## 启动与配置顺序

1. 启用 ingress Connector；若使用 Bearer，为每个 binding 配置独立的凭据中心 Secret 引用。当前 local seed 示例使用 `secret://platform/grafana_webhook_token`。
2. 启动 `api-server`、`rabbitmq`、`agent-worker`、`webhook-worker` 以及结果投递所需的固定 Delivery 配置。
3. 在“渠道与触发器”（`/applications/channels`）新建 Webhook，选择启用 human 执行用户、适配器与认证；可先保留草稿。
4. 校验、预览并发布 Trigger，再启用接收。
5. 在业务应用中绑定该入口、选择 Agent Publication，并按入口配置至多一个结果投递；发布并激活应用。执行授权落在绑定的 human 用户上，而不是钉钉机器人或结果接收人。
6. Trigger、源连接器、执行用户与发布版本有效时才允许受理；Dispatcher 仍须通过当前业务应用路由与授权检查才能创建 Job。

## 运维与故障恢复

- `webhook_event` 是 Inbox 事实，`webhook_outbox` 是可靠发布事实；RabbitMQ 消息只有 `webhook_event_id` 和 `correlation_id`。
- publisher confirm 失败时 outbox 指数退避；超过 `WEBHOOK_OUTBOX_MAX_ATTEMPTS` 后进入 `dead`，事件变为 `DISPATCH_FAILED`，并在事件页可见。现行实现**没有**把 dead 记录人工重放为 `pending` 的运维动作；恢复应先处理配置或连接问题，再依赖新请求或未耗尽重试的 pending 记录。
- `publishing` 状态若卡住约 5 分钟，publisher 会将其收回为 `pending` 后再次认领。
- dispatcher 重投递先检查 event 是否已有 job；Delivery 失败只重试投递，不重新运行 Agent。
- 无 job 的 `REJECTED` / `REJECTED_AUTH` / `IGNORED` / `DISPATCH_FAILED` 事件按 `WEBHOOK_EVENT_RETENTION_DAYS` 清理；已有 job / audit / delivery 证据不级联删除。
- Trigger 列表返回最近事件状态及累计 accepted / rejected / failed 计数；当前不依赖额外 Prometheus 指标，事件详情和结构化日志用于继续下钻。

常用检查：

```bash
docker compose ps
docker compose logs --tail=200 api-server webhook-worker agent-worker rabbitmq
docker compose exec rabbitmq rabbitmq-diagnostics check_running
docker compose exec rabbitmq rabbitmqctl list_queues name messages_ready messages_unacknowledged
```
