## Why

当前 Agent MVP 已经打通 DingTalk / Debug API -> 持久化 job -> RabbitMQ -> worker -> Claude runtime -> DingTalk callback 的只读诊断链路，但入口和结果回调仍强绑定 DingTalk 字段与 DingTalk callback。下一步需要让 DingTalk 应用、DingTalk webhook 机器人、Grafana 告警 webhook、email 等都能作为可配置 Channel 接入，并能把结果投递到不同 Delivery 目标。

这次变更把“请求从哪里来”和“结果发到哪里去”拆成稳定契约，避免后续每新增一个 Channel 就复制 Agent job、worker 或 callback 流程。

## What Changes

- 新增通用 Channel 入站契约：请求必须包含 `from`、`delivery`、`routing`、`message` 四类信息，Channel adapter 负责验签、解析身份、幂等键、路由字段和原始 payload 安全摘要。
- 新增 Grafana alert webhook 入站：只处理 `status=firing`，忽略 `resolved` 并记录原因；Grafana labels 使用专用字段映射 `project_code`、`environment`、`base`、`workshop`、`service`。
- 新增结果 Delivery 契约：结果根据 job 绑定的 `delivery` 路由投递，支持 DingTalk webhook 机器人、DingTalk 企业机器人、email、generic webhook 和 none。
- 新增长报告分片投递：Delivery 层按目标平台限制分片发送并记录每片状态，Agent job 不因单个分片失败而重新执行。
- 新增 Connector 配置模型：同一个连接器可配置是否允许 ingress、delivery 或两者都允许；secret/webhook URL 等敏感值使用密钥引用或环境配置，不直接写入业务记录。
- 修改 Agent session/job 模型：从 DingTalk 专用身份字段演进为通用 source channel、requester、external conversation/event、reply route，并保留兼容迁移路径。
- 修改 DingTalk 入口：DingTalk 企业机器人和 DingTalk webhook 机器人都通过通用 Channel contract 进入或投递，不再由 AgentExecutor/worker 直接依赖 DingTalk callback client。
- 保持 RabbitMQ 为内部基础设施：队列消息继续只承载 `job_id` 和 `correlation_id`，不把外部 Channel payload 放进 MQ。
- 保持 Agent 和内部工具只读边界：本变更不新增写操作、自动修复、重启、改代码、删除 Redis key、更新 SQL 或部署能力。

## Capabilities

### New Capabilities
- `channel-ingress-contract`: 定义可扩展 Channel 入站请求、验签、身份解析、幂等、Grafana firing 过滤和专用 routing 字段。
- `result-delivery-routing`: 定义结果投递路由、Delivery adapter、分片发送、投递尝试记录和失败处理。
- `channel-connector-configuration`: 定义 Channel/Delivery connector 的配置、启用方向、密钥引用、host allowlist 和安全约束。

### Modified Capabilities
- `agent-job-lifecycle`: Agent session/job 需要持久化通用 Channel 来源、requester、external event/conversation 和 reply route，而不是只依赖 DingTalk 字段。
- `dingtalk-agent-ingress`: DingTalk 企业机器人和 webhook 机器人需要通过通用 Channel/Delivery contract 支持可配置入口和出口。
- `agent-audit-permission`: 审计和权限检查需要覆盖 Channel 验签、connector 授权、Grafana ignored event、Delivery attempt 和分片投递。

## Impact

- Affected backend modules: `dingding`, `job`, `agent`, `audit`, `permission`, `message_bus`, plus new `channel` / `delivery` style modules.
- Affected persistence: `agent_session`, `agent_job`, audit records, connector/configuration tables, and new delivery attempt/chunk records.
- Affected APIs: existing DingTalk webhook, debug job API, new generic Channel/Grafana webhook APIs, and result delivery internals.
- Affected runtime path: `AgentExecutor` and `AgentJobWorker` should persist results and call a generic delivery service instead of directly sending DingTalk callbacks.
- Affected tests/docs: ingress idempotency, Grafana firing/resolved behavior, DingTalk ingress/egress configuration, chunked delivery, duplicate RabbitMQ delivery, delivery failure without Agent re-execution, and migration compatibility.
