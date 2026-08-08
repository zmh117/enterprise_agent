## ADDED Requirements

### Requirement: Platform configuration writes require authenticated internal actor
系统 SHALL 要求平台配置新增、修改、启停、密钥轮换、导入和发布 API 使用管理端认证 middleware 提供的内部用户 actor，并 MUST 在生产模式拒绝仅靠客户端身份请求头的调用。

#### Scenario: 已认证管理员修改平台配置
- **WHEN** 有有效管理 session 且具备 `platform_config:manage` 权限的内部用户更新资源绑定
- **THEN** 系统执行现有领域校验、保存修改并以内部用户 ID 记录配置审计

#### Scenario: 未认证请求伪造管理员头
- **WHEN** 请求没有有效 session 但提交 `x-admin-user-id`
- **THEN** 生产 API 拒绝请求且不写入平台配置

### Requirement: Platform configuration reads respect management permissions
系统 SHALL 对包含用户授权、密钥状态、runtime config 和管理审计的敏感管理读取执行对应 action permission，并 MUST 继续屏蔽 secret 值。

#### Scenario: 普通 Agent 用户读取密钥状态
- **WHEN** 已认证用户没有 secret 管理或查看权限
- **THEN** 系统拒绝该管理读取，而不是仅因为用户能使用 Agent 就返回密钥元数据
