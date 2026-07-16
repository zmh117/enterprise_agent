## ADDED Requirements

### Requirement: 用户可以通过角色继承权限
系统 SHALL 持久化角色和用户角色关系，并 MUST 只展开 enabled 用户、enabled 角色和 enabled membership。

#### Scenario: 用户通过角色获得工具权限
- **WHEN** 启用用户属于拥有某只读工具 allow policy 的启用角色
- **THEN** 权限求值器允许该用户在其它安全条件满足时使用该工具

#### Scenario: 角色被禁用
- **WHEN** 管理员禁用一个角色
- **THEN** 该角色授予的权限不再用于新的请求，用户其它直接或角色权限保持独立

### Requirement: 权限求值统一处理用户角色和 deny
系统 SHALL 在一个统一 evaluator 中计算用户直接 policy、角色 policy、平台 access grant、资源通配符、作用域和 effect，并 MUST 让命中的显式 deny 阻止对应 allow。

#### Scenario: 角色宽泛允许但用户被明确拒绝
- **WHEN** 用户通过角色获得 `tool:*` allow，同时用户主体命中目标工具 deny
- **THEN** 系统拒绝该工具并返回安全权限原因

#### Scenario: 用户有工具权限但无数据范围
- **WHEN** 用户被允许调用数据库工具，但没有目标基地或车间 platform access grant
- **THEN** 系统拒绝工具调用且不访问目标数据源

### Requirement: 管理动作使用明确资源和 action 权限
系统 SHALL 对用户、角色、身份绑定、Agent 编辑、Agent 发布、平台配置、密钥和审计查看定义独立管理 action，并 MUST 在每个写 API 执行前授权。

#### Scenario: 用户管理员不能发布 Agent
- **WHEN** 操作者具有 `user:manage` 但不具有 `agent:publish`
- **THEN** 系统允许管理用户但拒绝发布 Agent

#### Scenario: Agent 编辑者提交草稿
- **WHEN** 操作者具有目标 Agent 的 `agent:edit`
- **THEN** 系统允许更新草稿，但发布仍要求 `agent:publish`

### Requirement: 工具授权与 Agent 分配共同生效
系统 SHALL 将用户/角色工具权限与 Agent publication 的工具分配分开管理；工具只有在两者都允许且工具本身 enabled/read-only 时才可暴露给 runtime。

#### Scenario: 用户有权限但 Agent 未分配
- **WHEN** 用户拥有 `query_loki` 权限，但当前 Agent publication 未分配该工具
- **THEN** runtime 不向模型暴露 `query_loki`

#### Scenario: Agent 已分配但用户无权限
- **WHEN** 当前 Agent publication 分配 `query_database`，但用户和角色均无该工具权限
- **THEN** runtime 不向模型暴露或执行该工具

### Requirement: 权限决策提供安全 trace 和审计
系统 SHALL 为 allow/deny 决策生成包含内部用户、角色摘要、资源、action、作用域、命中 policy/grant ID 和最终结果的安全 trace，并 MUST 不包含密码、session token、secret 或原始敏感数据。

#### Scenario: 权限被拒绝
- **WHEN** Web、钉钉、Agent 或工具请求被 RBAC 拒绝
- **THEN** 系统记录可排障的安全决策 trace，并向调用方返回不泄漏内部策略细节的错误
