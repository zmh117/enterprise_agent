# 多业务应用、共享 Agent Worker 与钉钉机器人路由

## 当前结论

Business Application、Agent Publication、DingTalk Connector 和运行进程是不同边界：

```text
多个 Business Application
  -> 各自活动 Application Publication / Route
  -> 创建独立 Agent Job 与 job_dispatch_outbox
  -> RabbitMQ agent.job.queue
  -> 共享 agent-worker
  -> Python Agent Runtime
```

Agent Profile 是配置身份，不是常驻进程。多个应用可以引用同一个 Agent Publication，
也可以引用同一 Agent 的不同历史 Publication；每个 Job 仍冻结自己的 Application、
Agent、Session/Execution Policy、发送人、Tool/File Snapshot 与回复路由。

RabbitMQ 消息只传 `event_id`、`job_id`、`correlation_id`。Worker 从 PostgreSQL 重读并
原子领取 Job，不能从队列 payload 推断应用配置。

## Worker 并发

当前 Compose 默认只有一个 `agent-worker`，RabbitMQ consumer 使用
`prefetch_count=1`。一次模型执行会占用该 Worker，其他应用的 Job 留在队列等待；
增加业务应用不会自动增加执行并发，也不会为每个应用创建容器。

多个 Worker 副本可以作为竞争消费者，但这只是部署扩容，不改变 Application 或 Agent
Publication。验收仍须检查原子 claim、模型 Provider 限流、数据库连接、队列积压、
MCP 上游负载和投递结果，不能只看副本数。

## 多钉钉 Connector

当前 `dingtalk-runtime` 是一个固定 TypeScript 渠道适配器进程，但会在同一进程内管理
多个 SDK Client：

```text
Control Plane desired snapshot
  -> dingtalk-runtime lease
  -> RuntimeManager.reconcile()
  -> 每个启用 dingtalk_enterprise_stream Connector 一个 SDK Client
```

新增、修改、停用 Connector 时，Runtime 按 connector revision 启动、重启或停止对应
Client，不需要为每个机器人复制 Compose service，也没有
`DINGTALK_STREAM_CONNECTOR_ID` 单 Connector 启动参数。旧
`dingtalk-stream-ingress` 已不在当前 Compose 中。

一个 Runtime 实例通过租约管理当前 desired snapshot。控制面短暂不可用时，进程保留
已连接 Client 并把 health 标为 degraded；这不等于消息业务链仍完整可用。

## 同一群多个机器人如何路由

群聊活动路由的确定性身份包含：

```text
environment=local
+ trigger_type=dingtalk_group
+ source_connector_id
+ normalized routing_key=conversation:<conversation_id>
```

因此，同一群的机器人 A 和机器人 B 必须使用两个不同 Connector：

```text
应用 A -> Connector A + conversation:group-1
应用 B -> Connector B + conversation:group-1
```

群 ID 相同并不冲突，因为 Connector 不同。以下配置会冲突并在激活时拒绝：

```text
应用 A -> Connector X + conversation:group-1
应用 B -> Connector X + conversation:group-1
```

系统不会按应用优先级、创建时间或随机规则选择。若用户同时触发两个机器人，且钉钉向
两个 Client 都投递回调，平台会得到两个 Connector 隔离的入口事件，并可能创建两个
独立 Job；幂等不会跨 Connector 合并它们。

## 完整链路

```text
DingTalk SDK callback
  -> dingtalk-runtime submit
  -> channel_ingress_event + channel_ingress_outbox
  -> channel-dispatch-worker
  -> 当前发送人身份 + 活动 Application route
  -> Agent Job + job_dispatch_outbox
  -> job-dispatch-worker -> RabbitMQ
  -> agent-worker -> Python Runtime -> MCP
  -> Delivery Outbox/Attempt -> 原会话或发布目标
```

`CONNECTED`/`REGISTERED` 只表示 SDK Client 状态；业务验收必须继续核对 Ingress、
Outbox、Route、Job、Runtime、MCP 和 Delivery 的同一 correlation 证据。

## 边界表

| 场景 | 当前行为 |
|---|---|
| 多个应用共享一个 Agent Publication | 支持 |
| 一个 `dingtalk-runtime` 管理多个 Connector | 支持 |
| 同群两个机器人使用不同 Connector | 支持 |
| 同一 Connector + 同一路由归属两个活动应用 | 拒绝 |
| 一个 Worker 同时执行多个 Job | 默认不支持，`prefetch_count=1` |
| 历史 TypeScript Agent Publication 创建新 Job | 拒绝 |
