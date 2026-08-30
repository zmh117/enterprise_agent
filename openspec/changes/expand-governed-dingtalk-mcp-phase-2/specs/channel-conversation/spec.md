## ADDED Requirements

### Requirement: 主动机器人消息必须绑定当前 Job 来源会话
系统 SHALL 从当前 Job 冻结的 Channel 来源与回复路由解析 `dingtalk_send_robot_message` 的 conversation type、open conversation ID、当前 sender staff ID 和 Connector robot code。群聊只能发送到当前群，私聊只能发送给当前发起人；这些值 MUST NOT 由模型、JWT 或 Tool 参数提供。

#### Scenario: 群聊来源准备机器人消息
- **WHEN** 已授权用户在钉钉群聊 Job 中请求发送机器人消息
- **THEN** Action Intent 冻结当前群的来源会话事实并向原用户投放确认卡

#### Scenario: 请求指定其它群
- **WHEN** Agent 参数包含其它 open conversation ID、robot code 或用户列表
- **THEN** Tool schema 或目标解析拒绝请求且不创建 Intent

### Requirement: 主动消息不得替代普通 Agent 结果投递
`dingtalk_send_robot_message` SHALL 被视为独立、受确认的外部 mutation；普通 Agent 最终回答仍通过既有 Delivery route 投递。系统 MUST NOT 因 Tool 发送成功而跳过最终结果，也不得因最终结果投递重试而重发 Tool 消息。

#### Scenario: 主动消息发送成功
- **WHEN** 确认后的机器人消息 Provider attempt 成功
- **THEN** Intent 记录唯一发送结果，当前 Agent Job 仍独立生成并投递最终回答

#### Scenario: 最终回答投递重试
- **WHEN** Agent 最终回答 Delivery 发生可重试失败
- **THEN** Delivery 只重试最终回答，不重新执行已成功的机器人消息 Intent
