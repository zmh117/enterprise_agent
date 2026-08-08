## ADDED Requirements

### Requirement: 受管 Webhook 的结果路由由 Trigger publication 固定
系统 SHALL 使用 Webhook event 固定的 Trigger publication 构造 reply route，MUST NOT 接受外部 payload 提供任意 Delivery type、Connector、endpoint、token 或目标会话。

#### Scenario: Grafana 告警完成诊断
- **WHEN** Webhook Agent job 成功并生成最终报告
- **THEN** ResultDeliveryService 使用 Trigger publication 固定的钉钉 Connector 和安全目标分片投递结果

#### Scenario: payload 包含钉钉 Webhook URL
- **WHEN** 外部 payload 包含自定义 Webhook URL 或 delivery target
- **THEN** 系统不把该值写入 reply route、job 或外部请求

### Requirement: Trigger Delivery 失败不得重新执行 Agent
系统 SHALL 把受管 Webhook 的 Agent 执行状态与 Delivery attempt 分开；投递失败 MUST NOT 将 Webhook event重新分发或重跑 Agent。

#### Scenario: 钉钉临时不可用
- **WHEN** Agent job 已成功但固定钉钉 Delivery 返回临时错误
- **THEN** 系统保留 job 成功状态并按 Delivery 策略重试或标记投递失败，不创建新 job

### Requirement: Webhook 事件页关联 Delivery 证据
系统 SHALL 允许授权管理员从 Webhook event 查看关联 job、Delivery attempt 和 chunk 状态的安全摘要，而不复制完整目标凭证或报告正文。

#### Scenario: 查看分片投递结果
- **WHEN** 长报告被拆分为多个钉钉消息
- **THEN** 事件页展示分片总数、成功/失败状态和安全错误摘要
