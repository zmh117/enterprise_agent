## 1. 配置与依赖

- [x] 1.1 确认 DingTalk Stream Python SDK 或协议客户端依赖，并将依赖加入后端运行环境
- [x] 1.2 在 `backend/app/shared/config.py` 增加 Stream ingress 启用开关、Client ID/Secret、connector ID、默认 routing、默认 delivery、重连间隔和兼容 HTTP webhook 开关
- [x] 1.3 更新 `.env.example`、Docker Compose 和后端 README，说明 Stream ingress 本地启动方式和 HTTP webhook 默认非正式入口
- [x] 1.4 扩展 connector 配置模型，区分 `dingtalk_enterprise_stream` 入口、钉钉企业 App 出口、钉钉 webhook 群机器人出口

## 2. Stream Adapter

- [x] 2.1 新增 DingTalk Stream 消息 DTO 和 parser，提取会话 ID、用户 ID、消息 ID、事件 ID、文本内容和原始 payload 摘要
- [x] 2.2 实现 Stream adapter，将受支持用户消息归一化为 Channel event，并填充 `from`、`delivery`、`routing`、`message`、`external_event_id` 和 connector metadata
- [x] 2.3 对不支持事件类型、空消息、缺失身份字段和缺失 routing 的 Stream 事件返回 ignored/rejected 结果，并写入安全审计摘要
- [x] 2.4 为 Stream 事件生成稳定幂等键，确保重连或重投不会创建重复 Agent job

## 3. Stream Ingress Worker

- [x] 3.1 新增独立 Stream ingress worker 入口，启动时加载启用的 DingTalk Stream connector 并建立长连接
- [x] 3.2 将 Stream worker 接入 ChannelIngressService，成功路径完成权限检查、job 持久化、RabbitMQ 发布和 Stream acknowledgement
- [x] 3.3 实现连接断开、临时失败和启动失败的有界退避重连，并记录连接生命周期审计事件
- [x] 3.4 防止同一 connector 在同一进程内重复启动；部署文档明确同一 connector 默认单活

## 4. HTTP Webhook 降级

- [x] 4.1 将 `/webhooks/dingding/agent` 从正式钉钉用户消息入口降级为兼容/测试入口，并默认禁用
- [x] 4.2 更新钉钉接入文档，删除“必须配置公网 HTTPS 回调地址”的正式路径，改为 Stream 连接配置
- [x] 4.3 确保钉钉 webhook 群机器人只能作为 delivery connector 使用，不能被配置为 ingress connector

## 5. 审计、权限与投递

- [x] 5.1 扩展权限检查链路，确保 Stream 消息在创建 Agent job 前检查 connector enablement、用户 allowlist 和项目/服务 allowlist
- [x] 5.2 扩展审计事件，串联 Stream receipt、identity parsing、idempotency、permission、job creation、queue dispatch、worker execution、artifact 和 delivery result
- [x] 5.3 保持结果出口走 ResultDeliveryService，默认发回原钉钉会话，同时支持配置为钉钉企业 App 或 webhook 群机器人 delivery
- [x] 5.4 保持长报告分片发送策略，并覆盖 Stream 入口创建的 job 结果投递

## 6. 测试与验证

- [x] 6.1 增加 fake DingTalk Stream client 单元测试，覆盖连接成功、缺少凭据、断线重连和重复事件
- [x] 6.2 增加 Stream adapter 测试，覆盖消息归一化、不支持事件、缺失字段和稳定幂等键
- [x] 6.3 增加 ChannelIngressService 集成测试，覆盖 Stream 消息成功创建 job、重复消息返回已有 job、无权限不创建 job
- [x] 6.4 增加 delivery 集成测试，覆盖 Stream job 成功后发回原会话、配置为企业 App 出口和 webhook 群机器人出口
- [x] 6.5 更新或替换旧 DingTalk HTTP webhook ingress 测试，使其只验证兼容/测试开关，不再作为正式入口验收
- [x] 6.6 运行 OpenSpec 校验和后端测试，记录无法真实联调钉钉企业 App 时的 fake 验证边界
