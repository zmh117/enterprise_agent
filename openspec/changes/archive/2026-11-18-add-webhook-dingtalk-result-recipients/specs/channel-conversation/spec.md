## ADDED Requirements

### Requirement: Webhook 在 Web 配置多个钉钉结果接收人
Web SHALL 提供钉钉应用机器人、群/用户类型、稳定目标 ID 和备注的列表编辑器，允许 1–20 个不同接收人。发布 MUST 冻结接收人，校验目标形状、机器人状态和 Agent 投递授权。Webhook payload MUST NOT 改写目标。新建后和再次编辑均 SHALL 可完成该配置。

#### Scenario: 保存多个群和用户
- **WHEN** 管理员添加同一或不同受管机器人的群和用户并保存、校验、发布
- **THEN** 发布包含规范化列表，重开页面恢复所有行；重复对象、空目标和越界数量被拒绝

#### Scenario: 未授权机器人
- **WHEN** Agent 发布未分配任一所选机器人为结果投递
- **THEN** 校验和发布拒绝并定位对应接收人，不自动扩大 Agent 权限

### Requirement: Webhook 停用独立于配置健康
已授权管理员 SHALL 能从渠道卡片或配置页面停用 Webhook，即使入口或凭据已不可用或表单存在未保存修改。操作 MUST 使用 revision 冲突保护并保留未保存编辑。停用 MUST 拒绝新接收和尚未创建 Job 的事件分发；已创建任务及其冻结结果投递继续执行。

#### Scenario: 故障入口停用
- **WHEN** 原 Connector 已停用或凭据不可解析，管理员提交正确 revision 停用且未更换 Connector
- **THEN** 定义成功停用，不要求修复入口后再停用

#### Scenario: 表单未保存
- **WHEN** 已启用 Webhook 有未保存编辑，管理员点击停用
- **THEN** 停用成功且输入保留，发布和启用旧草稿的保护仍然生效
