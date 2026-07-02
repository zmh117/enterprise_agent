## Why

当前钉钉用户消息入口依赖公网 HTTPS HTTP webhook，本地开发和内网部署都需要额外暴露地址，实际联调容易卡在钉钉无法访问本机服务。改为 DingTalk Stream 后，系统可以由本地/容器内进程主动连接钉钉并接收消息，再复用现有 Channel、Agent job、RabbitMQ、worker 和 Delivery 链路。

## What Changes

- **BREAKING**: 钉钉用户消息入口从 HTTP webhook 改为 DingTalk Stream 长连接；`/webhooks/dingding/agent` 不再作为正式钉钉用户消息入口。
- 新增 DingTalk Stream ingress worker/service：使用企业 App Client ID/Secret 或 Stream 所需凭据连接钉钉，接收用户消息事件。
- Stream adapter 将钉钉消息归一化为现有 `ChannelEvent`，继续走 `ChannelIngressService -> agent_job -> RabbitMQ -> agent-worker`。
- 保持结果出口不变：最终报告仍通过 `ResultDeliveryService`，可投递到钉钉企业 App 或 webhook 群机器人。
- 保持 webhook 群机器人只作为出口：不作为用户消息入口。
- HTTP webhook route 可保留为本地测试/兼容开关，但默认禁用或从文档中移出正式接入路径。
- 新增 Stream 运行配置、重连策略、幂等键、审计事件和本地开发文档。

## Capabilities

### New Capabilities
- `dingtalk-stream-ingress`: 定义 DingTalk Stream 长连接入口、消息归一化、重连、幂等和本地运行方式。

### Modified Capabilities
- `dingtalk-agent-ingress`: 钉钉用户消息入口从 HTTP webhook 验签模型改为 Stream 接收模型，原 webhook 入口不再是正式入口。
- `agent-audit-permission`: 审计和权限需要覆盖 Stream 连接、Stream 消息接收、重连、消息确认、拒绝和异常。

## Impact

- Affected backend modules: `dingding`、`channel`、`bootstrap`、`workers` 或新增 `stream` worker。
- Affected runtime: 新增一个常驻 DingTalk Stream ingress 进程，可本地运行，也可在 Docker compose 中作为独立服务运行。
- Affected config: 新增 DingTalk Stream 凭据、启用开关、默认 routing、默认 delivery、重连间隔、worker 标识等环境变量。
- Affected APIs/docs: HTTP webhook 钉钉入口文档降级为兼容/测试；正式钉钉入口文档改为 Stream 模式。
- Affected tests: Stream 消息转 ChannelEvent、幂等、权限、重连、失败不建 job、与 delivery 的端到端 fake 测试。
