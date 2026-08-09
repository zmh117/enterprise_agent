## ADDED Requirements

### Requirement: 用户门户必须保留完整登录与 Session 安全
前端 MUST 保留登录、退出、修改密码、Session 列表与撤销、Cookie、CSRF 和认证路由保护；未认证用户 MUST 不能读取身份、历史或调试数据。

#### Scenario: 未登录访问 Job 历史
- **WHEN** 浏览器没有有效 Session 访问历史路由
- **THEN** 前端跳转登录页且 API 返回未认证，不展示缓存业务数据

### Requirement: 用户门户必须支持本人外部身份管理
已登录用户 MUST 能查看自己的钉钉与 ONES 身份状态、发起钉钉 Challenge、执行 ONES 两阶段本人验证、选择默认 Team、重新验证和解绑；前端 MUST 不允许用户输入目标 `user_id`，管理员 MUST 不能代用户提交 ONES 密码。

#### Scenario: 用户重新验证 ONES
- **WHEN** 当前用户的 ONES 凭据失效
- **THEN** 门户允许本人重新提交邮箱密码和确认 Team，并且浏览器响应中不出现 Token

#### Scenario: 用户完成钉钉 Challenge
- **WHEN** 当前用户生成短时绑定码
- **THEN** 门户只展示绑定步骤和过期状态，最终身份来自受信钉钉消息而不是用户填写 subject ID

### Requirement: 用户门户必须保留历史和受限调试
门户 MUST 提供当前用户有权访问的会话、Job、Step、MCP Tool Call、结果摘要、Ingress、Delivery 和失败诊断；调试入口 MUST 使用当前认证主体且不得允许覆盖用户、Job Snapshot、Resource Revision、Credential 或 MCP Server。

#### Scenario: 用户查看自己的失败 Job
- **WHEN** Job 因 MCP Tool 或 Delivery 失败
- **THEN** 页面展示安全错误、步骤、Tool Provenance 和投递状态，不展示 Header、Secret Ref、连接信息或 Token

#### Scenario: 用户查询其他人的 Job
- **WHEN** 当前用户请求无权访问的 Job ID
- **THEN** API 返回防枚举的未找到或拒绝结果

### Requirement: 平台管理页面必须退出用户门户
前端 MUST 移除或禁用 Agent、API Capability、Handler、Connection、内置工具治理、Resource、Secret、业务应用工作台、角色授权控制台和通用 Runtime Config 编辑路由与导航；门户 MUST 不保留调用这些写 API 的隐藏表单或自由文本入口。

#### Scenario: 管理员登录轻量门户
- **WHEN** 具有平台管理权限的用户登录
- **THEN** 前端仍只展示用户门户允许的身份、历史和调试功能，平台资源运维通过 `platformctl` 完成

#### Scenario: 访问旧管理 URL
- **WHEN** 用户直接访问已移除的管理路由
- **THEN** 前端返回明确的已移除提示，不加载旧页面或静态假数据

### Requirement: 前端构建不得继续依赖已移除控制面模块
前端路由、导航、API Client、查询缓存和生产构建 MUST 不再导入已移除的 Capability、平台治理和业务应用工作台模块；删除后 MUST 通过类型检查、单元测试、生产构建和浏览器授权流程。

#### Scenario: 生产构建轻量门户
- **WHEN** 执行前端生产构建和路由测试
- **THEN** 构建成功且不存在指向已移除页面的导入、导航或 API 调用
