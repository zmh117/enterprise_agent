# platform-config-api Specification

## Purpose
Defines backend APIs for the future web configuration console, including topology management, YAML import, snapshot export, validation, and secret-safe responses.
## Requirements
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

### Requirement: Platform configuration API validates domain invariants
系统 SHALL 在保存配置前校验领域约束，包括编码唯一性、父子关系存在、资源类型合法、secret ref 合法、只读工具边界和配置 JSON schema。

#### Scenario: Duplicate environment code rejected
- **WHEN** 管理端创建已存在编码的环境
- **THEN** 系统拒绝请求并返回冲突错误

#### Scenario: Invalid workshop parent rejected
- **WHEN** 管理端创建车间但指定不存在的基地
- **THEN** 系统拒绝请求并返回校验错误

#### Scenario: Mutation tool binding rejected
- **WHEN** 管理端试图为 MVP 诊断流程启用写库、删 Redis 或重启服务类工具
- **THEN** 系统拒绝保存配置，因为第一版只允许只读诊断工具

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

### Requirement: API responses do not leak secret values
系统 SHALL 确保所有平台配置 API 响应只返回 secret reference 元数据，MUST NOT 返回任何解析后的真实密钥值。

#### Scenario: Get resource binding with credential
- **WHEN** 管理端查询带数据库密码引用的资源绑定
- **THEN** 系统只返回 `secret_ref` 编码或引用，不返回真实密码

#### Scenario: Export topology snapshot
- **WHEN** 系统导出 topology snapshot
- **THEN** snapshot 中的 credential 字段仍然是 secret reference，不包含明文 token 或 password

### Requirement: Imported topology can be verified as runtime-ready
系统 SHALL 让通过 YAML import 或平台配置 API 写入的 topology 能被验证为 Internal API Platform 可消费的 runtime snapshot。

#### Scenario: YAML import produces database snapshot
- **WHEN** 管理端导入合法 topology YAML 到 PostgreSQL
- **THEN** `/api/platform/topology-snapshot` 返回 source 为 database 或可被运行时加载的 DB-backed snapshot，并包含启用资源数量和访问授权摘要

#### Scenario: Imported topology has validation errors
- **WHEN** 导入后的启用资源绑定缺少运行时必须字段
- **THEN** snapshot API 返回配置错误详情，并且不得把该配置标记为 runtime valid

### Requirement: Platform configuration API supports runtime verification workflow
系统 SHALL 提供足够的只读 API 输出，让开发者或后续 Web 平台确认当前 DB 配置能驱动只读诊断工具。

#### Scenario: Verify effective topology
- **WHEN** 开发者查询平台 topology snapshot
- **THEN** 响应包含启用 environment/base/workshop、resource binding 作用域、resource kind、secret reference 摘要和配置 revision/hash

#### Scenario: Verify disabled resource exclusion
- **WHEN** 管理端禁用某个 resource binding 后查询 topology snapshot
- **THEN** snapshot 不包含该禁用资源，且 revision/hash 发生可观测变化

### Requirement: Platform configuration API documents restart or reload semantics
系统 SHALL 文档化基于 revision 轮询、完整快照构建、原子切换和 Last Known Good 的热加载语义。

#### Scenario: 新 revision 成功激活
- **WHEN** Internal API Platform 检测到可装载的新 Published Revision
- **THEN** 新请求使用新 generation，进行中请求继续使用其已捕获的旧 generation

#### Scenario: 新 revision 激活失败
- **WHEN** 新快照构建失败
- **THEN** 文档和 API 明确显示 published 不等于 effective，并保留 Last Known Good

### Requirement: Platform API accepts secret values through write-only fields
系统 SHALL 提供平台密钥管理 API，允许管理端通过 write-only 字段提交 secret 明文值，并只返回 secret ref、状态和脱敏摘要。

#### Scenario: Create secret through API
- **WHEN** 管理端调用 secret 创建接口并提交明文 value
- **THEN** API 返回 secret metadata 和 `secret_ref`，响应中不包含明文 value

#### Scenario: Read secret through API
- **WHEN** 管理端查询 secret 详情
- **THEN** API 返回 configured/version/updated_at/masked_summary，不返回明文 value

### Requirement: Platform API manages DB-backed runtime config
系统 SHALL 提供 runtime config 的 CRUD、启停、snapshot 和校验 API，供后续 Web 配置页面使用。

#### Scenario: Save runtime setting
- **WHEN** 管理端提交合法 runtime setting key、类型、作用域和值
- **THEN** 系统保存配置、更新 revision，并写入配置审计

#### Scenario: Save secret-backed runtime setting
- **WHEN** 管理端把 `ANTHROPIC_API_KEY` 配置为 `secret://platform/deepseek_api_key`
- **THEN** 系统保存 secret ref，并在 snapshot 中仅返回该 ref 的脱敏状态

### Requirement: Platform API exposes env migration guidance
系统 SHALL 提供当前 env key 到 bootstrap-only、deployment safety gate、governed runtime policy、test-only 或 Secret management 的分类与迁移关系。

#### Scenario: List migratable env keys
- **WHEN** 管理端请求可迁移配置项列表
- **THEN** 系统返回 key、类型、安全默认值、是否敏感、分类、建议作用域、适用服务、迁移目标、弃用版本和是否需要重启

#### Scenario: Bootstrap-only key is edited
- **WHEN** 管理端尝试把 `DATABASE_DSN`、`RABBITMQ_URL` 或主加密密钥保存为普通 runtime config
- **THEN** 系统拒绝该配置并提示必须通过部署环境或受控 Secret 管理

#### Scenario: Deployment safety gate is enabled through API
- **WHEN** 管理端尝试通过数据库配置开启被部署环境关闭的已发布 Runtime、真实模型或真实内部工具
- **THEN** 系统拒绝越权开启或保存为被 deployment gate 阻断的请求状态
- **AND** 响应明确说明必须由部署环境开启

#### Scenario: Test-only key is edited in production
- **WHEN** 管理端在生产环境尝试启用测试身份请求头
- **THEN** 系统拒绝修改并记录安全审计事件

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

### Requirement: Platform API exposes effective feature diagnostics
系统 SHALL 向具有配置读取权限的管理员提供只读有效功能配置诊断，返回四个顶层开关、派生管理能力、受治理策略、来源、弃用状态和冲突信息。

#### Scenario: Authorized administrator reads diagnostics
- **WHEN** 具有配置读取权限的管理员请求有效功能配置
- **THEN** 系统返回每项配置的最终值、来源、分类、revision、弃用输入和阻断原因
- **AND** 响应不包含 Secret 明文、完整连接串或未经脱敏的环境变量值

#### Scenario: Unauthorized caller reads diagnostics
- **WHEN** 未认证或不具有配置读取权限的调用方请求详细诊断
- **THEN** 系统拒绝请求并记录审计事件

#### Scenario: Legacy conflict is present
- **WHEN** 启动前检查或草稿发布校验发现新旧配置冲突
- **THEN** API 返回稳定的冲突代码、冲突键和迁移目标

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

