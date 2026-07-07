## ADDED Requirements

### Requirement: DingTalk delivery credentials are never exposed in audit records
系统 SHALL 在钉钉企业 App 和 webhook 群机器人投递过程中屏蔽 Client Secret、access token、webhook token、签名密钥、完整 webhook URL 和敏感接收人信息。

#### Scenario: Delivery attempt is recorded
- **WHEN** 系统记录 DingTalk delivery attempt
- **THEN** target summary 和 audit payload 只包含 connector ID、route type、目标安全摘要和分片数量，不包含任何密钥或完整 URL

#### Scenario: DingTalk provider returns an error
- **WHEN** 钉钉 API 或 webhook 返回错误
- **THEN** 系统保存安全错误摘要，不保存 access token、签名串、完整请求体中的敏感字段或完整 webhook URL

### Requirement: DingTalk delivery connector authorization is enforced
系统 SHALL 在钉钉企业 App 和 webhook 群机器人投递前校验 connector 存在、启用、允许 delivery，并记录授权决策。

#### Scenario: Delivery connector is allowed
- **WHEN** Agent job 使用允许 delivery 的 DingTalk connector
- **THEN** 系统记录 connector delivery 授权成功并继续投递

#### Scenario: Delivery connector is not allowed
- **WHEN** Agent job 使用未启用或不允许 delivery 的 DingTalk connector
- **THEN** 系统阻止投递、记录授权失败，并不发起外部钉钉请求

### Requirement: DingTalk webhook robot ingress attempts are audited
系统 SHALL 对 webhook 群机器人被误用为入口的请求记录审计事件，说明该 connector 只允许 delivery。

#### Scenario: Webhook robot ingress is rejected
- **WHEN** 请求尝试通过 webhook 群机器人 connector 创建 Agent job
- **THEN** 系统记录入口拒绝审计事件，并且不持久化 Agent session、Agent job 或 queue message
