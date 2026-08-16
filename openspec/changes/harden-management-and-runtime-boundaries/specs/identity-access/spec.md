## ADDED Requirements

### Requirement: 管理面必须形成统一认证授权响应矩阵
系统 SHALL 对所有管理 Router、平台配置、Agent Workflow 和调试 Job 入口使用同一管理面装配与可信 principal 边界。管理面关闭时端点 MUST 不注册；管理面开启时未认证、无 action 权限和已授权请求 MUST 分别得到 401、403 和成功响应。

#### Scenario: 管理面关闭
- **WHEN** `FEATURE_WEB_ADMIN=false` 且客户端请求任一管理 API、Workflow 或调试 Job 入口
- **THEN** 系统返回 404，且不得读取管理数据或执行写操作

#### Scenario: 管理面开启但未登录
- **WHEN** `FEATURE_WEB_ADMIN=true` 且请求没有有效 Session principal
- **THEN** 系统返回 401，不得把客户端 Header 解释为 actor

#### Scenario: 已登录但没有 action 权限
- **WHEN** 有效内部 principal 请求未获授权的管理 read、edit、publish 或 manage 操作
- **THEN** 系统返回 403 且记录安全权限拒绝

#### Scenario: 已登录且具有 action 权限
- **WHEN** 有效内部 principal 具有目标资源和 action 权限并满足写请求 CSRF
- **THEN** 系统执行操作并以该 principal 的内部用户 ID 记录 actor

### Requirement: 测试 actor Header 必须由显式测试适配器控制
系统 MUST NOT 在生产管理路径信任 `x-admin-user-id`、`x-agent-user-id` 或等价客户端 actor Header。Header 身份注入只可在 local/test/testing 环境且显式启用测试身份功能时由认证 adapter 解析，并仍须执行相同 action 授权。

#### Scenario: 生产请求伪造 actor Header
- **WHEN** 非测试环境的未认证请求仅提交已存在管理员的 actor Header
- **THEN** 系统返回 401，且不执行或审计为该管理员

#### Scenario: 显式测试适配器注入身份
- **WHEN** test 环境显式启用测试身份 Header 并提交启用用户标识
- **THEN** 系统构造 `auth_source=test-header` principal 并继续执行正常 action 判定
