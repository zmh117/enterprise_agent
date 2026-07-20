## ADDED Requirements

### Requirement: 管理后台使用统一 RBAC 和数据范围授权
系统 SHALL 对每个管理 API 执行服务端权限和数据范围校验，并向前端返回当前主体可用的 capability 摘要；前端 Capability Gate 仅用于交互裁剪，MUST NOT 替代后端授权。

#### Scenario: 前端隐藏无权操作
- **WHEN** 当前用户的 capability 摘要不包含资源编辑权限
- **THEN** 前端不展示编辑动作或将其明确禁用

#### Scenario: 绕过前端调用管理 API
- **WHEN** 无权限用户直接调用受保护的管理写接口
- **THEN** 后端拒绝请求、记录操作者和安全拒绝原因

### Requirement: 管理查询按内部用户和资源范围裁剪
系统 SHALL 以内部用户主体解析角色、权限策略、租户、项目、环境、基地和车间范围，并将相同授权规则用于 Web、钉钉入口和管理聚合查询。

#### Scenario: 钉钉绑定用户登录 Web
- **WHEN** 同一内部用户同时具有 Web 凭据和钉钉外部身份
- **THEN** 两个入口共享角色和资源访问授权

#### Scenario: 聚合查询范围受限
- **WHEN** 范围受限用户查询 Dashboard、会话或附件
- **THEN** 结果仅包含其授权范围且汇总值不会包含无权数据
