## REMOVED Requirements

### Requirement: 受管 Webhook 的结果路由由 Trigger publication 固定
**Reason**: 结果投递统一归业务应用管理。
**Migration**: 旧 Webhook 重新配置发布，并将接收人迁至应用的投递绑定；不保留旧 Trigger 投递的执行分支。

## ADDED Requirements

### Requirement: Webhook 结果必须按应用固定投递且复核人员归属
Webhook Job 的结果路由 SHALL 来自事件命中的应用 Publication。钉钉私聊目标 SHALL 从内部人员的同企业有效绑定解析并冻结，发送前 MUST 复核启停、绑定归属、机器人可用及执行主体当前应用权限。外部 payload 不得指定投递 Connector、URL、目标或凭据。

#### Scenario: 人员解绑或停用
- **WHEN** 结果准备发送时目标人员已停用或原钉钉绑定失效
- **THEN** 停止该目标投递，不改投新绑定或其他人，保留独立失败状态

#### Scenario: 单个接收人失败
- **WHEN** 多名接收人中的一个发送失败
- **THEN** 按目标独立重试，不重跑 Agent，不重发已成功目标

#### Scenario: 无人接收
- **WHEN** 冻结的私聊目标名单为空
- **THEN** 使用 none 路由保存结果并记录跳过投递
