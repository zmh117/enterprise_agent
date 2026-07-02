## 1. 配置与 Connector

- [x] 1.1 扩展 DingTalk/Delivery 配置读取，支持企业 App Client ID/Secret、webhook 群机器人 URL/secret 的 `env:` 引用约定。
- [x] 1.2 扩展 connector metadata 解析能力，安全解析 `*_ref` 字段且不把解析后的密钥写入可序列化摘要。
- [x] 1.3 更新本地 seed，配置 `connector-dingtalk-enterprise-default` 和 `connector-dingtalk-webhook-default` 的 delivery-only/ingress 权限、endpoint_ref、secret_ref、host_allowlist 和 metadata 示例。
- [x] 1.4 更新 `.env.example` 和 Docker compose 环境变量占位符，不提交真实 Client ID、Client Secret 或机器人 webhook。

## 2. DingTalk 企业 App Client

- [x] 2.1 新增 `DingTalkAccessTokenClient`，实现 Client ID/Secret 获取 access token、过期时间解析、提前刷新和进程内缓存。
- [x] 2.2 新增企业 App 消息 client，封装钉钉发送消息请求、响应码解析、超时处理和安全错误摘要。
- [x] 2.3 为 token client 和消息 client 增加 fake transport 或可注入 HTTP transport，确保单元测试不访问真实钉钉网络。
- [x] 2.4 覆盖 token 成功、token 失败、token 缓存复用、消息发送失败和敏感信息屏蔽测试。

## 3. Webhook 群机器人 Client

- [x] 3.1 新增 `DingTalkWebhookRobotClient`，按 webhook 群机器人格式发送 markdown/text 消息。
- [x] 3.2 实现 webhook 群机器人加签 URL 生成、host allowlist 校验、超时处理和钉钉错误响应解析。
- [x] 3.3 确保 webhook 群机器人 connector 只能作为 delivery 使用，入口使用时拒绝创建 Agent job。
- [x] 3.4 覆盖 webhook 发送成功、签名生成、host denied、入口误用拒绝和完整 URL 屏蔽测试。

## 4. Delivery 集成

- [x] 4.1 拆分现有 DingTalk delivery adapter，把 `dingtalk_enterprise_robot` 绑定到企业 App adapter，把 `dingtalk_webhook_robot` 绑定到 webhook 群机器人 adapter。
- [x] 4.2 保留或明确替代内部 callback 形态，避免破坏现有 `dingtalk_conversation` 或测试 fake delivery 行为。
- [x] 4.3 将 ReplyRoute target 映射到企业 App 目标和 webhook 群机器人目标，缺失目标时从 connector metadata 读取默认值。
- [x] 4.4 复用 ReportChunker、delivery_attempt 和 delivery_chunk，确保分片顺序、`part x/y` 标识和失败状态一致。
- [x] 4.5 确保钉钉投递失败不会改写 Agent job 执行状态，也不会触发 Agent 重新执行。

## 5. 审计、权限与安全摘要

- [x] 5.1 增加钉钉 token 获取、connector delivery 授权、HTTP 发送成功/失败、webhook 入口拒绝的审计事件。
- [x] 5.2 更新 target summary 和 error summary 屏蔽规则，覆盖 Client Secret、access token、webhook token、签名串、完整 URL 和敏感接收人信息。
- [x] 5.3 增加权限测试，验证未启用 connector、allow_delivery=false、allow_ingress=false、host allowlist 不匹配时均不会发起外部钉钉请求。

## 6. 文档与验证

- [x] 6.1 更新 README，说明钉钉企业 App Client ID/Secret 配置、webhook 群机器人配置、reply route 示例和真实联调步骤。
- [x] 6.2 增加本地 curl 或脚本示例，说明如何用 Debug API/Grafana route 投递到 webhook 群机器人。
- [x] 6.3 运行 DingTalk delivery、channel connector、audit permission、worker idempotency 的定向测试。
- [x] 6.4 运行 `make check` 和 `openspec validate add-dingtalk-enterprise-and-webhook-delivery`。
