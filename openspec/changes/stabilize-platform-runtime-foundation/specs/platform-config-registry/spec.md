## MODIFIED Requirements

### Requirement: Resource bindings are persisted by scope
系统 SHALL 在 PostgreSQL 中持久化稳定 Resource Identity、DB/Redis/Loki Resource Draft、不可变 Revision 以及按环境、基地、车间和业务应用发布绑定的具体 Revision。ER context 与 business-flow context 不在本次资源清空范围。

#### Scenario: Bind database revision to base
- **WHEN** 授权发布者为基地绑定已发布数据库 revision
- **THEN** 系统保存资源类型、作用域、revision ID、Secret reference 和状态，不复制明文连接密钥

#### Scenario: Bind Loki revision to workshop
- **WHEN** 业务应用发布为车间选择一个 Loki revision
- **THEN** registry 保存具体 revision 及车间查询约束，运行时不得浮动到后续 revision

### Requirement: Secret references never store secret payloads
系统 SHALL 在新建资源、Revision 和 binding 中只保存 `secret://platform/<code>`，MUST NOT 在 PostgreSQL 普通配置表中保存真实 token、password、API key、Redis 密码或数据库密码。旧 `env:` 只可作为显式导入输入。

#### Scenario: Store platform secret reference
- **WHEN** 管理端为数据库 Draft 选择凭据中心 Secret
- **THEN** 系统只保存 `password_ref=secret://platform/<code>` 和用途

#### Scenario: Reject raw secret in config json
- **WHEN** 管理端提交的资源配置 JSON 中包含疑似真实密钥字段和值
- **THEN** 系统拒绝保存并返回校验错误

#### Scenario: Reject new env provider binding
- **WHEN** 新建或发布的资源包含 `env:`、`vault:` 或 `kms:` 引用
- **THEN** registry 必须拒绝；旧 env 数据只能进入显式导入流程

### Requirement: Registry exposes stable runtime revision
系统 SHALL 为已发布 topology、Resource Revision、应用 binding 和相关 Secret active version 生成稳定 runtime revision/generation；仅修改 Draft 不得改变 effective generation。

#### Scenario: Published configuration changes revision
- **WHEN** 新 Resource Revision 发布、应用重新绑定或相关 Secret active version 变化
- **THEN** registry 的 published revision/generation 必须变化并触发运行时装载

#### Scenario: Draft changes
- **WHEN** 管理员只修改未发布 Draft
- **THEN** published/effective generation 必须保持不变

#### Scenario: Runtime reports revision
- **WHEN** Internal API Platform 装载数据库快照
- **THEN** 运行时状态同时包含 observed published generation 和 effective generation

## ADDED Requirements

### Requirement: Provider 字段契约必须与运行时实现一致
Registry MUST 以单一 schema 定义管理 API、前端表单、验证器和运行时适配器字段；数据库第一阶段只允许 MySQL、SQL Server、Oracle，Redis 和 Loki 使用各自统一字段。

#### Scenario: 数据库字段名称不一致
- **WHEN** 请求同时使用旧 `user` 和新 `username` 或其他歧义字段
- **THEN** 系统必须按导入规则显式转换或拒绝，不得让管理端保存后运行时无法读取

#### Scenario: Provider 没有运行时 Handler
- **WHEN** Provider 被元数据声明但当前代码没有对应运行时实现
- **THEN** Registry 必须将其标记 unavailable 并阻止发布

## REMOVED Requirements

### Requirement: Platform access grants are persisted
**Reason**: 全局授权改为业务应用严格角色与 Job 固化 Execution Scope，旧 `platform_access_grant` 被备份后清理。

**Migration**: 在维护窗口验证新 RBAC 和双人管理员不变量；不迁移旧 grant，缺少新授权的访问将被拒绝。

### Requirement: Registry projects access grants into runtime access policy
**Reason**: Internal API Platform 改为从 Job 的严格应用角色授权事实和不可变 Execution Scope 计算访问，不再投影旧 grant。

**Migration**: 删除旧投影路径，运行时只接受业务应用发布、角色和 scope binding。
