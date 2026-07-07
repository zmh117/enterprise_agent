## ADDED Requirements

### Requirement: DingTalk enterprise App can receive final Agent results
系统 SHALL 支持通过钉钉企业 App 出口将最终报告或失败通知发送回配置的钉钉目标，目标可以来自 reply route 或 connector 默认配置。

#### Scenario: Reply route contains enterprise target
- **WHEN** Agent job 的 reply route 指定企业 App 钉钉目标
- **THEN** 系统使用该目标发送最终报告，并将投递结果关联到原 Agent job

#### Scenario: Reply route omits enterprise target
- **WHEN** Agent job 的 reply route 使用 `dingtalk_enterprise_robot` 但未显式指定目标
- **THEN** 系统使用 connector metadata 中的默认钉钉目标；若默认目标缺失则标记 delivery 配置失败

### Requirement: DingTalk webhook robot is not a user-question ingress
系统 SHALL 将钉钉 webhook 群机器人限定为结果出口能力，MUST NOT 通过该 connector 接收用户问题或创建 Agent job。

#### Scenario: User sends message to webhook robot
- **WHEN** webhook 群机器人相关请求到达系统入口
- **THEN** 系统不会把该请求解析为用户问题，也不会创建 Agent job

#### Scenario: Webhook robot receives final report
- **WHEN** Agent job 使用 `dingtalk_webhook_robot` 作为 delivery route
- **THEN** 系统把最终报告作为群消息发送到配置的钉钉群机器人 webhook

### Requirement: DingTalk delivery uses safe acknowledgement and failure semantics
系统 SHALL 将钉钉投递结果与 Agent 执行结果分离，钉钉发送失败 MUST NOT 改写已经成功或失败的 Agent job 执行状态。

#### Scenario: DingTalk delivery fails after Agent success
- **WHEN** Agent job 已经 SUCCEEDED 但钉钉企业 App 或 webhook 群机器人发送失败
- **THEN** 系统只更新 delivery attempt/chunk 状态并记录安全错误摘要，Agent job 保持 SUCCEEDED
