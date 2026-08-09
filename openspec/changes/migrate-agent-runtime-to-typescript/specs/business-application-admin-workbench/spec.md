## MODIFIED Requirements

### Requirement: 管理API受统一身份和应用级权限保护
系统 SHALL 复用现有 Web Session、RBAC 和 CSRF 保护 Business Application 管理 API，并 MUST 使用 `business_application` 的 read、create、edit、publish、activate、disable、archive 动作授权；CLI MUST 调用同一 Application Service，不能绕过校验直接写表。

#### Scenario: 有权用户读取应用
- **WHEN** 用户具有目标项目或应用 read 权限
- **THEN** API 返回其可见应用，不返回无权对象摘要

#### Scenario: 未授权用户访问具体应用
- **WHEN** 用户无权读取目标应用
- **THEN** API 返回 404 或等效防枚举结果，审计不泄露内容

#### Scenario: 缺少CSRF执行写操作
- **WHEN** Session 用户缺少有效 CSRF 执行写操作
- **THEN** 系统拒绝且不产生控制面变更

### Requirement: 管理API覆盖业务应用完整控制面生命周期
系统 SHALL 提供应用列表、详情、创建、元数据/生命周期更新、Draft 保存、校验、发布、历史、环境激活/停用和 effective preview，并 MUST 返回 Agent、MCP Tool、Resource、Channel/Delivery 与 Runtime readiness 的安全状态。

#### Scenario: 创建并发布应用
- **WHEN** 有权用户创建应用、保存合法 Draft、校验并发布
- **THEN** API 返回明确资源、revision、hash 和下一步，不隐式激活

#### Scenario: 查询应用详情
- **WHEN** 用户读取详情
- **THEN** API 返回 Definition、Draft、错误、Publication、Deployment、usage 和 `runtime_wired`，不返回 Secret/连接信息

#### Scenario: 请求包含未知字段
- **WHEN** 写请求包含协议外字段
- **THEN** API 返回 422 并拒绝整个请求

### Requirement: 管理API提供稳定的并发与错误契约
系统 MUST 对所有可变资源使用 expected revision 和幂等键，并 SHALL 区分 validation、conflict、forbidden、not found、dependency、integrity 与 runtime-unready 错误。

#### Scenario: 草稿revision冲突
- **WHEN** 客户端使用过期 expected revision
- **THEN** API 返回 409 与当前非敏感摘要，不静默覆盖

#### Scenario: 发布存在多个错误
- **WHEN** Draft 同时存在 Agent、Tool 与 Resource 错误
- **THEN** API 返回可定位的全部安全错误，不只返回首项或堆栈

### Requirement: Web提供真实的业务应用列表与详情工作区
系统 SHALL 用真实 API 恢复“业务应用”列表和详情，替换退役占位页；页面 MUST 展示定义、Agent Publication、MCP Tool/Resource 组成、Channel/Trigger/Delivery、校验、Publication 历史、环境状态和 Runtime readiness。

#### Scenario: 查看业务应用列表
- **WHEN** 用户进入 `/applications`
- **THEN** 页面展示其可见应用、状态、当前 revision、各环境 Publication/Runtime 摘要以及 loading/empty/error 状态

#### Scenario: 查看业务应用详情
- **WHEN** 用户选择一个应用
- **THEN** 页面展示真实组成和版本事实，不显示 Capability、Handler、Connection 或静态 fixture

#### Scenario: 前端未登录
- **WHEN** 管理 API 返回 401
- **THEN** 统一认证门跳转登录，不显示虚构数据或局部登录表单

### Requirement: Web支持受控的应用编辑、校验和发布
系统 SHALL 为有权限用户提供严格表单来创建/编辑应用、选择 Agent Publication、选择其 MCP Tool 子集及 Resource、配置 Channel/Trigger/Delivery、校验、发布和激活/停用环境。页面 MUST 根据 RBAC、expected revision、依赖状态和校验结果控制动作。

#### Scenario: 保存应用草稿
- **WHEN** 用户选择合法精确组件并提交
- **THEN** 页面携带 expected revision/幂等键并展示新 revision，不提交 Secret、底层 URL 或自由 Tool

#### Scenario: 校验失败后修正
- **WHEN** API 返回字段和组件错误
- **THEN** 页面在对应区域展示并保留安全输入，发布/激活保持禁用

#### Scenario: 发布并激活
- **WHEN** 用户先发布再显式激活合法版本
- **THEN** 页面分别更新 Publication 和 Deployment，并明确新 Job 才使用新版本

### Requirement: Capability和数据源安全边界在真实页面中保持有效
系统 MUST 将该区域替换为只读代码目录中的 MCP Tool Publication 与精确 Resource Deployment 选择；页面 MUST 不显示或接受 API Capability、Handler、Connection、自由 Tool/URL/SQL/Redis/LogQL/Shell、Secret 或底层连接配置。

#### Scenario: 查看 MCP Tool 组成区域
- **WHEN** 用户编辑应用
- **THEN** 页面只展示所选 Agent Publication 允许且当前有效的 Tool Publication，并按需要选择受治理 Resource

#### Scenario: 旧客户端提交 Capability
- **WHEN** 请求包含 Capability Release 或旧 Resource Composition
- **THEN** API 明确拒绝且不创建 Draft

#### Scenario: 查看Channel和Delivery引用
- **WHEN** 页面展示 connector
- **THEN** 只显示名称、ID、方向和 configured 状态，不显示凭据或完整敏感 URL

### Requirement: 业务应用工作区满足响应式和可访问性要求
系统 SHALL 在桌面和窄屏保持列表、详情、表单、Tool/Resource 选择、错误、版本历史和环境状态可读，并 MUST 为状态、禁用原因和异步操作提供文本与辅助技术语义。

#### Scenario: 窄屏编辑应用
- **WHEN** 用户在窄屏查看或编辑
- **THEN** 页面使用单列/局部滚动且无阻止整体阅读的横向溢出

#### Scenario: 键盘和辅助技术操作
- **WHEN** 用户使用键盘或辅助技术
- **THEN** 标签、错误摘要、状态、按钮和禁用原因具有可理解名称且不只依赖颜色
