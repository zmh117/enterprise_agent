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

`docker-compose.yml` 已移除旧的 `dingtalk-stream-ingress` 服务。当前仓库只提供
`dingtalk-runtime` 这条 Stream 接入路径；不要从历史镜像另行启动旧 Worker，否则同一
钉钉应用可能产生重复连接和重复事件。

## 后续新增机器人

后续在“业务应用 → 渠道与触发器”先选择或创建“钉钉企业”，再新增钉钉应用机器人：

```text
创建待验证企业
  -> 应用连接选择该企业
  -> Web 保存 Connector 和 Platform Secret
  -> config revision 变化
  -> Runtime reconcile
  -> 只启动或重建对应 Client
  -> 发送一条真实测试消息确认 Corp ID
```

企业名称由管理员维护；Corp ID 只能从该应用收到的受信消息固化，不能手工输入或
编辑。首条验证消息只保存企业验证证据，不创建身份候选、应用访问或 Agent Job。
验证完成后，同一企业可以继续新增多个应用连接，并复用企业内人员身份；应用访问
仍由各自命中的 Business Application Publication 决定。

不修改 Compose、不重启其他机器人，也不挂载 Docker Socket。

## 企业生命周期与影响

- `PENDING_VERIFICATION`：等待某个已连接应用的真实测试消息确认 Corp ID。
- `ACTIVE`：企业已验证，其启用应用可以进入业务渠道候选。
- `DISABLED`：企业下全部应用停止进入业务渠道候选，身份记录与历史仍保留。
- `ARCHIVED`：治理归档态；归档前必须停用企业下的应用连接。

企业停用、归档或恢复前，页面列出受影响应用连接和业务应用引用。恢复不会沿用旧
验证结论，而是回到 `PENDING_VERIFICATION` 并要求重新发送测试消息。删除单个
应用连接前，页面同样列出业务应用草稿／发布引用；有引用时必须先移除并重新发布。

## 状态解释

- `READY`：连接已完成 SDK 注册，可以接收回调。
- `CONNECTED`：WebSocket 已连接。它是连接运行态，不表示企业已经验证，也不应
  因 SDK 的瞬时 `registered=false` 被展示为“待注册”。
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

页面始终把“企业生命周期”和“连接运行状态”分开显示。若运行状态为
`CONNECTED`、企业状态仍为 `PENDING_VERIFICATION`，页面显示“已连接，等待企业
验证”，并提示发送测试消息；这不是连接失败。

## 消息与 Corp ID 排障

企业验证或业务消息必须同时满足：来源 Connector 引用目标企业、企业处于允许状态，
且 `senderCorpId`／`chatbotCorpId` 与已固化 Corp ID 一致。Corp ID 缺失或不一致时
平台失败关闭，不自动换绑企业，也不创建 Agent Job；审计只记录安全错误码，不保存
消息正文或认证材料。

无回复时按以下证据链排查，而不是只看心跳：

```text
Runtime -> channel_ingress_event -> channel_ingress_outbox
        -> Agent Job -> Agent Worker -> Delivery
```

## 停用与恢复

需要停止接入时，在管理面停用目标 Connector，等待 reconcile 停止对应 Client；需要
停掉整个 Runtime 时，先停止 `dingtalk-runtime` 并确认租约释放。恢复使用当前
`dingtalk-runtime` 和受管 Connector revision。仓库没有可直接切回的旧
`dingtalk-stream-ingress` 服务，不能把历史 Worker 当作当前回滚步骤。
