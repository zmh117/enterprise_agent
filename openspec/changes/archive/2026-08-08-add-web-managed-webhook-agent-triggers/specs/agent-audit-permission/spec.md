## ADDED Requirements

### Requirement: Webhook 服务账号必须完成统一授权链
系统 SHALL 在 Webhook event 接收/分发和每次工具调用时，以 Trigger 服务账号执行 Connector ingress、Agent use、project、tool 和平台数据范围授权，MUST 采用显式 deny 优先。

#### Scenario: 服务账号权限完整
- **WHEN** 服务账号、角色和 grant 共同允许固定 Agent、项目、工具和目标数据范围
- **THEN** 系统允许创建 job并在决策 trace 中记录匹配策略和 grant

#### Scenario: 服务账号没有 Agent use 权限
- **WHEN** Trigger publication 有效但服务账号未被允许使用对应 Agent
- **THEN** dispatcher 拒绝创建 job、将 event 标记为安全失败并记录 deny trace

#### Scenario: 工具调用超出数据范围
- **WHEN** Webhook Agent 试图使用允许的工具访问服务账号未授权的基地或车间
- **THEN** 工具层拒绝调用并记录范围拒绝，Agent 不得绕过该决定

### Requirement: Webhook 配置和运行审计不得泄漏凭证或原始报文
系统 SHALL 审计 Trigger 创建、修改、发布、回滚、public ID 轮换、服务账号授权、事件认证/过滤/分发和 Delivery 结果，MUST 只保存安全摘要。

#### Scenario: HMAC 认证失败
- **WHEN** 请求签名不匹配
- **THEN** 审计记录 Trigger、错误码、payload hash、请求大小和 correlation ID，不记录 secret、签名原文或 body

#### Scenario: 管理员修改 Trigger
- **WHEN** 管理员保存或发布 revision
- **THEN** 审计记录 actor、Trigger、before/after config hash、revision 和结果，不记录 secret value
