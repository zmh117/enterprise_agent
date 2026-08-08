## MODIFIED Requirements

### Requirement: Platform configuration API exposes topology management
系统 SHALL 提供 Web 配置平台使用的 REST API，用于管理环境、基地、车间、稳定 Resource Identity、Resource Draft、验证结果、不可变 Revision、应用发布绑定和 Secret reference。

#### Scenario: List topology
- **WHEN** 管理端请求平台 topology 列表
- **THEN** 系统返回启用和禁用的环境、基地、车间以及必要的分页或过滤信息

#### Scenario: Create resource draft
- **WHEN** 管理端为某作用域提交合法的 DB、Redis 或 Loki Draft
- **THEN** 系统保存 Draft、写入配置审计，并明确返回 DRAFT、published 与 effective 状态

#### Scenario: Bind resource revision
- **WHEN** 业务应用发布选择一个可用 Resource Revision
- **THEN** 系统保存具体 revision binding，而不是浮动 Resource Identity

### Requirement: YAML topology import upserts database configuration
系统 SHALL 将 YAML import 限定为 bootstrap 或显式迁移操作；导入结果只能创建或更新 PostgreSQL topology 与 Resource Draft，MUST NOT 自动发布或覆盖现有 Published Revision。

#### Scenario: Import new yaml topology
- **WHEN** 授权管理员导入包含新环境、基地、车间和资源配置的 YAML
- **THEN** 系统创建对应 topology 与 Draft，返回 created、updated、skipped 和 requires-secret-migration 统计

#### Scenario: Import existing yaml topology
- **WHEN** 相同稳定编码和内容被再次导入
- **THEN** 系统幂等处理，不创建重复对象或 Published Revision

#### Scenario: Import attempts to overwrite published resource
- **WHEN** YAML 内容与现有 Published Revision 不同
- **THEN** 系统创建新 Draft 并要求重新验证、发布，不得直接改变有效运行时

### Requirement: API exposes runtime topology snapshot
系统 SHALL 提供只读 snapshot API，展示 PostgreSQL 中当前 published/effective Resource Revision、应用 binding、runtime generation、Last Known Good 和安全错误摘要。

#### Scenario: Snapshot from database
- **WHEN** PostgreSQL 中存在已发布且成功装载的 topology 与资源
- **THEN** snapshot API 返回 source 为 database，并同时标明 published revision 与 effective revision

#### Scenario: Snapshot validation error
- **WHEN** Published Revision 缺少可解析 Secret 或运行时无法装载
- **THEN** snapshot API 返回 degraded/blocked 状态和脱敏错误，不得静默回退 YAML

### Requirement: Platform configuration API documents restart or reload semantics
系统 SHALL 文档化基于 revision 轮询、完整快照构建、原子切换和 Last Known Good 的热加载语义。

#### Scenario: 新 revision 成功激活
- **WHEN** Internal API Platform 检测到可装载的新 Published Revision
- **THEN** 新请求使用新 generation，进行中请求继续使用其已捕获的旧 generation

#### Scenario: 新 revision 激活失败
- **WHEN** 新快照构建失败
- **THEN** 文档和 API 明确显示 published 不等于 effective，并保留 Last Known Good

## ADDED Requirements

### Requirement: Resource API 必须实施技术发布门禁
Resource API MUST 在发布前校验字段 schema、`secret://platform/` 引用、连接、只读账号、Provider 可用性和当前 Draft digest；本次不要求审核审批。

#### Scenario: 单个授权发布者发布
- **WHEN** 用户具备发布权限且 Draft 为当前 VERIFIED 内容
- **THEN** 系统可以直接创建不可变 Published Revision 并审计

#### Scenario: Draft 在验证后被修改
- **WHEN** Draft digest 与最近验证结果不一致
- **THEN** 发布必须拒绝并要求重新验证

### Requirement: 破坏性资源重置不得暴露为普通 CRUD
全量资源重置 MUST 只通过受控维护 CLI 的 report/prepare/apply/verify 执行，普通 Web/API 删除不得物理删除 Published Revision。

#### Scenario: 管理员从页面删除已发布资源
- **WHEN** 管理员对 Published Resource 使用普通删除操作
- **THEN** API 必须拒绝，并提供 disable/archive 语义
