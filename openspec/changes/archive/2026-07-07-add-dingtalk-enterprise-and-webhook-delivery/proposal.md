## Why

当前 Channel/Delivery 已经把结果投递从 Agent runtime 中抽离出来，但 DingTalk delivery adapter 仍是内部 callback 形态，不能直接使用钉钉企业 App 的 Client ID/Secret，也不能按钉钉群机器人 webhook 标准格式把结果发到群。为了让真实钉钉接入可落地，需要补齐两类 DingTalk 出口：企业 App 主动投递和 webhook 群机器人投递。

这次变更只扩展结果出口能力，不扩大 Agent 的只读诊断边界，也不让外部系统直接进入 RabbitMQ。

## What Changes

- 新增 DingTalk 企业 App delivery adapter：通过 Client ID/Secret 获取并缓存 access token，再调用钉钉发送消息接口把 Agent 结果投递到配置的会话或接收目标。
- 新增 DingTalk webhook 群机器人 delivery adapter：按照钉钉自定义机器人 webhook 消息格式发送 markdown/text 到群，不支持作为用户问题入口。
- 扩展 connector 配置：支持 `env:` secret reference 保存 `DINGTALK_CLIENT_ID`、`DINGTALK_CLIENT_SECRET`、机器人 webhook URL、机器人签名密钥、endpoint host allowlist 和默认目标。
- 扩展 reply route：支持企业 App 出口目标和 webhook 群机器人出口目标，并确保 delivery target 摘要不保存 token、secret、完整 webhook query 参数或 access token。
- 增加 delivery 审计：记录获取 token、发送请求、分片发送、失败原因、安全摘要和 connector 授权结果。
- 更新文档与本地测试方式：说明钉钉企业 App 和 webhook 群机器人的配置项、数据库 seed 示例、curl/假客户端测试方法。
- 保持 webhook 群机器人“只发送消息到群”：不实现 webhook 机器人作为入口接收用户问题。

## Capabilities

### New Capabilities

### Modified Capabilities
- `result-delivery-routing`: 结果投递需要支持真实 DingTalk 企业 App 和 DingTalk webhook 群机器人两类出口。
- `channel-connector-configuration`: connector 配置需要表达 DingTalk 企业 App 凭据、webhook 群机器人 endpoint/secret、host allowlist 和密钥引用。
- `dingtalk-agent-ingress`: DingTalk 结果回传不再只依赖内部 callback，需要支持通过企业 App 出口回到钉钉；webhook 群机器人只作为出口。
- `agent-audit-permission`: 审计与权限需要覆盖 DingTalk token 获取、HTTP 发送、安全摘要、connector delivery 授权和失败隔离。

## Impact

- Affected backend modules: `delivery`、`dingding`、`channel.infrastructure.connector_registry`、`bootstrap`、`shared.config`。
- Affected persistence/config: `integration_connector` seed、connector metadata/secret_ref/endpoint_ref/host_allowlist 使用约定，必要时增加配置字段或迁移。
- Affected runtime path: `ResultDeliveryService` 选择具体 DingTalk delivery adapter，AgentExecutor/worker 仍只调用通用 delivery service。
- Affected tests/docs: DingTalk 企业 App token client、webhook 群机器人消息格式、分片发送、失败不重跑 Agent、敏感信息不落库、README 配置指引。
- External systems: DingTalk Open Platform 企业 App、DingTalk custom robot webhook。真实密钥必须由环境变量或 secret reference 提供，不能提交到仓库。
