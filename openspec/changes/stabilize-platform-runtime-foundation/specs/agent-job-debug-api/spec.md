## MODIFIED Requirements

### Requirement: 调试 API 必须能创建 Agent Job
系统 SHALL 提供受登录态保护的调试 Job 创建 API，用于在不依赖外部 Channel 的情况下创建只读诊断 Job，并复用业务应用发布、严格 RBAC、审计、持久化和 Outbox 链路。API MUST 使用当前登录用户，且只接受该用户有权使用的已发布业务应用、Execution Scope、消息和幂等键。

#### Scenario: 当前用户提交调试问题
- **WHEN** 已登录用户具备 `agent.debug.execute`，并选择有权访问的业务应用发布和 Execution Scope
- **THEN** 系统以当前用户身份创建隔离 Session、Agent Job、用户消息、授权快照、审计和 Job Dispatch Outbox，并返回 `job_id`

#### Scenario: 请求试图覆盖运行身份或资源
- **WHEN** 调试请求提交任意 `user_id`、Agent ID、Resource Revision、Connector 或自定义 reply route
- **THEN** 系统必须拒绝这些越权字段，且不得创建 Job 或 Outbox event

#### Scenario: 调试 API 使用幂等键
- **WHEN** 同一用户在同一发布版本和 Execution Scope 下两次提交相同 `idempotency_key`
- **THEN** 系统返回同一个 `job_id`，且不重复创建 Job 或 Outbox event

### Requirement: 调试 API 必须执行权限校验
系统 SHALL 在创建调试 Job 前校验登录态、`agent.debug.execute`、业务应用角色、应用发布可用性和 Execution Scope；任一授权缺失都必须 fail closed。

#### Scenario: 授权用户创建任务
- **WHEN** 当前用户拥有调试权限、目标应用角色和目标 Execution Scope
- **THEN** 系统创建并通过 Outbox 调度 Agent Job

#### Scenario: 未授权用户被拒绝
- **WHEN** 当前用户缺少任一所需权限或范围
- **THEN** 系统返回安全拒绝，且不创建 Session、Job、消息或 Outbox event

## ADDED Requirements

### Requirement: 调试查询必须受当前用户授权
Job、Step 和 Tool Call 查询 MUST 要求登录，并仅允许 Job 创建人、具备该业务应用运维权限的用户或平台管理员访问；响应必须继续脱敏。

#### Scenario: 用户查询其他应用的调试 Job
- **WHEN** 当前用户不是创建人且没有目标应用运维权限
- **THEN** 系统必须拒绝查询，并且不得泄露 Job 是否存在的敏感细节

### Requirement: 运行中心必须提供受限调试入口
前端 SHALL 提供“运行中心 → 发起调试”，只列出当前用户可用的已发布业务应用与 Execution Scope；默认 Delivery 为 none，可选 Delivery 必须来自现有已授权 binding。

#### Scenario: 用户成功发起调试
- **WHEN** 用户选择允许的应用、范围并提交消息
- **THEN** 页面创建 Job 后导航到受保护的 Job 详情页

#### Scenario: 用户选择可选投递
- **WHEN** 用户选择当前应用发布已有的授权 Delivery binding
- **THEN** 系统固化该 binding；页面不得允许填写任意 Connector 或目标地址
