## MODIFIED Requirements

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

## ADDED Requirements

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
