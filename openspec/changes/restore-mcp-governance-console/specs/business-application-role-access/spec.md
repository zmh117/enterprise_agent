## MODIFIED Requirements

### Requirement: 业务应用是用户运行授权的入口对象
系统 SHALL 允许角色对具体 Application 授予 `invoke` 或等价使用权限。Application 路由下命中的授权 MUST 封装该 Application 固定的项目和 Agent 入口许可，普通管理员不得再为同一路径手工组合项目、Agent、MCP Tool 或 Resource 使用策略。

#### Scenario: 用户通过角色获得 Application 访问
- **WHEN** 已绑定且启用的用户通过有效角色获得当前激活 Application 的使用权限
- **THEN** 系统继续检查数据范围和当前 Publication 运行上限，不要求额外配置底层项目、Agent 或 Tool 策略

#### Scenario: 用户未获得 Application 访问
- **WHEN** 已绑定用户没有任何有效角色允许当前 Application
- **THEN** 系统在创建 Agent Job 前拒绝请求并返回“当前用户无权使用该 Application”

### Requirement: 多角色业务访问按应用合并
系统 SHALL 按当前 Application 合并用户全部有效角色的允许状态和明确数据范围，并 MUST 让高级拒绝优先。系统 MUST 保留每项有效访问的角色来源用于预览和审计，且 MUST NOT 通过合并角色构造 MCP Tool 集合。

#### Scenario: 多角色合并同一 Application 范围
- **WHEN** 一个角色允许一号基地，另一个角色允许二号基地，且二者都允许同一 Application
- **THEN** 用户在两个明确数据范围内使用该 Application，实际 Tool 集合仍来自当前激活 Publication

### Requirement: 服务账号仅通过业务授权参与非交互式入口
系统 SHALL 允许服务账号通过业务角色获得 Webhook 等非交互式 Application 使用权限和明确数据范围，但 MUST NOT 因该角色获得管理后台登录、MCP Tool 编辑或 Credential 权限。

#### Scenario: Webhook 服务账号有业务角色
- **WHEN** Webhook 触发器的启用服务账号获得目标 Application 和数据范围授权
- **THEN** 系统按该服务账号的角色执行 Application 授权，并与当前 Publication 的 MCP 安全上限求交

## REMOVED Requirements

### Requirement: 每个业务应用独立配置能力和数据范围
**Reason**: 角色不再保存 API Capability 或逐 Tool 允许集合，只保存 Application 使用权限和数据范围。

**Migration**: 保留每个 Application 的明确数据范围；删除旧 Capability 授权数据，不迁移为 MCP Tool 权限。

### Requirement: 业务能力选择受多层安全上限约束
**Reason**: MCP Tool 集合由已激活 Application/Agent Publication 固定，角色页面不能再次选择 Tool。

**Migration**: 旧 Capability 选择直接删除；运行时使用 Application 访问、数据范围和当前 Publication 三者交集。

### Requirement: 旧原始策略仅作为受控兼容和高级例外
**Reason**: 本变更建立当前统一角色/Application 权限事实，不继续读取已退役 Capability 或旧平台原始允许策略。

**Migration**: 保留受控高级显式拒绝；旧允许策略不迁移，管理员必须使用角色显式授予 Application 和数据范围。

## ADDED Requirements

### Requirement: 每个 Application 独立配置使用权限和数据范围
系统 SHALL 让角色在每个 Application 授权项下独立选择 Application 使用权限和环境、基地、车间范围。同一角色绑定多个 Application 时，一个 Application 的数据范围 MUST NOT 自动用于另一个 Application。

#### Scenario: 同一角色的两个 Application 使用不同范围
- **WHEN** 角色为生产 Application 选择生产一号基地、为测试 Application 选择测试基地
- **THEN** 两个 Application 分别使用自己的范围进行授权，不发生跨 Application 继承

### Requirement: Application Publication 构成不可扩大的运行上限
系统 SHALL 将当前环境激活的 Application Publication、Agent Publication、MCP Tool Publication 和精确 Resource Deployment 作为运行上限，并 MUST 与用户 Application 权限和数据范围求交。角色变更不得修改或扩大该运行上限。

#### Scenario: Publication 移除 Tool
- **WHEN** 新激活 Publication 不再包含此前可用的 MCP Tool
- **THEN** 所有角色成员的新 Job 都不再获得该 Tool，角色记录无需重写

#### Scenario: 角色请求未发布 Tool
- **WHEN** 客户端试图通过角色授权请求写入未发布 Tool
- **THEN** 后端拒绝字段且不改变 Publication 或角色

### Requirement: 不兼容旧 Capability 授权
系统 MUST 拒绝新角色或运行授权请求中的 API Capability、Handler、Connection 和 Resource Mapping 字段，并 MUST 不通过隐藏兼容读取恢复旧允许效果。

#### Scenario: 客户端提交旧 Capability ID
- **WHEN** 客户端在 Application 角色授权中提交旧 Capability ID
- **THEN** 系统返回稳定的已退役错误且不创建授权

