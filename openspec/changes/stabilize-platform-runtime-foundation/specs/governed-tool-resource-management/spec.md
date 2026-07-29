## ADDED Requirements

### Requirement: 工具资源必须通过草稿、验证和发布生命周期
DB、Redis、Loki Resource MUST 具有稳定身份、可编辑 Draft、技术验证结果和不可变 Published Revision；正常发布路径为 `DRAFT → VERIFIED → PUBLISHED`，不包含审核审批步骤。

#### Scenario: 发布已验证草稿
- **WHEN** 授权发布者发布字段、Secret、连接和只读检查均通过的 VERIFIED draft
- **THEN** 系统创建新的不可变 revision 并记录发布者、时间、校验摘要和审计

#### Scenario: 发布未验证草稿
- **WHEN** draft 尚未验证或验证结果已因内容变化失效
- **THEN** 系统必须拒绝发布

### Requirement: 已发布资源不得原地修改或普通删除
Draft 可以删除；Published Revision MUST NOT 被原地修改或通过普通 CRUD 物理删除，只能 disable 或 archive。

#### Scenario: 修改已发布 revision
- **WHEN** 管理员尝试修改 Published Revision 的连接字段或 Secret 引用
- **THEN** 系统必须拒绝，并要求从该版本创建新 Draft

### Requirement: 业务应用发布必须绑定具体 Resource Revision
业务应用发布 MUST 为每个逻辑资源槽保存具体 Resource Revision ID；运行中的 Job 不得跟随 Resource Identity 的后续浮动版本。

#### Scenario: 资源发布新版本
- **WHEN** 某 Resource 发布新 revision，但业务应用尚未重新发布
- **THEN** 该业务应用继续绑定原 revision

### Requirement: 运行时必须原子热加载并保留 Last Known Good
运行时 SHALL 轮询发布版本并完整构建不可变资源快照后原子切换；加载失败不得用部分或无效快照覆盖 Last Known Good。

#### Scenario: 新快照加载成功
- **WHEN** 新发布 revision 的 Secret 与驱动均可解析
- **THEN** 进行中请求继续使用旧快照，新请求使用新快照

#### Scenario: 新快照加载失败
- **WHEN** 新 revision 缺少 Secret 或连接初始化失败
- **THEN** 运行时保留 Last Known Good，将相关资源和应用标为 degraded，并记录脱敏错误

#### Scenario: 必需资源没有 Last Known Good
- **WHEN** 已发布应用所需资源从未成功装载
- **THEN** 仅该应用必须被标为 blocked 并拒绝新建资源依赖 Job

### Requirement: 工具资源管理界面必须展示实际生效状态
“平台治理 → 工具资源” MUST 支持 DB、Redis、Loki 的列表、Draft 编辑、Secret 选择、测试、发布、disable/archive，并区分 draft、published、effective 和 activation 状态。

#### Scenario: 管理员查看资源详情
- **WHEN** 资源新版本已发布但运行时加载失败
- **THEN** 界面必须同时显示 Published Revision、当前 Effective Revision、失败状态和安全错误，不能误报已生效

### Requirement: 全量资源重置必须使用四阶段维护命令
系统 MUST 提供 `resource-reset report/prepare/apply/verify`，只清理 DB、Redis、Loki 资源、revision、binding 和当前快照；Provider、Secret、身份、RBAC、应用、Job、Delivery、审计和历史快照必须保留。

#### Scenario: Prepare 后状态发生变化
- **WHEN** apply 前的对象清单 digest 与 prepare 结果不一致
- **THEN** apply 必须拒绝并要求重新 report/prepare

#### Scenario: 仍有运行中的资源依赖 Job
- **WHEN** 维护排空超时且仍存在运行任务
- **THEN** prepare 必须中止，不得强杀任务或继续删除资源

#### Scenario: 用户确认精确清单
- **WHEN** apply 再次展示 operation ID、备份引用和精确影响并得到明确确认
- **THEN** 系统在单个受控事务中清理目标并把依赖应用标为 blocked
