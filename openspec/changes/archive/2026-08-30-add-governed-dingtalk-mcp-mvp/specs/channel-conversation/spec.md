## ADDED Requirements

### Requirement: 唯一 DingTalk Stream Client 必须同时接收卡片回调
每个已启用 Connector 的现有 `dingtalk-runtime` Stream Client SHALL 在机器人消息 topic 之外注册固定 `/v1.0/card/instances/callback` topic。系统 MUST NOT 为卡片回调启动同 Client ID 的第二个 Stream Client。

#### Scenario: 同一 Connector 收到卡片点击
- **WHEN** 已注册的 Stream Client 收到卡片回调
- **THEN** runtime 在同一 lease 下将有限规范字段交给内部控制 API

### Requirement: 卡片回调 ACK 必须建立在持久状态转换之后
`dingtalk-runtime` SHALL 只在控制面完成幂等校验和 Action Intent 状态事务后 ACK；ACK MAY 更新卡片状态，但 MUST NOT 等待 Agent Job 或 Provider 执行完成。提交失败时不得 ACK，以允许钉钉重投。

#### Scenario: 合法同意被持久接受
- **WHEN** 控制面把意图从待确认原子转为已批准
- **THEN** runtime 返回包含按 key 更新卡片数据的成功 ACK

#### Scenario: 控制面暂时不可用
- **WHEN** runtime 无法持久提交回调
- **THEN** runtime 不 ACK 且日志只记录安全错误分类

