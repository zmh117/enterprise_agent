## ADDED Requirements

### Requirement: Webhook 多接收人结果独立投递
系统 SHALL 为冻结接收人中的每个群或用户在结果事务内创建独立 Delivery Outbox，并以 Job、结果产物和稳定接收人 key 保证本地幂等。各对象 SHALL 独立 claim、重试、终态与审计；重试不得重复已成功对象，不得重新执行 Agent。发送前 MUST 校验目标仍属于 Job 冻结列表及对应机器人可用性。

#### Scenario: 群成功而用户暂时失败
- **WHEN** 一个群投递成功、一个用户被限流、其他目标可用
- **THEN** 其他目标继续投递，仅限流用户进入有限重试；已成功目标保持成功

#### Scenario: 重复入队和重复消费
- **WHEN** 同一结果重复创建 Outbox 或消费已成功记录
- **THEN** 不增加同目标重复 Outbox，不重新发送已成功分片

#### Scenario: 钉钉单聊业务失败
- **WHEN** 单聊响应包含目标 userId 的无效或限流结果
- **THEN** 判定该对象失败或可重试，不把 HTTP 200 视为投递成功

#### Scenario: 篡改投递绑定
- **WHEN** Outbox 的接收人 key 不存在于 Job 冻结列表或原路线 hash 不一致
- **THEN** 拒绝发送并记录安全错误
