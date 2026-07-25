## ADDED Requirements

### Requirement: 受管入口 Connector 提供配置 revision
系统 SHALL 为 Web 管理的入口 Connector 提供单调递增 revision，并允许 Runtime 使用 revision 判断是否需要重建连接。

#### Scenario: 非敏感配置变化
- **WHEN** 管理员修改钉钉 Client ID、聊天策略或其他 Runtime 相关配置
- **THEN** 系统递增 Connector revision，Runtime 只重建该 Connector

#### Scenario: 请求强制重连
- **WHEN** 管理员请求重连但未修改字段
- **THEN** 系统递增 Connector revision 并记录审计，使 Runtime 重建该 Connector

### Requirement: 受管 Channel 目录按 Trigger 类型校验 Connector
系统 SHALL 根据 Connector 类型、enabled、allow_ingress 和配置完整性决定其支持的 Business Application Trigger 类型。

#### Scenario: 钉钉 Stream Connector 可用于私聊和群聊
- **WHEN** `dingtalk_enterprise_stream` Connector 已启用、允许 ingress 且配置完整
- **THEN** 系统将其标记为支持 `dingtalk_private` 和 `dingtalk_group`

#### Scenario: Delivery-only Connector 被查询
- **WHEN** `dingtalk_webhook_robot`、email 或其他 delivery-only Connector 出现在配置库
- **THEN** 系统不把它列为 Business Application Trigger 可选 Channel

### Requirement: 管理端明文凭据转换为现有 Secret reference
系统 SHALL 在受保护写接口内把一次性明文凭据转换为现有平台受管 Secret reference，Connector 仍只保存 reference。

#### Scenario: 查询 Connector
- **WHEN** 管理端读取已经配置 Secret 的 Connector
- **THEN** API 返回 Secret 已配置状态和 mask，不返回 platform secret ciphertext、nonce 或明文

#### Scenario: Connector 审计
- **WHEN** 系统记录 Connector 创建、轮换、启停或重连
- **THEN** 审计只包含 Connector ID、revision、动作和 actor，不包含 Client Secret
