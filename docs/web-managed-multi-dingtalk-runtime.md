# Web 受管多钉钉 Stream Runtime

## 运行边界

`dingtalk-runtime` 是固定的 TypeScript 连接适配器。一个已启用的
`dingtalk_enterprise_stream` Connector 对应一个独立 SDK Client。Runtime
只管理连接、回调标准化和可靠 Inbox 提交，不选择 Agent、不创建 Agent Job，
也不消费回复队列。

钉钉消息进入后的唯一数据面仍是：

```text
DingTalk SDK callback
  -> channel_ingress_event + channel_ingress_outbox
  -> RabbitMQ channel dispatch
  -> Python ChannelIngressService
  -> Business Application route
```

## 首次迁移现有机器人

首次部署时，API 启动的本地 seed 会把现有单机器人启动配置登记为
`dingtalk_enterprise_stream` Connector，并把 Client Secret 写入
Platform Secret。确认管理页能看到该 Connector 后，再启动新的 Runtime。

```bash
docker compose up -d --build api-server rabbitmq postgres
docker compose up -d --build dingtalk-runtime channel-dispatch-worker
```

`docker-compose.yml` 已移除旧的 `dingtalk-stream-ingress` 服务。禁止同时手工
启动旧 Python Stream Worker和新的 TypeScript Runtime，否则同一个钉钉应用
可能产生重复连接和重复事件。

## 后续新增机器人

后续只在“业务应用 → 渠道与触发器”中新建钉钉应用机器人：

```text
Web 保存 Connector 和 Platform Secret
  -> config revision 变化
  -> Runtime reconcile
  -> 只启动或重建对应 Client
```

不修改 Compose、不重启其他机器人，也不挂载 Docker Socket。

## 状态解释

- `READY`：SDK 已注册，可以接收回调。
- `CONNECTED`：WebSocket 已连接，但当前连接周期尚未通过真实消息回调验证，不等于可用。
- `REGISTERED`：SDK 已确认注册，或当前连接周期内已有消息成功提交至平台 Inbox。
- `STARTING` / `RECONNECTING`：正在连接或自动重连。
- `AUTH_FAILED`：该 Connector 凭据失败，不影响其他 Client。
- `MISCONFIGURED`：必需凭据缺失、被停用或无法解析。控制面保留 Connector
  与历史，但不向 Runtime 下发该 Connector，也拒绝其延迟到达的入站消息。
- `STALE`：控制面长时间未收到 Runtime 心跳。
- `STOPPED`：管理员停用或 Runtime 未加载。

出现 `MISCONFIGURED` 时，在渠道编辑页重新填写 Client Secret 并保存，系统会
轮换或迁移到平台凭据引用。随后执行“测试配置”；该测试只确认已保存引用可以
安全解析，不会向钉钉发起网络请求。测试通过后 Runtime 会在下一次 reconcile
重新加载该 Connector；实际可用性仍以 `READY` 为准。一个 Connector
配置异常不得阻断其他 Connector 的配置下发。

## 回滚

如需临时回滚，先停止 `dingtalk-runtime`，确认租约释放和全部连接断开，再单独
恢复旧 Worker。任何时刻只允许一种 Stream Runtime 连接同一组钉钉应用。
