## MODIFIED Requirements

### Requirement: Platform enforces environment/base/workshop access scope
The system SHALL enforce the immutable Execution Scope and strict business-application role captured on the Job, independently of the Agent-side tool permission check. Legacy `platform_access_grant` MUST NOT participate in runtime authorization.

#### Scenario: In-scope request allowed
- **WHEN** a RUNNING Job is authorized for `sanjiu`/`guanlan`/`GL001` and requests the bound tool resource for that target
- **THEN** the platform allows resolution and execution

#### Scenario: Out-of-scope base rejected
- **WHEN** a Job scoped only to `sanjiu` requests a resource in `mmk`
- **THEN** the platform rejects the request with a non-retryable authorization error

#### Scenario: Out-of-scope workshop rejected
- **WHEN** a Job scoped to workshop `GL001` requests `GL002`
- **THEN** the platform rejects the request as unauthorized

#### Scenario: Legacy grant exists
- **WHEN** a caller would have been allowed only by a legacy `platform_access_grant`
- **THEN** the platform denies access because no strict application-role authorization exists

### Requirement: Platform validates caller identity from request context
The system MUST authenticate the calling service with a required Bearer Token and MUST resolve caller, application, Handler and scope facts from the persisted `X-Agent-Job-Id`. User and scope headers are consistency hints only and cannot grant access.

#### Scenario: Missing service Token rejected
- **WHEN** a tool request arrives without a valid Internal API service Token
- **THEN** the platform rejects the request before reading or executing the target resource

#### Scenario: Unknown or non-running Job rejected
- **WHEN** the Token is valid but the supplied Job does not exist or is not in an allowed execution state
- **THEN** the platform rejects the request and records the rejection

#### Scenario: Header identity conflicts with Job
- **WHEN** a user, application or scope Header conflicts with the persisted Job facts
- **THEN** the platform rejects the request and MUST NOT trust the Header value

## ADDED Requirements

### Requirement: 平台必须全局使用严格应用角色授权
系统 MUST 删除 `compatibility` 配置、执行分支和 fallback；缺少新 RBAC 数据时必须拒绝，不得自动迁移 `permission_policy` 或 `platform_access_grant` 的授权含义。

#### Scenario: 旧策略允许但新角色未授权
- **WHEN** 用户只有旧 permission policy 而没有业务应用角色
- **THEN** 系统必须拒绝创建或执行 Job

### Requirement: 平台必须保持双人管理员不变量
系统 MUST 始终保留至少两个已登录验证、启用且为人类身份的 `platform-admin` 成员；系统账号不计数。

#### Scenario: 禁用操作会只剩一名管理员
- **WHEN** 禁用用户或移除角色会使有效人类平台管理员少于两人
- **THEN** 系统必须在同一事务中拒绝操作
