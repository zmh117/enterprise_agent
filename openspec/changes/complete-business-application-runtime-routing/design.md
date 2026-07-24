## Context

业务应用控制面已经具备应用、草稿修订、不可变 Publication、环境 Deployment、Trigger 路由投影和只读 Resolver。钉钉 Stream 入口、统一外部身份、Agent Job、RabbitMQ、Worker 和回复原会话 Delivery 也已经分别可用。

当前实现处于危险的“半接线”状态：

- 管理 API、审计和 Web 将 `runtime_wired` 固定为 `false`；
- Publication snapshot 和 Resolver 却返回 `runtime_wired=true`；
- `FEATURE_PUBLISHED_AGENT_RUNTIME=true` 时，Bootstrap 已把 Business Application Resolver 注入 Channel ingress；
- Channel ingress 只应用 Agent Publication 以及会话策略中的两个布尔字段，没有保存应用、Deployment 或 Route provenance，也没有约束 Delivery；
- 已命中应用时，入口携带的 Agent Publication 仍可覆盖应用 Publication 固定的 Agent；
- 私聊和群聊都使用 `conversation_id` 作为 routing key，导致私聊需要按每个用户会话建路由；
- Resolver 将 `event.routing.environment` 用作应用 Deployment 环境。该字段实际是 `sanjiu` 等数据拓扑环境，而控制面目前只接受 `local/test/staging/production`，会造成运行时配置错误。

因此，本变更不是从零新增 Resolver，而是把已经存在的部分路径收敛为一条真实、可解释、可审计且可回退的数据面契约。

涉及的主要参与方包括：

- 管理员：发布、激活、回退和停用业务应用；
- 钉钉用户：通过私聊或群聊进入 Agent；
- 运维人员：需要判断某条消息是否已被业务应用接管；
- Agent Worker 与 Delivery Worker：必须使用 Job 已固定的配置，不能在执行中重新解析最新配置；
- 后续 Workflow 与 API Capability 建设：需要看到逐组件接线状态，不能被一个含糊布尔值掩盖。

## Goals / Non-Goals

**Goals:**

- 正式接通钉钉 Stream 私聊和群聊到活动 Business Application Publication 的确定性路由。
- 将应用部署环境与业务数据环境分离，避免 `APP_ENV=local` 和 `routing.environment=sanjiu` 混用。
- 定义私聊按 bot identity、群聊按 conversation identity 的稳定路由键。
- 无匹配路由或命中后发生完整性、策略错误时都失败关闭，不再调用默认 Agent。
- 将应用、Publication、Deployment、Trigger route 和解析状态在 Job 创建并入队前持久化。
- 让应用固定的 Agent Publication、受支持 Session Policy 与 Delivery Binding 真正生效，并阻止入口静默覆盖。
- 用逐组件状态和整体状态替代硬编码提示，使管理 API、Web 和审计如实表达“未接线、部分接线、已接线或阻塞”。
- 支持历史 Publication 显式回退、Deployment 停用以及运行记录反查。
- 保持统一身份、RBAC、幂等、快速 ACK、只读 Agent 和投递失败不重跑 Agent 等现有边界。

**Non-Goals:**

- 不接管现有 managed Webhook、Grafana Webhook 或普通 HTTP Channel 入口。
- 不实现 Workflow 执行引擎；Workflow Publication 在本阶段仍为 `stored_only`。
- 不实现 API Capability Catalog、Capability Gateway 或应用能力授权执行；非空 Capability 仍阻止发布。
- 不新增任意 HTTP、SQL、Redis、LogQL、Shell 或写操作工具。
- 不把 Business Application 的 Delivery Binding 当作保存临时 `sessionWebhook` 的位置。
- 不把每个业务应用部署为独立 Agent 服务，也不启动新的 Agent Runtime。
- 不回填历史 Job 的业务应用归属，不根据旧消息猜测 provenance。
- 不改变 Webhook 的现有入口行为；本次失败关闭仅作用于钉钉 Stream。

## Decisions

### 1. 部署环境与业务数据环境严格分离

Business Application Deployment 固定使用单一运行环境：

```text
deployment_environment = local
```

唯一允许值是：

```text
local
```

Channel event 中的：

```text
routing.environment = sanjiu
```

只表示数据库、Redis、Loki 等业务数据拓扑范围，继续写入 Job routing context，但绝不参与 Business Application Deployment 解析。

Channel ingress 调用 Resolver 时只能使用 Bootstrap 注入的 `local`。管理端激活确认和有效配置视图只展示 `local`；后端拒绝所有非 `local` Deployment 请求。迁移删除非 `local` Deployment 和 route 投影，但保留不可变 Publication 与历史 Job provenance。

选择拆分两个概念，而不是扩展 Business Application 环境枚举接受 `sanjiu`，是因为后者会把部署阶段和企业数据域永久混为一谈，也无法回答“同一个 sanjiu 数据范围在测试和生产部署是否使用同一应用版本”。

### 2. 引入唯一的运行时接线状态模型

保留 `runtime_wired` 作为兼容布尔字段，但不再把它作为唯一真相。服务端统一计算：

```text
runtime_wired: boolean
runtime_status:
  not_wired | partially_wired | wired | blocked
runtime_components:
  trigger_routing
  agent_publication
  session_policy
  delivery
  execution_policy
  workflow
  capabilities
```

每个组件返回：

```text
status: wired | partially_wired | stored_only | unsupported | blocked
reason_code
message
```

规则如下：

- `runtime_wired=true` 表示当前服务数据面闸门开启，且该应用在当前部署环境至少有一条可执行的受支持活动 Trigger route；
- 所有已启用且属于本阶段的组件均可执行时，整体为 `wired`；
- 至少一条路由可执行，但存在明确标注为 `stored_only` 的 Workflow 或 Execution Policy 字段时，整体为 `partially_wired`；
- 数据面闸门关闭或当前环境没有有效受支持路由时为 `not_wired`；
- 活动路由存在但 Publication hash、组件引用、路由身份、Delivery 或策略完整性失败时为 `blocked`。

应用列表、详情、Publication、Deployment、effective 查询、激活响应和审计都通过同一个 `RuntimeReadinessEvaluator` 生成状态，禁止各层硬编码。

选择“兼容布尔值 + 结构化状态”，而不是直接删除 `runtime_wired`，可避免管理端契约一次性破坏，同时解决一个布尔值无法表达部分接线的问题。

### 3. 第一阶段只支持两类钉钉 Stream Trigger

支持矩阵固定为：

| Trigger | actor policy | 路由键 | 状态 |
|---|---|---|---|
| `dingtalk_private` | `CURRENT_SENDER` | `bot:<bot_identity>` | wired |
| `dingtalk_group` | `CURRENT_SENDER` | `conversation:<conversation_id>` | wired |
| `webhook` | `SERVICE_ACCOUNT` | 原定义 | stored_only |

路由的唯一键仍为：

```text
deployment_environment
+ trigger_type
+ source_connector_id
+ normalized_routing_key
```

私聊的 `bot_identity` 必须由受信 Stream payload 字段或 Connector 配置解析，优先使用 payload 中经过适配器提取的 `robotCode`，缺失时使用 Connector 中固定的 bot identity。它不能来自消息正文、模型参数或用户可伪造的 routing context。私聊不按用户 ID 或会话 ID 建路由，因此一个机器人绑定一次即可服务多个用户。

群聊的 `conversation_id` 必须取钉钉事件的原始会话标识并规范化，不能使用群名称。这样同一机器人可把不同群路由到不同应用。

现有值为 `default` 或其他不符合上述命名空间的活动路由不自动猜测迁移；读取时标记为 `blocked/legacy_routing_key`，管理员必须在草稿中明确改为新的路由键后重新发布和激活。

选择显式命名空间而不是裸字符串，可避免 bot identity 与 conversation ID 碰撞，也让日志和页面能够直接解释路由含义。

### 4. 路由执行采用统一失败关闭

解析流程固定为：

```text
规范化受信 ChannelEvent
  → 计算部署环境、Trigger type、connector ID 和 routing key
  → 查询活动 route 投影
  ├─ 没有 route：记录 route.not_matched，不创建 Job，并回复安全配置错误
  └─ 找到 route：
       → 校验应用、Deployment、Publication schema/hash
       → 校验本阶段支持矩阵和 Delivery
       ├─ 通过：固定应用运行快照并创建 Job
       └─ 失败：不创建 Job，记录 route.blocked，并通过现有拒绝通知回复安全错误
```

“未命中”和“命中但损坏”必须是不同的类型结果，不能继续用 `resolve_trigger_optional()` 的 `None/exception` 混合语义。建议新增：

```text
RuntimeRouteResolution
  outcome = matched | not_matched | blocked
```

`not_matched` 与 `blocked` 都不得改用默认 Agent，也不得尝试其他业务应用。这样管理员看到的接管状态与实际执行一致，漏配路由不会被隐式默认行为掩盖。

### 5. 应用 Publication 对 Agent 选择拥有最高优先级

路由命中后，Agent Publication 只能来自不可变 Business Application Publication snapshot。Channel event 的 `agent_code`、`agent_publication_id`、revision 或 hash 不得在未命中业务应用时触发默认 Agent。

若已命中应用但 Channel event 同时携带另一个固定 Agent：

- 值完全一致时允许继续并记录来源；
- 值不一致时返回 `blocked/agent_override_conflict`，不允许入口覆盖。

Agent Worker 只读取 Job 中已经固定的 Agent Publication，不在执行时重新调用 Business Application Resolver。这样激活新版本不会改变已经入队的 Job。

### 6. 会话归属按业务应用隔离，策略按支持程度执行

命中应用时，会话 identity 增加稳定 `business_application_id` 维度：

```text
business_application_id
+ source_channel
+ connector_id
+ external_conversation_id
+ conversation_mode 对应主体
```

不同业务应用即使共享同一钉钉会话，也不能复用同一 `agent_session`。同一应用重新激活新 Publication 后可以延续会话，但每个 Job 仍固定自己的 Publication provenance。

第一阶段连接：

- `conversation_mode`
- `recent_message_limit`
- `continuous_conversation_enabled`
- `attachments_enabled`

`retention_days` 若当前清理任务尚未接线则标记为 `stored_only`，不得声称已执行。Execution Policy 中未传递到 Worker 并被强制执行的字段同样逐项标为 `stored_only`。后续接线时复用同一状态模型，不新增全局开关。

选择应用 ID 而不是 Publication ID 作为会话隔离维度，能在应用升级后保持真实连续对话；Job provenance 则保证历史执行仍可复现版本。

### 7. Job 在入队前保存完整且不可变的应用 provenance

`agent_job` 增加可空字段：

```text
business_application_id
business_application_code
business_application_publication_id
business_application_deployment_id
business_application_route_id
business_application_config_hash
business_application_runtime_status
```

同时将安全的路由决策摘要保存到专用 JSON 或审计 payload：

```text
deployment_environment
trigger_type
source_connector_id
normalized_routing_key_hash
resolution_outcome
component_status
```

不保存 `sessionWebhook`、Token、Secret、完整敏感 URL 或消息原始 payload。路由键如包含外部会话标识，审计默认保存摘要/hash，只有受权限保护的 Job 字段保留执行所需标识。

这些字段与 Job、消息、Session 和 Outbox/MQ 发布在现有事务边界内持久化。RabbitMQ payload 继续只携带 `job_id` 和 `correlation_id` 等最小标识。

现有 Job 保持字段为空，API 显示 `legacy_unattributed`，不进行推断回填。

### 8. Delivery Binding 只授权投递方式，临时目标仍来自受信事件

钉钉 Stream 第一阶段只支持活动 `reply_original` Delivery Binding，并要求：

- Binding connector ID 与 ingress source connector ID 一致；
- Event 已由 Stream 适配器生成 `dingtalk_stream_session_webhook` reply route；
- 临时 `sessionWebhook` 只存在于受保护的 Job reply route，不进入 Application snapshot；
- Binding 的 `reply_mode` 与现有分片策略兼容；
- 同一 Trigger 对应且仅对应一个有效的 `reply_original` Binding。

命中应用后，Delivery Binding 是“允许回复原会话”的策略；具体临时目标由钉钉事件提供，模型和应用草稿都不能覆盖。缺失、重复、不匹配或不支持的 Delivery 会使 route `blocked`，并在激活预检中显示。

Delivery Worker 继续从 Job 读取固定 reply route。投递失败只重试投递，不重新执行 Agent。

选择复用原会话 webhook 而不是应用中配置固定群，是为了保持私聊和群聊的原路回复语义，也避免把短期凭据写进长期 Publication。

### 9. 激活前执行运行时预检，激活本身仍保持控制面原子性

激活流程在现有完整性和路由冲突检查之外增加 `RuntimeReadinessEvaluator`：

```text
校验当前数据面闸门
校验目标 environment 是否为当前 APP_ENV
校验 Trigger 支持矩阵与路由键命名空间
校验 actor policy
校验 Agent Publication
校验 Session Policy 支持状态
校验 reply_original Delivery
生成 component_status 与受影响入口摘要
```

仅允许激活到 `local`。任何非 `local` 请求在写 Deployment 前返回字段错误；`local` 中存在 `blocked` 的受支持 Trigger 时拒绝激活，确保控制面不会主动制造已知不可执行路由。`stored_only` 组件不阻止本阶段路由，但会使整体状态为 `partially_wired`。

回退通过重新激活历史 Publication 完成，并再次执行相同预检。停用移除活动 route 投影；之后的新消息因未命中而失败关闭，已经创建的 Job 不受影响。

### 10. 管理 Web 展示影响范围和真实状态，不再展示固定文案

业务应用列表和详情使用服务端状态：

- 状态徽标：未接线、部分接线、已接线、已阻塞；
- 唯一 `local` 运行实例；
- 私聊 bot identity 或群 conversation identity 的安全摘要；
- 每个组件的生效状态和原因；
- 激活、回退、停用后将接管或释放的入口；
- 未命中路由的失败关闭行为；
- 最近 Job 的应用 Publication provenance。

激活确认必须明确说明：

- “发布”不会改变运行时；
- “激活到 local”会让匹配消息从下一次新事件起使用该 Publication；
- “停用”会让后续未匹配消息返回配置错误且不创建 Job；
- 已入队 Job 不切换版本。

前端不得自行推断 `runtime_wired`，也不得在 API 缺字段时默认显示为已接管。

### 11. 审计和可观测性围绕一次路由决策建立

至少记录以下事件：

```text
business_application.route.matched
business_application.route.not_matched
business_application.route.blocked
business_application.runtime.activated
business_application.runtime.rolled_back
business_application.runtime.deactivated
```

所有阶段使用相同 `correlation_id`、`external_event_id`、`job_id`、application code、Publication ID、Deployment ID 和 route ID 串联。日志和指标区分：

- matched；
- not_matched；
- blocked by reason；
- Job created；
- Agent succeeded/failed；
- Delivery succeeded/failed。

这使“钉钉没有回复”可以按入口、身份、路由、Job、Worker 和 Delivery 顺序定位，而不需要猜测开关状态。

## Risks / Trade-offs

- [失败关闭会暴露既有漏配路由] → 对每次 `not_matched` 记录指标和审计，并向钉钉原会话返回可操作的安全提示。
- [当前数据库存在 `default` 等旧 routing key] → 不自动猜测迁移；将其标记为 `legacy_routing_key`，提供预检错误和重新发布指引。
- [bot identity 在不同钉钉 payload 中可能缺失] → 由 Stream 适配器与 Connector 配置双来源解析；两者都缺失时不命中应用并记录原因，禁止使用用户输入补齐。
- [一条 route 可执行但 Workflow/Execution Policy 未执行，用户仍可能误解] → 使用 `partially_wired` 和逐字段状态，UI 不以单个绿色开关概括全部配置。
- [新增 Job provenance 增加存储和索引成本] → 只保存标识、hash 与小型状态摘要；不复制完整 Publication snapshot。
- [停用后新消息无法执行] → 停用确认明确显示失败关闭行为，并记录 runtime deactivation 审计。
- [Application Publication 升级时延续旧会话可能混合上下文] → Job 固定版本且上下文标记消息对应的 Publication；若未来需要强隔离，可新增显式“升级时重开会话”策略。
- [状态计算散落导致再次不一致] → 只允许 `RuntimeReadinessEvaluator` 产生状态，API、审计和 UI 使用同一 DTO。
- [拒绝命中后损坏配置可能让用户收不到正常答案] → 复用钉钉失败通知发送安全、可操作的错误；不以错误版本生成看似正常的诊断。

## Migration Plan

1. 增加 Job provenance 可空字段、索引和 API DTO，先部署数据库迁移；旧 Job 显示为 `legacy_unattributed`。
2. 引入统一 `RuntimeReadinessEvaluator` 和结构化状态 API，但保持数据面闸门关闭，验证列表、详情、Publication 与 Deployment 状态一致。
3. 修正环境边界：Resolver 只使用 `APP_ENV`，业务 `routing.environment` 原样保留给工具范围。
4. 实现钉钉私聊/群聊路由键构造、三态解析结果、Agent 优先级、Session 隔离和 Job provenance，完成单元与集成测试。
5. 接入 `reply_original` Delivery Binding 校验及运行时约束，验证投递失败不会重新执行 Agent。
6. 将旧 `default` 路由标为阻塞而非自动迁移；管理员为当前 bot/群创建明确新草稿、发布并激活到 `APP_ENV` 对应环境。
7. 在 `local` 开启现有 `FEATURE_PUBLISHED_AGENT_RUNTIME`，验证私聊、群聊、无匹配失败关闭、命中后阻塞、回退、停用和最终 Delivery。
8. 通过审计和 Job provenance 观察 matched、not_matched、blocked 与 delivery 指标。

回滚方式：

- 配置回滚：重新激活上一个历史 Publication；
- 路由回滚：停用当前 Deployment，让后续消息失败关闭且不创建 Job；
- 紧急数据面回滚：关闭既有 `FEATURE_PUBLISHED_AGENT_RUNTIME`，新钉钉消息失败关闭，已入队 Job 继续按固定版本执行；
- 数据库字段保持向后兼容，不在回滚中删除迁移。

## Open Questions

- 当前没有阻止本变更进入实现的开放问题。
- 默认 Agent 回退已取消；`route.not_matched` 指标用于发现和修复漏配路由。
- Execution Policy、Workflow 与 API Capability 的真实执行接线分别由后续独立变更完成，本变更只建立可扩展的状态与阻塞语义。
