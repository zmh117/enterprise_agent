## ADDED Requirements

### Requirement: Agent 显式授权受管机器人结果投递
Agent 配置 SHALL 展示受管钉钉应用机器人的主动结果投递能力，允许在 channels.delivery 显式分配并冻结到 Publication。普通 Stream ingress 和普通通用 Delivery 能力 MUST 保持区分；专用结果路线只能使用被分配、启用且有效的机器人，不能借此访问任意 endpoint。

#### Scenario: 分配受管机器人
- **WHEN** 管理员为 Agent 选择受管机器人投递并发布
- **THEN** Webhook 可以引用该机器人用于固定群或用户结果投递；未经分配的机器人仍被拒绝
