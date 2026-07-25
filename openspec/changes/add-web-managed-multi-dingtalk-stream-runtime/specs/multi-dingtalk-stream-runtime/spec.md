## ADDED Requirements

### Requirement: 单个 Runtime 动态维护多个 Stream Client
系统 SHALL 在一个 `dingtalk-runtime` 实例中为每个已启用的钉钉应用机器人 Connector 维护一个独立 Stream Client。

#### Scenario: 动态增加第二个机器人
- **WHEN** 控制 API出现第二个已启用且配置完整的钉钉 Connector
- **THEN** Runtime 在协调周期内创建第二个 Client，且不重启或断开第一个 Client

#### Scenario: 停用单个机器人
- **WHEN** Connector A 被停用而 Connector B 保持启用
- **THEN** Runtime 只断开并移除 A 的 Client，B 保持连接

#### Scenario: 配置 revision 变化
- **WHEN** Connector A 的加载 revision 与控制面最新 revision 不一致
- **THEN** Runtime 串行停止旧 A Client 并创建新 A Client，不重建其他 Client

### Requirement: Client 生命周期操作必须串行和幂等
系统 SHALL 为每个 Connector 串行执行 start、stop、restart 和 SDK 自动重连协调，MUST NOT 因重叠 reconcile 创建重复 Client。

#### Scenario: 重连时再次收到 reconcile
- **WHEN** Client 正在 RECONNECTING 且新的协调周期读取到相同 revision
- **THEN** Runtime 不创建第二个 Client，也不重置当前退避

#### Scenario: 停止发生在异步连接期间
- **WHEN** 管理员在 Client 仍处于 STARTING 时停用 Connector
- **THEN** Runtime 取消后续注册、清理重连定时器并最终上报 STOPPED

### Requirement: READY 以订阅注册完成为准
系统 SHALL 仅在 SDK 已完成注册时上报 READY；WebSocket 打开或 `connect()` 返回本身不得视为可用。

#### Scenario: WebSocket 打开但尚未注册
- **WHEN** SDK connected 为 true 但 registered 仍为 false
- **THEN** Runtime 保持 STARTING 或 CONNECTED_NOT_REGISTERED，不上报 READY

#### Scenario: 注册完成
- **WHEN** SDK 收到 REGISTERED 状态并设置 registered 为 true
- **THEN** Runtime 上报 READY、loaded revision 和 connected timestamp

#### Scenario: 认证或注册失败
- **WHEN** endpoint 获取或订阅注册因无效凭据失败
- **THEN** Runtime 上报 AUTH_FAILED 或安全 ERROR，不把 `connect()` 的正常返回误报为 READY

### Requirement: Runtime 上报心跳和安全观测状态
系统 SHALL 周期性上报 Runtime 心跳及各 Connector 的状态、加载 revision、最近消息时间和安全错误摘要。

#### Scenario: Client 收到消息
- **WHEN** 某个 Connector Client 收到受支持的钉钉消息
- **THEN** Runtime 更新该 Connector 的 last_message_at，不修改其他 Connector 的状态

#### Scenario: SDK 错误包含敏感数据
- **WHEN** SDK 错误或响应中包含 ticket、Secret、sessionWebhook 或完整 endpoint
- **THEN** Runtime 只上报稳定错误码和脱敏摘要

### Requirement: 控制面不可用时保留健康连接
系统 SHALL 在配置读取或状态上报短暂失败时保留当前健康 Client，并在控制面恢复后继续协调。

#### Scenario: 一次配置轮询失败
- **WHEN** Runtime 无法从内部控制 API读取最新期望快照
- **THEN** Runtime 不批量停止现有 Client，记录降级状态并按退避重试

#### Scenario: 控制面恢复
- **WHEN** 后续配置轮询成功
- **THEN** Runtime 根据成功读取的完整快照执行新增、停用和 revision 差异协调

### Requirement: Runtime 容器重启后恢复全部启用 Connector
系统 SHALL 在 Runtime 重启并取得单实例租约后，从控制面重新加载所有已启用钉钉 Connector。

#### Scenario: Runtime 正常重启
- **WHEN** Runtime 进程重启且存在多个 enabled Connector
- **THEN** Runtime 为每个配置完整的 Connector 恢复独立 Client 并重新上报状态

#### Scenario: 单个 Connector 配置无效
- **WHEN** 恢复过程中一个 Connector 缺少有效凭据
- **THEN** 该 Connector 进入 AUTH_FAILED 或 ERROR，其他 Connector 继续启动

### Requirement: MVP 只允许一个 Runtime 持有活动租约
系统 SHALL 通过内部控制 API的短租约确保同一时刻只有一个 `dingtalk-runtime` 加载 Connector。

#### Scenario: 第二个 Runtime 启动
- **WHEN** 已有未过期的 singleton 租约且第二个 runtime_id 请求租约
- **THEN** 控制面拒绝授予租约，第二个 Runtime 退出且不创建 Client

#### Scenario: 原 Runtime 租约过期
- **WHEN** 原 Runtime 不再续约且租约超过有效期
- **THEN** 新 Runtime 可以取得租约并从控制面恢复 Connector

### Requirement: Runtime 不承担 Agent 和结果投递职责
`dingtalk-runtime` MUST NOT 选择 Agent、创建 Agent Job、执行 Agent、消费 Agent 结果或持有 Agent 模型凭据。

#### Scenario: 收到用户消息
- **WHEN** Stream Client 收到钉钉用户消息
- **THEN** Runtime 只提交内部 Channel Inbox 请求并完成钉钉 ACK，不直接调用 Agent

#### Scenario: Agent 产生结果
- **WHEN** 现有 Agent Worker 完成既有 Job
- **THEN** 结果继续由现有 Python Result Delivery 链路发送，Runtime 不消费新的 reply queue
