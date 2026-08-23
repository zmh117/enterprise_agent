## ADDED Requirements

### Requirement: 系统必须提供项目角色人员只读 Tool
系统 MUST 在 `ones-mcp` 代码 Manifest 中提供 `ones_list_project_role_members`，只查询当前 Principal 默认 Team 内指定项目的角色和人员。该 Tool MUST 为只读、`INTERNAL` 数据分级，MUST NOT 创建 API Capability、Handler、Release 或动态 HTTP 实现。

#### Scenario: Tool 在代码 Manifest 中暴露
- **WHEN** `ones-mcp` 使用完整且无冲突的 Tool Manifest 启动
- **THEN** `tools/list` 返回 `ones_list_project_role_members` 的稳定业务 schema，而不返回 REST URL、Header 或原始响应结构

### Requirement: 项目角色人员 Tool 输入必须只包含项目 UUID
`ones_list_project_role_members` Input Schema MUST 只接受非空且长度受限的 `project_uuid`。Team UUID、User ID、Token、URL、Method、Path、Header 和请求体 MUST NOT 由模型提供。

#### Scenario: 合法项目 UUID
- **WHEN** 已授权用户提交合法 `project_uuid`
- **THEN** Service 使用当前 Principal 的默认 Team 和该项目 UUID 构造固定 REST Path

#### Scenario: 调用方提交额外请求字段
- **WHEN** 输入包含 Team、用户、Token、URL、Method、Header 或 Body
- **THEN** Tool 在外部请求前拒绝调用

### Requirement: 项目角色人员 Tool 必须执行固定两步 REST 查询
Service MUST 先按已提供契约调用固定项目角色成员 GET，保留角色顺序并收集所有 member UUID；随后 MUST 去重 UUID 并按已提供契约调用固定 Team users POST；最后 MUST 以 UUID 将用户姓名映射回各角色。调用集合和顺序 MUST 由代码固定。

#### Scenario: 两步查询成功
- **WHEN** GET 返回合法角色/成员 UUID，POST 返回全部请求用户的 UUID/姓名
- **THEN** Tool 按原角色顺序返回每个角色及其成员 UUID/姓名

#### Scenario: 项目没有角色人员
- **WHEN** GET 按已提供空结果契约返回空角色列表或角色成员为空
- **THEN** Tool 返回合法空结果，不伪造人员且不执行无必要的用户查询

#### Scenario: 用户响应缺少成员
- **WHEN** POST 没有返回 GET 中引用的某个成员 UUID
- **THEN** Tool 按 Provider 响应不完整失败，不省略该成员或返回错误姓名

### Requirement: 项目角色人员 Tool 输出必须是有界角色摘要
Output Schema MUST 返回 `roles` 和 `untrusted_data: true`。每个角色只包含 `role_uuid`、`role_name` 和 `members`；每个 member 只包含 `uuid`、`name`。系统 MUST 限制角色数、每角色人数和字符串长度，MUST NOT 返回邮箱、电话、头像、部门、Token 或完整 Provider 响应。

#### Scenario: 输出角色与姓名
- **WHEN** 两个 Provider 请求均成功且响应符合契约
- **THEN** 模型只收到按角色组织的 UUID/名称摘要和不可信数据标记

#### Scenario: Provider 返回额外个人字段
- **WHEN** Team users 响应包含邮箱、电话、头像、部门或其它未声明字段
- **THEN** 响应解析器丢弃这些字段，Tool 输出和审计均不包含它们

### Requirement: 新 Tool 必须沿用当前用户身份与发布授权
`ones_list_project_role_members` MUST 使用 Principal JWT/JWKS 认证、当前用户活动 ONES Token/User ID 和默认 Team，并同时满足代码 Manifest、精确 invoke scope、Agent Publication、Application Publication、角色 Grant 和 Job 冻结 Tool/schema hash。旧 Publication、Grant 和 Job MUST NOT 因部署新代码自动获得新 Tool。

#### Scenario: 新发布显式授权
- **WHEN** 新 Agent/Application Publication、角色 Grant 和新 Job 均显式包含该 Tool
- **THEN** 当前用户可以查询其默认 Team 内有权访问的项目角色人员

#### Scenario: 旧 Job 调用新 Tool
- **WHEN** 调用来自未冻结该 Tool 的旧 Job
- **THEN** 系统在 ONES 请求前拒绝调用

#### Scenario: Provider 返回 401 或 403
- **WHEN** 当前用户 Token 失效或无权访问指定项目
- **THEN** 系统沿用现有一次受控 Token 刷新和失败关闭策略，且不切换用户、Team、管理员或服务账号

### Requirement: 现有工作项搜索契约必须保持不变
将工作项 GraphQL document 移入文件目录 MUST NOT 改变 `ones_work_item_search` 的 Tool identifier、input/output schema、固定 Path、variables、当前用户/默认 Team 绑定、授权、Token 刷新、审计或错误语义。

#### Scenario: 工作项迁移回归
- **WHEN** 对迁移前后的工作项 Operation 使用相同 Principal、输入和 Provider fixture
- **THEN** Provider 请求和规范化 Tool 输出保持契约等价
