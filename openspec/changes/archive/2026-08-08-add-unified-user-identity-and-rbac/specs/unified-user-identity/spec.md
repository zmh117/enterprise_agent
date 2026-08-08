## ADDED Requirements

### Requirement: 内部用户是跨入口唯一权限主体
系统 SHALL 为每个自然人或受管服务账号创建稳定的内部用户 ID，并 MUST 让 Web 登录、钉钉入口、Agent job、工具调用、配置操作和审计使用该内部用户 ID 作为权限主体。

#### Scenario: 同一用户从 Web 和钉钉访问
- **WHEN** 一个启用用户使用本地 Web 账号登录，并通过已绑定的钉钉身份发送 Agent 请求
- **THEN** 两个入口解析到同一个内部用户 ID，并使用同一组角色、工具权限和平台数据范围

#### Scenario: 外部身份字段发生变化
- **WHEN** 用户昵称或其它非唯一钉钉展示字段发生变化
- **THEN** 系统仍通过稳定绑定解析同一个内部用户，不复制用户或权限

### Requirement: 钉钉外部身份按 provider tenant 和 subject 唯一绑定
系统 SHALL 使用 `provider + tenant_code + external_subject_id` 唯一标识钉钉外部身份，并 MUST 从受信 connector 配置解析 tenant/corp 边界。系统 MUST NOT 仅凭昵称、姓名、手机号、邮箱或缺少 tenant 的员工号自动绑定用户。

#### Scenario: 管理员绑定钉钉员工
- **WHEN** 管理员为内部用户提交启用的钉钉 tenant、connector 和 `senderStaffId`
- **THEN** 系统创建唯一外部身份绑定并返回不包含敏感 payload 的绑定摘要

#### Scenario: 同一钉钉身份绑定两个用户
- **WHEN** 管理员尝试把同一 provider、tenant 和 `senderStaffId` 绑定到另一个用户
- **THEN** 系统拒绝绑定、保留原关系并记录冲突审计

#### Scenario: 不同企业出现相同员工号
- **WHEN** 两个钉钉 tenant 使用相同 `senderStaffId`
- **THEN** 系统把它们视为两个独立外部身份，不发生跨企业权限共享

### Requirement: 第一版钉钉身份由管理员手工管理
系统 SHALL 在第一版支持管理员创建、查看、启用、禁用和解绑钉钉外部身份，并 MUST NOT 自动为未知钉钉发送者创建内部用户。

#### Scenario: 未绑定用户发送消息
- **WHEN** 钉钉 Stream 收到无法解析到启用内部用户的发送者
- **THEN** 系统安全拒绝请求、记录 identity resolution denial，并且不创建 Agent job

#### Scenario: 管理员禁用外部身份
- **WHEN** 管理员禁用某个钉钉绑定但保持内部用户启用
- **THEN** 该用户仍可通过其它有效身份登录，但该钉钉身份不能创建新 job

### Requirement: 用户和身份状态立即影响新请求
系统 SHALL 对内部用户和外部身份执行 enabled/disabled 状态检查，并 MUST 在用户或身份被禁用后阻止新的认证、Channel 请求和权限使用。

#### Scenario: 用户被禁用
- **WHEN** 管理员禁用一个已有 Web session 和钉钉绑定的用户
- **THEN** 系统使其现有管理 session 失效，并拒绝后续 Web 和钉钉请求

#### Scenario: 用户重新启用
- **WHEN** 管理员重新启用用户但外部身份仍为 disabled
- **THEN** 用户可通过其它启用登录身份访问，但被禁用的钉钉身份仍不可用

### Requirement: 外部身份来源可审计但不替代内部 actor
系统 SHALL 在新 job、session、消息和审计中保存内部用户 ID，并 MAY 保存外部身份记录 ID、provider、tenant 和 connector 作为来源证据。系统 MUST NOT 把完整钉钉 payload 或不必要的个人信息复制到权限策略和审计摘要。

#### Scenario: 钉钉请求被接受
- **WHEN** 已绑定钉钉用户通过 Stream 创建 job
- **THEN** job requester 使用内部用户 ID，审计关联外部身份记录和 connector，并避免保存完整原始身份 payload

### Requirement: 历史原始主体迁移可对账且不错误合并
系统 SHALL 为现有用户型 permission、platform grant 和已知钉钉主体提供 legacy 映射及迁移报告，并 MUST 保留历史 job/session/audit 的可追溯性。无法唯一确定 tenant 或用户归属的主体 MUST 保持未迁移或 legacy 状态。

#### Scenario: 现有主体可唯一匹配
- **WHEN** 现有 user policy 的主体能通过已知 tenant 和 `senderStaffId` 唯一映射到内部用户
- **THEN** 系统迁移该权限到内部主体并在对账报告中记录映射

#### Scenario: 现有主体存在歧义
- **WHEN** 同一原始主体可能属于多个 tenant 或无法确认所属用户
- **THEN** 系统不自动合并，报告人工处理项，并保持历史记录不变
