## Context

当前系统已经有通用 `ResultDeliveryService`、`ReplyRoute`、connector 方向控制、delivery attempt/chunk 持久化，以及 `dingtalk_conversation`、`dingtalk_webhook_robot`、`dingtalk_enterprise_robot` route type。但现有 DingTalk adapter 实际发送的是内部 callback payload：

```json
{"conversation_id": "...", "title": "...", "text": "..."}
```

这适合接一个内部钉钉网关，不等于直接调用钉钉开放平台。用户现在能提供企业 App 的 Client ID/Secret，并要求结果直接发回钉钉；同时还要求实现 webhook 机器人，但 webhook 机器人只负责把消息发到群，不作为入口接收用户问题。

## Goals / Non-Goals

**Goals:**

- 支持 DingTalk 企业 App delivery：通过 Client ID/Secret 获取 access token，并用企业 App 能力发送 Agent 最终报告或失败通知。
- 支持 DingTalk webhook 群机器人 delivery：按钉钉机器人 webhook 消息格式发送群消息。
- 继续复用 `ResultDeliveryService` 的分片、attempt/chunk、失败隔离和审计模型。
- 通过 connector 的 `secret_ref`、`endpoint_ref`、`metadata` 和 host allowlist 表达钉钉出口配置，真实密钥只放环境变量或外部 secret。
- Webhook 群机器人只作为 delivery connector，不参与 `/webhooks/dingding/agent` 入口验签、用户身份解析或 job 创建。

**Non-Goals:**

- 不实现钉钉 OAuth 用户授权、通讯录同步、审批或其他企业应用能力。
- 不把 Client ID/Secret 写入数据库、日志、audit payload、job payload 或 OpenSpec 文档。
- 不改变 RabbitMQ 消息格式，队列仍只承载 `job_id` 和 `correlation_id`。
- 不扩大 Agent 只读诊断边界，不新增自动修复、重启、写库、删 Redis 或代码变更能力。
- 不实现 webhook 群机器人入口收消息。用户问题入口仍由企业机器人/App 回调或通用 Channel adapter 承担。

## Decisions

### 1. 企业 App 和 webhook 群机器人使用不同 adapter

`dingtalk_enterprise_robot` 与 `dingtalk_webhook_robot` 不再共用内部 callback client：

```text
ResultDeliveryService
  -> route.type=dingtalk_enterprise_robot
     -> DingTalkEnterpriseAppDeliveryAdapter
        -> DingTalkAccessTokenClient
        -> DingTalkEnterpriseMessageClient

  -> route.type=dingtalk_webhook_robot
     -> DingTalkWebhookRobotDeliveryAdapter
        -> DingTalkWebhookRobotClient
```

原因：企业 App 需要 Client ID/Secret 换 token，webhook 群机器人需要 access token/signature/webhook URL。两个协议、认证方式和失败码都不同，强行放进一个 adapter 会让配置和测试混乱。

替代方案：继续用 `DINGTALK_CALLBACK_URL` 指向外部钉钉网关。这个方案仍然可保留为内部 webhook/generic webhook 出口，但不能满足“系统直接发回钉钉”。

### 2. 凭据通过 connector secret reference 解析

建议 connector 形态：

```text
connector-dingtalk-enterprise-default
  connector_type = dingtalk_enterprise_robot
  allow_ingress = true 或 false
  allow_delivery = true
  secret_ref = env:DINGTALK_CLIENT_SECRET
  metadata.client_id_ref = env:DINGTALK_CLIENT_ID
  metadata.default_open_conversation_id / default_userid_list / default_robot_code

connector-dingtalk-webhook-default
  connector_type = dingtalk_webhook_robot
  allow_ingress = false
  allow_delivery = true
  endpoint_ref = env:DINGTALK_WEBHOOK_ROBOT_URL
  secret_ref = env:DINGTALK_WEBHOOK_ROBOT_SECRET
  host_allowlist = oapi.dingtalk.com,api.dingtalk.com
```

`ConnectorRegistry.resolve_secret()` 已支持 `env:`，可以扩展一个安全 metadata resolver，只解析以 `_ref` 结尾的字段。实现时不要把解析后的 secret 写回 connector 对象的可序列化摘要。

替代方案：新增全局 `DINGTALK_CLIENT_ID` / `DINGTALK_CLIENT_SECRET` 配置，并跳过 connector。这个方案只能表达一个租户/一个 App，后续多个群、多个企业或多套机器人无法配置。

### 3. Token client 必须缓存并可测试

新增 `DingTalkAccessTokenClient`：

- 输入：client_id、client_secret。
- 输出：access_token、expires_at。
- 缓存：内存缓存，按过期时间提前刷新。
- 错误：网络错误、认证失败、返回码非成功都转成安全异常。
- 测试：提供 fake transport，单测不访问真实钉钉网络。

token 获取失败是 delivery 失败，不应改变 Agent job 已经成功的状态。

### 4. Webhook 群机器人只发群消息

`dingtalk_webhook_robot` adapter 只支持 delivery：

- 消息类型优先 `markdown`，短失败通知可用 `text`。
- 使用 connector endpoint 作为 webhook URL。
- 如果 connector 配置了 secret，则按钉钉机器人签名规则给 webhook URL 添加 timestamp/sign。
- 发送前校验 host allowlist。
- 不解析钉钉用户身份，不创建 Agent job，不接受外部回调。

这满足“webhook机器人，只发送消息到群”的边界，避免把 webhook 群机器人误当成企业 App 入口。

### 5. ReplyRoute target 保持平台无关但要能表达钉钉目标

建议支持这些 target 字段：

```text
dingtalk_enterprise_robot:
  open_conversation_id?
  conversation_id?
  userid_list?
  robot_code?

dingtalk_webhook_robot:
  webhook_id?
  at_mobiles?
  at_user_ids?
  is_at_all?
```

adapter 负责把内部 target 映射成钉钉 API 需要的 payload。`target_summary` 只保存目标类型、connector_id、webhook_id、接收人数量、是否 at all 等安全摘要，不保存完整 webhook URL、access token、secret 或手机号明文。

## Risks / Trade-offs

- [钉钉企业 App API 权限不足] -> 文档明确需要在钉钉开放平台给 App 开通对应消息发送权限；运行时把权限错误记录为 delivery failed，不重跑 Agent。
- [Client Secret 泄露] -> 只允许通过环境变量/secret reference 读取，测试和文档使用占位符，审计摘要屏蔽密钥和完整 URL。
- [token 缓存失效或并发刷新] -> MVP 使用进程内缓存；刷新失败时保留安全错误摘要。多进程重复获取 token 可接受，后续再引入集中缓存。
- [webhook 群机器人与企业 App 语义混淆] -> connector type 和 route type 分开，webhook 群机器人不允许 ingress。
- [真实钉钉网络不可用于 CI] -> 单元测试使用 fake transport；真实联调文档提供手工验证步骤。

## Migration Plan

1. 新增配置读取和 connector metadata resolver，不改变现有表结构，优先复用 `integration_connector`。
2. 新增 DingTalk 企业 App token/message client 和 webhook robot client。
3. 将 `dingtalk_enterprise_robot`、`dingtalk_webhook_robot` route type 绑定到新 adapter。
4. 更新 local seed / README / `.env.example`，真实密钥使用占位符和 `env:` 引用。
5. 增加测试覆盖 token 缓存、webhook 签名、host allowlist、安全摘要、分片、delivery failure 不影响 job 状态。
6. 回滚时可将 connector 的 `allow_delivery=false` 或把 route 改成 `none`/内部 webhook，不影响 Agent job 创建和执行。

## Open Questions

- 企业 App 结果默认发回“原会话”还是配置的默认群，需要在真实钉钉 App 权限和可用 API 确认后选择默认 target；实现上先支持 reply route 明确指定 target，缺省值从 connector metadata 读取。
- 企业 App 使用的具体钉钉消息 API 需要在实现前按当前开放平台权限确认；adapter 应通过 client 层隔离 API 差异。
