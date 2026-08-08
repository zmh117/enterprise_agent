## Purpose

Define platform-side authorization for internal tool requests so Agent permissions and platform topology access remain independently auditable.
## Requirements
### Requirement: Platform enforces environment/base/workshop access scope
The system SHALL enforce platform-side access scope against the actual Business Target Path: Environment, optional Base and optional Workshop. Authorization SHALL be independent of the Agent-side stable Tool Identifier permission, and Resource Placement (`cloud`/`edge`) MUST NOT be a user, group or role authorization dimension.

#### Scenario: In-scope request allowed
- **WHEN** a user authorized for `sanjiu/guanlan/GL001` issues a tool request for that exact target
- **THEN** the platform allows the request to proceed to exact publication, resource and policy resolution

#### Scenario: Environment leaf access
- **WHEN** an Environment has no Base or Workshop and the user is authorized for that Environment leaf
- **THEN** the platform evaluates the real Environment target without requiring placeholder scope grants

#### Scenario: Out-of-scope base rejected
- **WHEN** a user authorized only for one Environment issues a request targeting another Environment or an unauthorized Base
- **THEN** the platform rejects the request with a non-retryable authorization error

#### Scenario: Out-of-scope workshop rejected
- **WHEN** a user authorized for Workshop `GL001` issues a request targeting `GL002`
- **THEN** the platform rejects the request as unauthorized

#### Scenario: Placement differs within an authorized target
- **WHEN** a user authorized for GL001 invokes a tool whose Job Snapshot contains both cloud and edge resources for GL001
- **THEN** target authorization remains GL001; deterministic placement resolution may choose an allowed resource but cannot expand the target scope

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

### Requirement: Access decisions are audited without leaking secrets
The system SHALL audit access-control decisions (allow/deny) with the resolved target and caller, and SHALL NOT record credentials, connection details, or unbounded raw payloads.

#### Scenario: Denied access is audited
- **WHEN** the platform denies a request for being out of scope
- **THEN** it records an audit entry containing the caller, the requested environment/base/workshop, and the deny reason, without any secret material

### Requirement: 管理后台必须由统一身份与 RBAC 原子保护
系统 SHALL 将管理 Web、管理 API、统一身份、Web Session、RBAC 和业务应用控制面视为同一个管理面启停单元。管理面开启时 MUST 要求可解析的统一用户身份和授权；系统不得支持无身份或无 RBAC 的管理后台组合。

#### Scenario: 管理面开启
- **WHEN** `FEATURE_WEB_ADMIN=true`
- **THEN** 管理 Web 和管理 API 启用统一身份、Web Session 与 RBAC 校验
- **AND** 未认证调用方不能访问受保护管理资源

#### Scenario: 管理面关闭
- **WHEN** `FEATURE_WEB_ADMIN=false`
- **THEN** 系统不暴露管理 Web 和管理 API
- **AND** Channel ingress 与已发布 Agent Runtime 不因管理面关闭而自动停止

#### Scenario: 旧身份开关与管理面冲突
- **WHEN** `FEATURE_WEB_ADMIN=true` 但兼容期旧身份或业务应用控制面开关显式为 `false`
- **THEN** 系统拒绝启动并报告冲突配置
- **AND** 系统不得降级为无认证或不完整管理后台

### Requirement: 测试身份不得绕过生产访问控制
系统 MUST 在生产环境拒绝测试身份请求头适配器，无论该请求头由反向代理、客户端还是内部服务提供。

#### Scenario: 生产请求携带测试身份头
- **WHEN** 生产环境收到仅能由测试身份适配器识别的身份请求头
- **THEN** 系统不将其解析为已认证用户
- **AND** 系统按未认证请求拒绝并记录审计事件

### Requirement: 当前全部展开为明确范围
系统 SHALL 在保存授权时把“当前全部环境、基地或车间”展开为当时存在且操作者有权授予的明确资源 ID 集合，并 MUST NOT 提供包含未来新增资源的动态全部选项。

#### Scenario: 新基地在授权后创建
- **WHEN** 管理员保存当前全部基地后新增一个基地
- **THEN** 新基地不进入既有角色授权，除非管理员再次编辑并明确选择

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

### Requirement: Placement must not be persisted in access grants
新的用户、组和角色数据范围 Grant MUST NOT 保存 cloud、edge、standalone、role label 或 replica 作为授权条件；任何提交此类条件的管理请求 MUST 被拒绝。

#### Scenario: Admin grants edge-only workshop access
- **WHEN** 管理员尝试创建只允许 GL001 edge 资源的用户数据 Grant
- **THEN** 系统拒绝并要求按逻辑 GL001 目标授权

#### Scenario: Existing scope is evaluated for both placements
- **WHEN** 用户拥有 GL001 的允许 Grant 且 Application Publication 为 GL001 配置两个 placements
- **THEN** 授权检查对两者使用相同 GL001 scope，实际 placement 仍由 Tool Call 解析和审计

### Requirement: Stable tool-use permission and data scope must both pass
运行时 MUST 同时要求调用者拥有稳定 Built-in Tool Identifier 的 `tool:use` Grant 和目标 Business Target Path 的允许范围；任一通过都不得替代另一项，也不得因 Grant 稳定而绕过精确 Release/Application 校验。

#### Scenario: Tool grant exists but target denied
- **WHEN** 用户可以使用 `query_redis_get` 但没有目标 GL002 的数据范围
- **THEN** 平台拒绝调用且不访问 Redis

#### Scenario: Target allowed but tool grant missing
- **WHEN** 用户可访问 GL001 但没有目标稳定 Tool Identifier 的使用权限
- **THEN** 模型不获得该工具，直接调用也被拒绝
