## ADDED Requirements

### Requirement: 钉钉身份拒绝事件生成安全发现记录

系统 SHALL 在已认证且已持久化的钉钉 Channel event 明确因身份从未绑定、身份停用或解绑、或所属用户停用而拒绝时，幂等生成安全的未绑定身份发现记录，并 SHALL 保持拒绝响应、不创建 Agent session、Agent Job、user message 或 RabbitMQ Job 消息。

#### Scenario: 未绑定身份事件被拒绝

- **WHEN** 一个有效钉钉 Channel event 无法解析到任何历史外部身份
- **THEN** 系统 SHALL 在返回现有未授权结果前持久化安全发现记录，且不得进入 Agent 调度链路

#### Scenario: 历史身份不可用事件被拒绝

- **WHEN** 一个有效钉钉 Channel event 对应停用、已解绑身份或停用系统用户
- **THEN** 系统 SHALL 持久化可关联原人员的安全发现记录，且不得把身份解析为其它用户

#### Scenario: 重复拒绝事件

- **WHEN** 同一来源渠道事件因重试再次进入身份拒绝处理
- **THEN** 系统 SHALL 幂等确认已有发现记录，不得创建重复发现消息、Agent Job 或 RabbitMQ Job 消息

#### Scenario: 发现投影提交失败

- **WHEN** 系统无法在身份拒绝事务中安全提交发现投影
- **THEN** 系统 SHALL 保持 fail-closed、不得创建 Agent Job，并返回不含消息正文或敏感信息的可重试错误分类
