## ADDED Requirements

### Requirement: 每个入口独立配置结果去向
新业务应用草稿和 Publication SHALL 将每条 Delivery 明确关联到一个 Trigger 的类型、连接器和规范化路由键。每个 Trigger MUST 至多有一个投递方式；未引用、重复或不存在的入口关联 MUST 返回定位到字段的错误。钉钉入口 MUST 使用与入口连接器一致的回复原会话；Webhook SHALL 支持仅保存结果、钉钉私聊、钉钉群或高级 HTTP 回调。

#### Scenario: 保存多人员投递
- **WHEN** 用户为 Webhook 选择钉钉私聊并选择最多 20 个不同目标人员
- **THEN** 管理 API 接受 target_user_ids 并保存入口关联，发布前复核企业与身份；空人员表示不发送

#### Scenario: 修改或删除入口
- **WHEN** 用户修改入口身份或删除触发器
- **THEN** 编辑器同步更新对应投递引用或删除该投递，不改变其他入口的投递

#### Scenario: 消息流向可见
- **WHEN** 用户查看组成配置
- **THEN** 每个触发器卡片展示入口、Agent 和自己的结果去向；保存错误展示在固定保存区

#### Scenario: 旧草稿存在未使用投递
- **WHEN** 原独立投递不能唯一归属于入口
- **THEN** 编辑器明确展示待处理配置并要求用户移除后保存，不静默丢弃或分配到其他入口
