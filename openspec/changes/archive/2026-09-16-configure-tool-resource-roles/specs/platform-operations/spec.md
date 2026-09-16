## MODIFIED Requirements

### Requirement: Registry exposes stable runtime revision
系统 SHALL 为 Environment/Base/Workshop topology、Resource Identity 和 Resource Revision 暴露规范化 revision 或 content hash，用于审计管理变更和证明每次 Tool Call 的实际资源事实。新 Resource Revision 的 content hash MUST 同时覆盖 Provider 连接配置、Secret references、数据范围 bindings 和资源角色 placement；系统 MUST NOT 生成 Application Resource Mapping、独立范围 Policy Revision、activation generation 或 Job-frozen Resource Revision。历史角色事实须从旧身份配置保留，不根据资源名称猜测，且不得重写旧发布哈希。

#### Scenario: Configuration changes revision
- **WHEN** Environment/Base/Workshop 或 Resource 发布新的不可变 revision
- **THEN** 对应 revision/hash 发生变化，既有 Published Revision 内容保持不变

#### Scenario: Tool Call reports revision
- **WHEN** `tool-mcp` 为一次调用解析唯一 Published Resource Revision
- **THEN** Tool Call 与 MCP Operation Audit 包含 Tool identifier/schema hash、Resource ID/revision/content hash 和实际 placement 的安全摘要

#### Scenario: Resource draft changes only
- **WHEN** 管理员修改尚未发布的 Resource Draft
- **THEN** 既有 Published Revision 与当前 Tool Call 解析结果不发生变化

#### Scenario: Resource scope binding changes
- **WHEN** 管理员修改 Draft 中的 DB table prefix、Redis namespace 或 Loki selector conditions
- **THEN** 同一个 Draft revision 和 content hash 变化，旧技术验证失效且 Published Revision 保持不变

#### Scenario: 已有资源修改角色
- **WHEN** 管理员从现有发布版本新建草稿并修改资源角色
- **THEN** 系统保存角色到该草稿并使旧验证失效，重新验证发布后才以新角色解析；其他资源与旧发布不变

#### Scenario: 升级前草稿验证不覆盖角色
- **WHEN** 升级前草稿哈希尚未纳入角色
- **THEN** 系统要求先保存草稿并重新技术验证，不复用旧验证发布

## ADDED Requirements

### Requirement: 管理端资源角色可创建并复用
数据库和 Redis 资源新建及编辑页面 SHALL 提供“资源角色”输入选择，初始为空，不预置角色；用户可保存新值并选择历史保存值，历史候选来自资源元数据，不读取连接凭据。角色 SHALL 与 RBAC 用户角色区分；Loki 不显示该输入且服务端拒绝非空值。

#### Scenario: 保存和复用新角色
- **WHEN** 管理员输入合法新角色并保存资源草稿
- **THEN** 后续新建或编辑可从历史值中选择该角色，同时仍可不填或新建其他角色

#### Scenario: 清空角色
- **WHEN** 管理员清空草稿角色并保存
- **THEN** 系统保存未指定状态；若发布后产生同目标多候选，仍按歧义规则拒绝，不隐式选择数据库
