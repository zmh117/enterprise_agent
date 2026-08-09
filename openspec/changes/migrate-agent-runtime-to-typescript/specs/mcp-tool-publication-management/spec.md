## ADDED Requirements

### Requirement: MCP Tool Publication 必须具有受治理生命周期
系统 SHALL 为代码注册的 MCP Tool 提供稳定治理对象、可变 Draft、校验结果和不可变 Publication 或等价版本模型，并 MUST 支持创建、更新、校验、发布、停用和历史读取。写操作 MUST 使用 RBAC、CSRF、expected revision、幂等键和安全审计。

#### Scenario: 管理员发布 Tool Binding
- **WHEN** 有权限管理员选择目录中的 Tool、合法 scope 和可选 Resource Deployment 并通过校验
- **THEN** 系统创建不可变 Tool Publication，保存 revision/hash 和审计主体

#### Scenario: 并发修改 Draft
- **WHEN** 第二个管理员使用过期 expected revision 保存
- **THEN** 系统返回冲突且不覆盖已保存 Draft

### Requirement: Tool 目录只能来自代码发布的领域 MCP Server
系统 MUST 只允许选择平台固定 allowlist 中由 ONES/Data MCP 代码注册的 Server、Tool、公开 Schema 和 scope；管理 API、CLI 与 Web MUST NOT 接受自由 Tool 名、Server URL、Schema、任意 HTTP/SQL/LogQL/Redis/Shell、Prompt 模板或认证 Header。

#### Scenario: 选择已注册 Tool
- **WHEN** 管理员从服务端目录选择当前 ONES Tool
- **THEN** Draft 引用目录身份与 Schema hash，而不是复制可编辑 Schema 或执行代码

#### Scenario: 提交自由 Tool
- **WHEN** 请求包含目录外 Tool、自由 URL、查询文本、脚本或自定义 Header
- **THEN** 服务端以字段级安全错误拒绝整个请求且 `tools/list` 不发生变化

### Requirement: Data MCP Tool 必须绑定精确 Resource Deployment
需要数据资源的 Tool Publication MUST 引用同 kind、已发布且 active 的精确 Resource Deployment/Revision；ONES 个人凭据 Tool MUST 不绑定共享 Token 或由管理员选择用户身份。系统 MUST 在发布和 Application 激活时重新校验依赖。

#### Scenario: 发布 Redis Tool
- **WHEN** Draft 选择 Redis 只读 Tool 和合法 Redis Resource Deployment
- **THEN** Publication 冻结 Tool Schema hash、Resource Deployment ID、Resource Revision ID 和 scope

#### Scenario: Resource 已取消发布
- **WHEN** Tool Draft 引用的 Resource Deployment 已 inactive
- **THEN** Tool 校验/发布失败，既有活动应用的新 Job 也失败关闭

### Requirement: Agent 与 Application 必须形成精确 Tool 交集
Agent Publication SHALL 定义该 Agent 可使用的最大 MCP Tool Publication 集合；Application Publication MUST 只选择该集合的子集并冻结精确 Tool Publication revision/hash。Job 可调用集合 MUST 是 Agent、Application、主体/凭据、Resource Deployment 和 MCP Server scope 当前有效交集。

#### Scenario: 两个 Application 使用同一 Agent
- **WHEN** Application A 只选择 ONES Tool，Application B 只选择 Redis Tool
- **THEN** 两者创建的 Job 分别只冻结自己的精确 Tool 子集，不能看到对方 Tool

#### Scenario: Application 选择 Agent 未允许 Tool
- **WHEN** 应用草稿引用不属于 Agent Publication 最大集合的 Tool Publication
- **THEN** 校验和发布失败且不创建部分 Application Publication

### Requirement: Publication 撤权必须立即影响新调用
停用 Tool Publication MUST 立即阻止新 Job 冻结该 Tool，并 MUST 在既有 Job 每次 MCP 调用前由 Worker/MCP Server 复核。已发出的只读上游请求可以有界完成，但后续调用和 retry MUST 失败关闭并记录 `DENIED` provenance。

#### Scenario: Tool 在 Job 排队后被停用
- **WHEN** Job 已冻结 Tool Binding但执行前 Publication 被停用
- **THEN** Runtime 不注册该 Tool或 MCP Server 拒绝调用，并产生安全拒绝审计

#### Scenario: 禁用请求被拒绝
- **WHEN** Tool Publication 仍被活动 Application Deployment 使用
- **THEN** 系统拒绝无保护停用并返回引用应用摘要，或要求先显式停用依赖 Deployment

### Requirement: Tool Publication 管理 API 和 Web 必须脱敏且防枚举
系统 SHALL 提供目录、Draft、校验、Publication、usage 和状态管理 API，并在 Agent/Application 工作区提供选择界面。响应 MUST 只包含非敏感 Server/Tool/Schema/resource 摘要，不得包含 Server 认证、MCP Token、Secret ref/value、连接地址或其他用户身份事实。

#### Scenario: 有权管理员查看 Tool 历史
- **WHEN** 管理员读取其有权管理的 Tool Publication
- **THEN** 页面显示版本、Schema hash、scope、Resource 状态、引用 Agent/Application 和审计摘要

#### Scenario: 无权读取目标 Tool
- **WHEN** 用户访问无权项目或应用范围的 Tool Publication
- **THEN** API 返回 404 或等效防枚举结果且审计不泄露目标内容

### Requirement: Tool Publication 必须产生完整安全审计和拒绝 Provenance
系统 MUST 审计创建、修改、校验、发布、停用、回退和依赖冲突，并 MUST 为过期 Runtime/MCP Token、停用 Publication、scope 拒绝和 Resource 撤权记录 `DENIED` Tool provenance。记录 MUST 不含认证材料、请求原文或 Provider 原始响应。

#### Scenario: 过期 MCP Token 被拒绝
- **WHEN** Runtime 使用过期 Token 调用已发布 Tool
- **THEN** MCP Server 拒绝调用并记录可关联 Job、Tool、稳定原因码和 `DENIED` 状态

#### Scenario: 管理员回退 Tool 配置
- **WHEN** 管理员从历史 Publication 创建新 Draft、重新验证并发布
- **THEN** 审计关联来源和新 Publication，历史不可变记录保持不变
