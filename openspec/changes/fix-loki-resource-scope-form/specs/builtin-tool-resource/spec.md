## MODIFIED Requirements

### Requirement: Resource management UI edits connection and scope in one Draft
“平台治理 → 工具资源” SHALL 在同一 Resource Draft 中分区编辑连接和数据范围，并只提供一次保存、验证和发布生命周期；界面 MUST NOT 把数据范围表现为独立页面、独立发布物或 Application Resource Mapping。新建与编辑 Loki Draft 时，前端 MUST NOT 将空的 Workshop 占位字段序列化到 scope_bindings，且 MUST 保留数据库和 Redis 的 Workshop 范围字段；非空非法 Loki Workshop 与其他未知字段 MUST 继续被严格校验拒绝，不得静默删除来扩大目标范围。

#### Scenario: 新建数据库资源
- **WHEN** 管理员选择数据库 Provider、平台目标、Secret 和 Workshop 表前缀
- **THEN** 前端提交一个包含连接配置与 scope bindings 的 Resource Draft，且不提交 Secret 明文

#### Scenario: 查看发布版本
- **WHEN** 管理员查看已发布的 DB、Redis 或 Loki Resource Revision
- **THEN** 页面只读展示该版本的连接安全摘要和数据范围，并要求从该版本创建 Draft 后才能修改

#### Scenario: Loki 选择环境或基地后保存
- **WHEN** 管理员在新建或编辑 Loki Draft 时改变 Environment/Base 数据范围目标并配置有效精确 selector
- **THEN** 提交的 scope_bindings 不包含空 workshop_code，保存不会因此出现未知字段错误

#### Scenario: 前端已有空 Workshop 占位值
- **WHEN** Loki 表单数据范围含空串、null 或 undefined 的 workshop_code
- **THEN** 两条保存路径仅从提交副本移除该占位字段，保留环境、基地和 selector，不修改原始表单对象

#### Scenario: 非法非空 Loki Workshop
- **WHEN** Loki 数据范围含非空 workshop_code 或其他未声明字段
- **THEN** 保存仍被拒绝，不得通过通用字段过滤放宽后端契约

#### Scenario: 数据库和 Redis 的车间范围
- **WHEN** 管理员保存数据库或 Redis 的 Workshop 数据范围
- **THEN** 前端保留原有 workshop_code、表前缀或 namespace prefixes 及父子目标联动规则
