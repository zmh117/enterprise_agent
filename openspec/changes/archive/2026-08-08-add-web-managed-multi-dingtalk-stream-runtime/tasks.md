## 1. 后端契约与迁移基线

- [x] 1.1 盘点现有 Connector、Platform Secret、Managed Webhook、Business Application Trigger 和 Channel Ingress DTO，记录必须复用的字段与服务
- [x] 1.2 定义统一 Managed Channel DTO、钉钉应用机器人写入 DTO、Runtime 配置 DTO、运行状态 DTO 和 eligible Channel DTO
- [x] 1.3 明确 `WEBHOOK` 与 `DINGTALK_APP_ROBOT` 到现有 Connector/Trigger 类型的映射，并为未开放 provider 编写拒绝用例
- [x] 1.4 为内部 Runtime API定义服务认证、错误码、分页/修订语义和禁止记录的敏感字段
- [x] 1.5 增加迁移，创建 `channel_connector_runtime`、Runtime singleton lease、`channel_ingress_event` 和 `channel_ingress_outbox`
- [x] 1.6 保持迁移使用应用生成 TEXT ID、JSON 字符串和现有时间格式，分别验证 SQLite 内存库与 PostgreSQL 18
- [x] 1.7 为 Connector 级事件幂等、Outbox claim、Runtime 状态和 lease 到期建立必要唯一约束与索引

## 2. 受管 Channel 后台管理

- [x] 2.1 在 Channel 领域增加 provider adapter 接口，使统一管理服务委托现有 DingTalk Connector 与 Managed Webhook 服务
- [x] 2.2 实现 Managed Channel 列表和详情查询，只返回 Webhook 与钉钉应用机器人及安全运行摘要
- [x] 2.3 实现钉钉应用机器人创建，校验 Client ID、tenant/corp、聊天策略并创建 `dingtalk_enterprise_stream` Connector
- [x] 2.4 复用 Platform Secret 服务保存首次 Client Secret，并确保 Connector 只保存 secret reference
- [x] 2.5 实现钉钉应用机器人编辑与 Secret 留空保留、显式轮换语义
- [x] 2.6 实现 enable、disable、restart 和软删除，所有写操作执行 expected revision 校验
- [x] 2.7 删除前检查 Business Application Publication/活动 Trigger 引用并返回安全引用摘要
- [x] 2.8 通过现有 Managed Webhook 服务实现统一 Webhook Channel 投影和配置入口，不复制认证、public ID 或映射逻辑
- [x] 2.9 实现按 trigger type 查询 eligible Channel，只返回 enabled、allow_ingress 且 provider 兼容的项
- [x] 2.10 在 Business Application 保存、校验和发布阶段重新校验 Channel eligibility，拒绝停用或类型不匹配的绑定
- [x] 2.11 为 Channel read/manage/restart/delete 接入 RBAC、CSRF 和安全审计
- [x] 2.12 确保所有管理响应不返回 secret_ref 可解析值、ciphertext、nonce、Client Secret 或完整敏感 endpoint

## 3. Runtime 内部控制 API

- [x] 3.1 增加仅供 `dingtalk-runtime` 使用的服务认证依赖，并使用 Compose Secret 提供 bootstrap credential
- [x] 3.2 实现 Runtime singleton lease 获取、续约和释放的事务比较更新
- [x] 3.3 实现完整期望配置快照接口，只返回 enabled 的 `dingtalk_enterprise_stream` Connector
- [x] 3.4 在受认证请求内解析 Client ID/Client Secret，并保证响应、中间件、日志和异常处理不记录明文
- [x] 3.5 实现 Connector 运行状态和 Runtime 心跳上报，校验 runtime_id、lease 和 loaded revision
- [x] 3.6 实现服务端 STALE 计算，心跳过期时覆盖上一次 READY 展示
- [x] 3.7 实现内部 DingTalk Channel Inbox 接口，校验 Runtime 身份、Connector ingress 权限、消息大小和标准化字段
- [x] 3.8 为内部 API增加限流、有界超时、安全错误码和审计测试

## 4. 可靠 Channel Inbox/Outbox

- [x] 4.1 实现 `(connector_id, external_event_id)` 幂等写入 `channel_ingress_event`
- [x] 4.2 在同一数据库事务中写入 Channel Inbox 和对应 Outbox
- [x] 4.3 只保存 payload hash、安全摘要、有界标准化事件和处理必需字段，不保存完整 raw payload
- [x] 4.4 使用现有加密能力保护 sessionWebhook 等短期回复凭据，并阻止其进入审计和错误摘要
- [x] 4.5 实现 Outbox claim、发布、重试、claim 超时恢复和 dead 状态
- [x] 4.6 声明 Channel dispatch RabbitMQ topology，消息体只包含 channel event ID 与 correlation ID
- [x] 4.7 实现 Python Channel Dispatcher，从受控存储加载事件并调用现有 `ChannelIngressService`
- [x] 4.8 保持未命中 Business Application 时返回现有配置错误，不增加默认 Agent fallback
- [x] 4.9 为重复事件、不同 Connector 相同消息 ID、RabbitMQ 中断恢复和 Publisher 崩溃恢复编写集成测试
- [x] 4.10 使用 mock/fake 下游验证 Dispatcher 契约，不新增或修改 Agent 执行和并行逻辑

## 5. TypeScript 多 Client Runtime

- [x] 5.1 创建独立 `dingtalk-runtime` TypeScript 包、锁定依赖版本并配置 lint、typecheck 和 test
- [x] 5.2 封装钉钉 Node SDK，暴露 connect、disconnect、connected、registered、reconnecting 和安全事件
- [x] 5.3 实现每 Connector 独立的 Managed Client 状态机和串行操作锁
- [x] 5.4 实现配置 reconcile：新增启动、停用停止、revision 变化重建、快照外连接清理
- [x] 5.5 确保配置 API单次失败时保留现有健康 Client，不执行 destructive reconcile
- [x] 5.6 READY 只由 REGISTERED/registered 状态产生，并覆盖 WebSocket 打开但未注册、认证失败和自动重连测试
- [x] 5.7 实现 singleton lease 获取和续约，第二 Runtime 无租约时退出且不加载 Client
- [x] 5.8 实现 Runtime/Connector 心跳、最近消息、loaded revision 和安全错误上报
- [x] 5.9 实现 SDK 回调标准化和内部 Inbox API提交，仅在持久化成功或幂等命中后 ACK
- [x] 5.10 对控制 API超时、Inbox 写入失败和钉钉重复投递实现有界重试，不在 Runtime 执行 Agent
- [x] 5.11 实现 SIGTERM/SIGINT 优雅退出，逐个 disconnect、停止重连定时器并释放租约
- [x] 5.12 增加健康检查端点，只返回 Runtime 进程、租约和连接计数，不暴露 Connector Secret 或消息内容
- [x] 5.13 编写多 Client 单元测试，证明 A 的启动、停用、认证失败和 Secret revision 变化不影响 B

## 6. Compose 与单连接迁移

- [x] 6.1 为 `dingtalk-runtime` 增加多阶段 Dockerfile，镜像只包含运行所需 Node 产物与依赖
- [x] 6.2 在现有 Compose 中增加固定 `dingtalk-runtime` 服务、内部认证 Secret、健康检查和 restart policy
- [x] 6.3 保留当前 PostgreSQL 18、RabbitMQ 4、API、Agent Worker 和网络配置，不引入新的数据库或消息中间件
- [x] 6.4 增加把现有单机器人环境配置登记为 Connector 与 Platform Secret 的迁移/操作说明
- [x] 6.5 增加新旧 Runtime 切换保护，文档明确禁止同一钉钉应用被 Python Worker 和 TypeScript Runtime 同时连接
- [x] 6.6 验证新 Runtime 后移除旧单连接 `dingtalk-stream-ingress` Compose 服务及不再使用的启动环境变量
- [x] 6.7 验证 `docker compose config --quiet`、镜像构建、服务健康和 Runtime 重启恢复

## 7. 后端阶段验收门

- [x] 7.1 运行 Backend 全量 pytest、Ruff 和当前类型检查，并区分本变更与既有失败
- [x] 7.2 运行 dingtalk-runtime 单元测试、lint、typecheck 和构建
- [x] 7.3 使用 fake DingTalk SDK 验证动态新增两个机器人、独立停用、独立重连和 Runtime 重启恢复
- [x] 7.4 验证同一 external message ID 经两个 Connector 产生两条独立 Inbox/Outbox，单 Connector 重投只产生一条
- [x] 7.5 验证 RabbitMQ 不可用时 ACK 前数据已持久化、恢复后继续 dispatch，且队列不含 Secret/sessionWebhook
- [x] 7.6 验证无业务应用路由时沿用配置错误回复且不回退默认 Agent
- [x] 7.7 有两套真实钉钉凭据时验证两个 Client 均为 READY、各自接收消息和互不影响；无凭据时保留为明确未执行项
- [x] 7.8 形成后端验收记录；只有 7.1 至 7.6 全部通过后才允许开始前端任务

## 8. 业务应用渠道与触发器前端

- [x] 8.1 在前端 Business Application 上下文增加 Managed Channel 与 eligible Channel API client 和类型
- [x] 8.2 在左侧“业务应用”分组的“应用列表”下增加同级“渠道与触发器”菜单和独立 `/applications/channels` 路由；移除应用详情中的 Channel 管理 Tab
- [x] 8.3 实现 Channel 列表，显示 provider、enabled、有效运行状态、最近消息、最近错误和 revision
- [x] 8.4 实现钉钉应用机器人创建/编辑表单，Secret 编辑留空表示不修改，响应中不展示原值
- [x] 8.5 实现 Webhook 配置入口并复用现有 Managed Webhook 表单/接口，不新增任意 HTTP 或其他 provider
- [x] 8.6 实现 Channel enable、disable、restart 和受引用删除错误展示
- [x] 8.7 将 Trigger Binding 的 Connector 自由输入改为 eligible Channel 选择器
- [x] 8.8 根据 trigger type 过滤 Webhook、钉钉私聊和钉钉群聊可选项，并展示停用/失效旧绑定
- [x] 8.9 保持应用草稿、校验、发布、激活的现有生命周期；Channel 选择不直接修改已发布版本
- [x] 8.10 确认独立 Channel 页面不修改应用草稿，应用设置只选择 eligible Channel，且页面不出现 Agent Profile、模型、工具、并行度和其他本次排除功能

## 9. 前端与端到端回归

- [x] 9.1 为独立路由、侧边栏顺序与单项高亮、Channel 列表、Secret 留空、revision conflict、状态轮询和错误态编写前端测试
- [x] 9.2 为 Trigger eligible selector、provider 过滤、失效绑定和发布前服务端拒绝编写前端测试
- [x] 9.3 完成页面迁移后重新运行 frontend test、lint/typecheck 和生产构建
- [x] 9.4 在浏览器验证新增钉钉机器人后无需重启 Compose 即更新为 STARTING/READY
- [x] 9.5 在浏览器验证停用 Channel 后不能新绑定，既有草稿显示失效且发布被服务端拒绝
- [x] 9.6 验证本变更没有新增 Agent 配置入口、没有修改 Agent Worker 并行行为、没有新增 reply queue
- [x] 9.7 运行 `openspec validate add-web-managed-multi-dingtalk-stream-runtime --strict` 并记录最终实现证据
