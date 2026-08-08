## ADDED Requirements

### Requirement: Redis 和 Loki 必须由已发布 Resource Revision 提供
Redis 与 Loki 的地址、认证、tenant/数据库号及查询边界 MUST 来自业务应用发布绑定的具体 Resource Revision，并被复制到 Job Execution Scope。

#### Scenario: Redis 发布新 revision
- **WHEN** Redis Resource Identity 发布新 revision 但应用未重新发布
- **THEN** 已发布应用和新建 Job 继续使用原绑定 revision

#### Scenario: Loki 请求覆盖 tenant
- **WHEN** 工具参数请求与绑定 revision 不同的 tenant
- **THEN** 平台必须拒绝或强制使用绑定 tenant，不能扩大范围

### Requirement: Redis 字段契约必须统一
Redis Resource MUST 使用 `host`、`port`、`database`、可选 `username`、`password_ref` 和受控 TLS 配置；管理 API、前端、验证器和运行时不得使用相互不兼容的 `db/user` 别名。

#### Scenario: 旧字段被导入
- **WHEN** import 遇到旧 `db` 或 `user` 字段
- **THEN** 导入器必须显式转换为 canonical 字段并生成 Draft，不能直接发布

### Requirement: Loki 字段契约必须统一
Loki Resource MUST 使用 `base_url`、可选 `tenant_id`、认证 Secret reference、超时和查询上限；管理 API、前端和运行时必须共享同一 schema。

#### Scenario: Draft 使用旧 tenant 字段
- **WHEN** 新建 Draft 直接提交歧义字段 `tenant`
- **THEN** API 必须拒绝或通过有审计的导入转换为 `tenant_id`

### Requirement: Secret 缺失必须阻止相关资源而非回退
Redis 或 Loki Published Revision 的 Secret 无法解析时，系统 MUST 保留 Last Known Good；没有 LKG 时仅阻止依赖该资源的应用。

#### Scenario: Redis 密码 Secret 被禁用
- **WHEN** runtime reload 无法解析 Redis `password_ref`
- **THEN** Redis revision 标为 degraded，且不得从 env 或旧配置回退
