## ADDED Requirements

### Requirement: Agent 入口选择必须展示启用的 Webhook
Agent 配置 SHALL 展示启用的 Webhook 入口并将选择固定到 Publication；Webhook 本身无需反向固定 Agent。新发布 MUST 验证入口启用，应用只使用已发布的入口集合。

#### Scenario: Webhook 先于 Agent 创建
- **WHEN** 管理员创建启用 Webhook 后编辑 Agent
- **THEN** 入口列表可选该 Webhook，发布 Agent 不要求 Webhook 已绑定 Agent 或应用
