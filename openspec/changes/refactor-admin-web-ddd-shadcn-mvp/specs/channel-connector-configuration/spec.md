## ADDED Requirements

### Requirement: Connector 提供 Secret 安全的 Web 管理契约
系统 SHALL 提供 Connector 的分页查询、详情、创建、更新、启停和绑定 API，允许管理钉钉 Stream、Callback 和 Delivery 配置；读取响应 MUST 只返回 Secret 引用与脱敏摘要，更新 SHALL 使用 revision 防止并发覆盖。

#### Scenario: 编辑钉钉 Delivery Connector
- **WHEN** 管理员提交合法方向、endpoint 引用、Secret 引用和 host allowlist
- **THEN** 系统保存新 revision、记录审计并返回脱敏后的 Connector

#### Scenario: 并发编辑 Connector
- **WHEN** 两个管理员基于同一旧 revision 更新 Connector
- **THEN** 后提交者收到冲突响应且现有配置不会被静默覆盖

### Requirement: Channel Provider 声明运行时支持状态
系统 SHALL 由后端目录返回 Provider 编码、允许方向、所需配置 schema 和 `available` 状态；Web 页面 SHALL 只允许创建 `available=true` 的 Provider。

#### Scenario: 展示已实现钉钉 Provider
- **WHEN** 后端将钉钉 Stream、Callback 或 Delivery Provider 标记为 available
- **THEN** Web 页面根据其 schema 渲染受支持配置表单

#### Scenario: 邮件 Provider 尚未实现
- **WHEN** 邮件或企业微信 Provider 仅保留扩展定义但 `available=false`
- **THEN** 页面不得允许创建或保存该类 Connector

### Requirement: Connector 配置变更可验证且不发送真实消息
系统 SHALL 提供配置校验能力检查方向、Secret 引用、endpoint host 和必填字段；普通校验 MUST NOT 发送真实外部消息，未来发送测试消息必须作为独立、显式、受审计能力设计。

#### Scenario: 校验钉钉 Connector
- **WHEN** 管理员点击配置校验
- **THEN** 系统验证配置完整性和安全策略并返回脱敏结果，不向钉钉发送消息
