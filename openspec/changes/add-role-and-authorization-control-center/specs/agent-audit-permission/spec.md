## MODIFIED Requirements

### Requirement: Users must be authorized before Agent job creation
系统 SHALL 在任何 Channel 消息创建 Agent job 前校验请求者身份状态、外部身份绑定、connector ingress 授权和目标业务应用使用权限。业务应用路由下的授权 SHALL 以业务应用访问为用户可见入口，并 MUST 继续强制应用激活状态、固定 Agent publication、安全执行策略和服务账号边界；兼容模式下的旧项目或 Agent 策略必须被标记为兼容来源。

#### Scenario: Authorized user submits request
- **WHEN** 已验证且启用的 Channel 请求者通过有效角色获得命中业务应用的使用权限，且 source connector 允许 ingress
- **THEN** 系统继续检查业务能力和数据范围、创建 Agent job，并记录业务应用、角色来源和授权决定

#### Scenario: Unauthorized user submits request
- **WHEN** 已验证请求者没有目标业务应用使用权限或命中高级拒绝
- **THEN** 系统拒绝请求、记录权限拒绝，不发布 Agent job，并返回中文安全提示

#### Scenario: Connector is not authorized for ingress
- **WHEN** 请求使用已停用或不允许 ingress 的 connector
- **THEN** 系统拒绝请求、记录 connector 授权失败，并且不发布 Agent job

## ADDED Requirements

### Requirement: 授权决策记录业务应用和来源摘要
系统 SHALL 为 job 创建、Worker 执行前、每次业务能力调用和结果投递前的授权决策生成安全 trace，至少包含内部用户或服务账号、目标业务应用、能力、明确数据范围、来源角色 ID、兼容策略标记、最终结果和拒绝阶段。trace MUST NOT 包含密码、Token、Secret、模型 API Key 或原始敏感策略条件。

#### Scenario: Worker 因角色到期拒绝
- **WHEN** Worker 执行前发现创建任务时有效的角色成员关系已经到期
- **THEN** 系统记录执行前授权拒绝、角色来源摘要和 job 关联，不记录消息正文或敏感数据

### Requirement: 角色授权配置变更被审计
系统 SHALL 记录角色基本信息、成员、管理后台能力、业务应用、只读能力、数据范围、角色分配委派和高级例外的变更前后安全摘要。高风险变更 MUST 同时记录管理员填写的变更原因。

#### Scenario: 扩大生产数据范围
- **WHEN** 管理员为角色增加生产基地范围
- **THEN** 系统记录操作者、角色、业务应用、增加的明确范围、受影响成员数和变更原因

#### Scenario: 延长成员有效期
- **WHEN** 管理员延长角色成员有效期
- **THEN** 系统通过普通成员更新审计记录原时间、新时间和操作者，不要求独立审批记录

