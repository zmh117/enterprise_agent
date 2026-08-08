## ADDED Requirements

### Requirement: 受管 Webhook 在进入 Channel 前固定来源配置
系统 SHALL 从已发布 Trigger 生成 Channel event，并 MUST 固定 Trigger publication、Agent publication、服务账号、routing policy 和 Delivery 引用后再调用通用 Channel ingress。

#### Scenario: 受管 Webhook 生成 Channel event
- **WHEN** Webhook event 通过认证、映射、过滤、幂等和服务账号权限预检
- **THEN** dispatcher 使用事件中固定的 publication 引用生成 Channel event 并创建 Agent job

#### Scenario: Trigger 在排队期间发布新 revision
- **WHEN** event 已进入 Inbox 后管理员发布新的 Trigger revision
- **THEN** 该 event 仍使用接收时固定的 Trigger 和 Agent publication，不读取新草稿或当前指针

### Requirement: 标准化 Channel event 不携带原始 Webhook payload
系统 SHALL 只把有界 message、受控 routing、来源标识和固定 reply route 交给 Channel ingress，MUST NOT 将完整原始 payload、认证 header、nonce 或 secret 写入 session、job、消息队列或 Agent prompt。

#### Scenario: 第三方 payload 包含敏感扩展字段
- **WHEN** Webhook body 除映射字段外还包含 token、URL、个人信息或大对象
- **THEN** 标准化 Channel event 排除这些未声明字段，只保留脱敏安全摘要
