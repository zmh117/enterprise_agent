## ADDED Requirements

### Requirement: 业务应用显式采用 Webhook 结果配置
业务应用 SHALL 支持 `webhook_result` 投递绑定，Connector 指向该应用所绑定的 Webhook 入口。该绑定 MUST 使用事件已经冻结的 Trigger Publication 结果路线，不用应用 target_reference 覆盖接收人。系统 MUST 校验唯一匹配绑定及一致的 Agent Publication，并继续服务账号业务授权；已有其他投递绑定不自动转换。

#### Scenario: Webhook 结果投递绑定
- **WHEN** 已激活应用匹配 Webhook，绑定授权使用该入口的结果配置且 Agent 发布一致
- **THEN** Job 保留冻结接收人列表，Agent 完成后按列表投递

#### Scenario: 不匹配或重复绑定
- **WHEN** 绑定引用其他入口或出现多个可用的结果绑定
- **THEN** 发布或运行时拒绝，不回退任意接收人
