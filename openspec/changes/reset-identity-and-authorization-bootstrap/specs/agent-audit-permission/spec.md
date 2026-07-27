## MODIFIED Requirements

### Requirement: Users must be authorized before Agent job creation
系统 SHALL 在任何 Channel 消息或非交互式入口创建 Agent Job 前校验请求者身份状态、外部身份绑定、服务账号状态、Connector ingress 授权和目标业务应用使用权限。业务应用路由下的授权 SHALL 以有效角色中的业务应用访问为唯一用户可见入口，并 MUST 继续强制应用激活状态、固定 Agent Publication、安全执行策略和服务账号边界。身份与授权重置成功后，旧用户、旧角色、直接用户策略、旧项目或 Agent allowlist MUST NOT 再作为兼容授权来源。

#### Scenario: Authorized user submits request
- **WHEN** 已验证且启用的 Channel 请求者通过有效角色获得命中业务应用的使用权限，且 source Connector 允许 ingress
- **THEN** 系统继续检查业务能力和数据范围、创建 Agent Job，并记录业务应用、角色来源和授权决定

#### Scenario: Unauthorized user submits request
- **WHEN** 已验证请求者没有目标业务应用使用权限或命中高级拒绝
- **THEN** 系统拒绝请求、记录权限拒绝，不发布 Agent Job，并返回中文安全提示

#### Scenario: Connector is not authorized for ingress
- **WHEN** 请求使用已停用或不允许 ingress 的 Connector
- **THEN** 系统拒绝请求、记录 Connector 授权失败，并且不发布 Agent Job

#### Scenario: Reset identity attempts to use legacy grants
- **WHEN** 重置后出现仅匹配旧用户、旧角色、旧项目或 Agent allowlist 的请求
- **THEN** 系统拒绝请求、记录严格模式拒绝和安全主体摘要，且不得创建 Agent Job 或回退到兼容授权

#### Scenario: Replacement service account has not been authorized
- **WHEN** 被重置流程创建的停用服务账号或未分配业务角色的服务账号触发 Webhook
- **THEN** 系统在 Job 创建前拒绝请求并记录服务账号未启用或未授权，不使用平台管理员代替执行
