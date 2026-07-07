## ADDED Requirements

### Requirement: Registry exposes stable runtime revision
系统 SHALL 为平台配置 registry 暴露稳定 revision 或 hash，用于判断 runtime snapshot 是否来自预期配置版本。

#### Scenario: Configuration changes revision
- **WHEN** environment、base、workshop、resource binding、secret reference 或 access grant 发生新增、修改、启停
- **THEN** registry 生成的 topology revision 或 hash MUST 发生变化

#### Scenario: Runtime reports revision
- **WHEN** Internal API Platform 从 registry 加载 DB-backed snapshot
- **THEN** 运行时状态输出包含该 revision 或 hash，便于与配置 API snapshot 对比

### Requirement: Registry projects access grants into runtime access policy
系统 SHALL 将 PostgreSQL 中启用的 platform access grants 投影成 Internal API Platform 运行时访问策略。

#### Scenario: User grant allows target
- **WHEN** 用户拥有目标 environment/base/workshop 的启用 allow grant
- **THEN** DB-backed runtime access policy 允许该用户解析并调用该目标下的只读工具

#### Scenario: Disabled or deny grant blocks target
- **WHEN** grant 被禁用或更高优先级 deny grant 命中目标
- **THEN** DB-backed runtime access policy 拒绝该用户访问目标，并记录授权拒绝

### Requirement: Registry keeps secret references unresolved outside infrastructure
系统 SHALL 在 registry、public snapshot、配置审计和运行时状态中只保留 secret reference，不得保存或返回解析后的真实密钥值。

#### Scenario: Secret reference is loaded for runtime
- **WHEN** DB-backed resource binding 使用 secret reference 配置数据库、Redis 或 Loki credential
- **THEN** registry snapshot 只包含引用，真实值仅能在 infrastructure gateway 建立外部连接时解析

#### Scenario: Public snapshot is exported
- **WHEN** 管理端或调试工具导出 topology snapshot
- **THEN** 响应不得包含任何真实 password、token、api key 或解析后的 secret payload
