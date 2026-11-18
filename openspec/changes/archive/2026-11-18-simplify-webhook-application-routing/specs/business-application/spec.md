## ADDED Requirements

### Requirement: 应用 Webhook 入口必须来自所选 Agent 的发布配置
系统 SHALL 仅允许选择所选 Agent Publication 允许且当前启用的 Webhook，自动确定路由与机器身份；MUST NOT 要求用户填写主体 ID 或路由键，服务端必须重验并拒绝伪造入口。

#### Scenario: 切换 Agent
- **WHEN** 应用切换到未允许原 Webhook 的 Agent 发布版本
- **THEN** 原绑定明确失效并阻止发布，要求重新选择入口

### Requirement: 应用统一配置 Webhook 结果投递
系统 SHALL 允许应用选择钉钉私聊机器人与最多 20 名内部目标人员，或在高级区选择受管 HTTP 回调。系统 MUST 删除 webhook_result 选项与对 Trigger 投递的依赖；无投递绑定或私聊名单为空时使用 none 路由。目标人员必须启用且具有该机器人企业的有效钉钉绑定。

#### Scenario: 多人钉钉私聊
- **WHEN** 应用配置启用机器人和多名有效人员并发布
- **THEN** Publication 固定各目标身份，结果分别发送，失败按目标独立记录

#### Scenario: 没有目标人员
- **WHEN** 应用私聊投递未选择人员或未配置结果投递
- **THEN** Agent 正常执行并保存结果，不创建外部消息

#### Scenario: 高级 HTTP 回调
- **WHEN** 应用选择具备出站能力的受管 HTTP Connector 与安全目标引用
- **THEN** 系统固定回调路由；不允许外部 payload 或应用表单传入任意 URL/凭据
