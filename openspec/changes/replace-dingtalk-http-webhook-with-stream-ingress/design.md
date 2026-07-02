## Context

当前钉钉用户消息入口按 HTTP webhook 设计，需要在钉钉开放平台配置公网 HTTPS 回调地址。这个模型对本地开发、内网部署和 Docker Compose 联调不友好：系统必须额外暴露公网地址，且入口失败经常发生在网络可达性、证书、回调 URL 或钉钉重试语义上，而不是 Agent 业务链路本身。

系统已经存在 Channel/Delivery 的方向：外部入口先归一化为内部 Channel event，再创建 Agent session/job，经 RabbitMQ 交给 worker 执行，最终由 ResultDeliveryService 按 delivery 配置投递结果。DingTalk Stream 更适合作为钉钉用户消息入口，因为它由系统主动连接钉钉并接收事件，不要求本地服务暴露公网 HTTP webhook。

## Goals / Non-Goals

**Goals:**

- 将正式钉钉用户消息入口改为 DingTalk Stream 长连接。
- 新增可独立运行的 Stream ingress worker/service，支持本地开发和容器部署。
- Stream 事件归一化为现有 Channel event，继续复用 Agent job、RabbitMQ、worker、审计和 Delivery 链路。
- 保留钉钉企业 App 与 webhook 群机器人的结果出口能力，其中 webhook 群机器人仍只作为出口。
- 明确 HTTP webhook 不再是正式钉钉用户消息入口，可作为兼容/测试能力被显式启用。
- 为后续平台 Web 做消息出入口编排保留 connector 配置边界。

**Non-Goals:**

- 不实现钉钉群机器人作为用户消息入口。
- 不把 Grafana 或其他 channel 改成 Stream 模型。
- 不引入自动修复、写操作或超出只读诊断边界的 Agent 能力。
- 不要求第一版支持多租户热加载所有 connector；第一版可以通过配置或数据库启用指定 connector。

## Decisions

### 1. 使用独立 Stream ingress 进程，而不是挂在 FastAPI 请求生命周期内

Stream ingress SHALL 作为常驻 worker/service 运行，负责建立 DingTalk Stream 连接、接收消息、确认消息和重连。FastAPI 仍负责管理 API、debug API 和其他 HTTP 能力。

理由：Stream 是长连接消费模型，和 HTTP 请求响应模型不同。独立进程更容易在 Docker Compose、systemd、Kubernetes 或本地命令中管理健康检查、重启和日志，也避免 API 进程重载影响 Stream 会话。

替代方案：把 Stream client 放入 FastAPI startup event。该方案部署简单，但 API reload、多 worker、健康检查和连接生命周期容易产生重复消费或断线不可控，因此不作为默认设计。

### 2. Stream adapter 只做传输适配，业务入口仍是 ChannelIngressService

Stream adapter SHALL 将钉钉消息解析为统一 Channel event，包含 `from`、`delivery`、`routing`、`message`、`external_event_id` 和 connector metadata，然后调用 ChannelIngressService 创建 Agent job。

理由：这样后续平台 Web 编排更多入口时，只需要新增 adapter 或 connector 配置，不需要为每个 channel 改 Agent job 创建逻辑。

替代方案：Stream adapter 直接创建 Agent job。该方案短期路径短，但会绕过现有 channel 幂等、权限、审计和 delivery 约束，不利于扩展。

### 3. HTTP webhook 从正式入口降级为兼容/测试能力

`/webhooks/dingding/agent` 不再作为正式钉钉用户消息入口。实现时可以保留 route，但 MUST 通过配置显式开启，并在文档中标注为兼容或本地测试入口。默认部署不依赖公网 webhook。

理由：用户明确不需要 HTTP webhook。保留显式开关可以降低回滚风险，也能帮助已有测试或调试工具迁移。

替代方案：直接删除 HTTP route。该方案最彻底，但会增加回滚和增量迁移风险；正式能力仍应以默认禁用和文档移除为准。

### 4. 结果出口不跟入口绑定，使用 delivery 配置决定

Stream ingress 接收的消息 SHALL 带上 delivery 配置。默认情况下，钉钉用户消息的结果发回原会话；也可以按 connector 配置投递到钉钉企业 App、钉钉 webhook 群机器人或其他已支持 delivery。

理由：入口和出口分离后，Grafana、钉钉用户消息和未来入口都可以复用同一套 Delivery 编排。

替代方案：Stream 消息固定发回原会话。该方案符合多数交互，但会限制平台 Web 做统一编排。

### 5. Stream 确认以“已持久化并完成调度决策”为边界

Stream adapter 收到消息后，只有在 ChannelIngressService 完成幂等判断、权限检查、job 持久化和队列发布后，才向钉钉确认成功。对重复事件返回已有 job 的确认。对认证、权限或格式错误返回拒绝/失败确认，并记录审计事件，不创建 job。

理由：确认过早会导致消息丢失；等待 Agent 执行完成又会阻塞钉钉消息消费。以持久化和调度决策为边界可以兼顾可靠性和异步执行。

替代方案：收到 Stream 消息立即确认。该方案吞吐更好，但在数据库或队列失败时会丢消息，不符合诊断链路可追踪要求。

## Risks / Trade-offs

- [Risk] Stream SDK 或协议依赖引入新的运行时失败模式 → 通过适配层封装、fake stream client 测试和连接状态审计降低影响。
- [Risk] 多个 Stream ingress 实例同时运行导致重复事件 → 使用外部事件 ID 幂等键，并在部署文档中明确同一 connector 默认单活。
- [Risk] Stream 长连接断线导致消息延迟 → worker MUST 支持退避重连、连接状态日志和审计事件。
- [Risk] HTTP webhook 降级影响已有联调脚本 → route 默认禁用但保留显式兼容开关，迁移文档给出新命令。
- [Risk] 结果出口配置错误导致用户无回复 → delivery 失败 SHALL 被审计并可重试或查询，Stream 入口不直接吞掉最终投递错误。

## Migration Plan

1. 增加 DingTalk Stream 配置项、connector 配置和运行入口。
2. 实现 Stream adapter，将钉钉消息归一化为 Channel event。
3. 接入 ChannelIngressService、权限、幂等、审计和 RabbitMQ 发布。
4. 增加 Stream ingress worker/service，并在 Docker Compose 中提供可选服务。
5. 将 DingTalk HTTP webhook 文档改为非正式入口，默认关闭 route 或要求显式开关。
6. 增加 fake Stream 端到端测试，覆盖成功、重复、无权限、格式错误、重连和 delivery 分片。
7. 本地验证通过后，使用企业 App Client ID/Secret 启动 Stream ingress，与钉钉开放平台联调。

Rollback 策略：保留 HTTP webhook 兼容开关时，可以临时重新启用旧入口；同时停用 Stream ingress worker，避免两个入口重复消费同一用户消息。

## Open Questions

- DingTalk Stream Python SDK 的最终依赖包和版本需要在实现时确认。
- 钉钉开放平台中 Stream 模式是否需要额外订阅事件类型，需要在真实企业 App 联调时确认。
- 第一版 connector 配置从环境变量读取还是从数据库读取，需要结合当前 channel 配置落点实现；设计上要求保留数据库化空间。
