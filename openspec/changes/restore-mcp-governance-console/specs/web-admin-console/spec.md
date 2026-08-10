## MODIFIED Requirements

### Requirement: 管理端提供认证后的基础页面
系统 SHALL 提供登录页和认证后的权限感知管理 Shell，并 MUST 对未认证用户隐藏本人身份、Session、Job 历史和全部治理数据。认证后导航 SHALL 同时支持本人安全功能和当前角色允许的治理功能，前端隐藏导航不得替代后端授权。

#### Scenario: 未登录访问治理或历史页面
- **WHEN** 浏览器没有有效 Session 访问任一管理、身份、Job 或调试路由
- **THEN** 前端进入登录流程且后台 API 返回未认证，不返回对象摘要

#### Scenario: 已登录用户进入控制台
- **WHEN** 用户完成系统账号登录
- **THEN** 前端加载当前用户安全摘要、本人身份和代码拥有权限，并只展示允许的导航和数据

### Requirement: Web 不展示敏感认证和密钥材料
系统 SHALL 确保管理 Shell 和浏览器 API 响应不包含密码 Hash、Session Token/Hash、Secret Ref/Value/Ciphertext、Master Key、MCP Authorization Header、Provider Token、完整敏感连接地址、私有推理或可重放外部 Payload。

#### Scenario: 查看身份、Resource 或失败 Tool Call
- **WHEN** 用户查看本人/他人外部身份、MCP Resource、Credential 或 Tool Call 详情
- **THEN** 页面只显示权限允许的状态、版本、安全错误、用途和脱敏 provenance

### Requirement: Web 写操作处理 revision 冲突
系统 SHALL 在用户、角色、身份、Agent、Application、Channel、Tool Publication、Resource 和 Credential 写操作中使用 expected revision/version 或等价并发控制，并 MUST 在冲突时要求刷新而不是静默覆盖。

#### Scenario: 两个管理员同时编辑治理对象
- **WHEN** 后提交请求使用已经过期的 expected revision/version
- **THEN** API 返回稳定冲突码，页面显示当前版本已变化并允许刷新比较

## ADDED Requirements

### Requirement: 管理 Shell 提供完整 MCP 治理导航
系统 SHALL 在认证后的管理 Shell 中按权限提供总览、Agent、Application、渠道与触发器、调试与运行历史、人员与账号、角色与授权、身份治理和 MCP 配置导航。MCP 配置 MUST 取代旧平台治理，且 MUST NOT 出现 API Capability、Handler、Connection 或 Resource Mapping 路由。

#### Scenario: 用户只具有运行历史读取权限
- **WHEN** 用户登录且只具有自己范围内的运行历史读取权限
- **THEN** 页面只展示允许的导航，直接请求其它治理 API 时后端仍拒绝

#### Scenario: 用户访问退役导航地址
- **WHEN** 用户访问旧 API Capability、Handler、Connection 或 Resource Mapping 地址
- **THEN** 页面返回不存在或已退役结果，不加载备份组件或兼容 API

### Requirement: Web 恢复人员角色和钉钉受信绑定
系统 SHALL 提供用户列表/详情、用户启停、角色列表/详情、用户角色分配和钉钉身份绑定管理页面，并 MUST 在操作前显示目标和影响范围。钉钉绑定 MUST 由未绑定候选或已存在受信身份发起，页面不得以手工输入 `senderStaffId` 建立新的可信身份事实。

#### Scenario: 管理员绑定钉钉候选
- **WHEN** 管理员从服务端候选中选择钉钉身份和目标自然人用户并提交当前版本
- **THEN** 页面调用受信绑定 API、显示成功摘要并刷新用户身份和候选列表

#### Scenario: 客户端手工提交 senderStaffId
- **WHEN** 客户端没有受信候选而直接提交任意 `senderStaffId`
- **THEN** 后端拒绝创建绑定且不产生外部身份事实

### Requirement: Web 支持多个 Agent 的完整发布生命周期
系统 SHALL 列出当前用户有权管理的全部 Agent，并 SHALL 为每个 Agent 提供 Draft、字段校验、有效配置预览、Publication、历史和回退。任何 Agent MUST 使用自己的 revision、config hash 和对象范围。

#### Scenario: 管理员切换 Agent
- **WHEN** 管理员从 Agent 列表进入另一个 Agent
- **THEN** 页面加载该 Agent 自己的 Draft、当前 Publication 和历史，不复用默认 Agent 的状态

#### Scenario: 发布 Agent Draft
- **WHEN** 有发布权限的管理员发布验证通过的 Agent Draft
- **THEN** 系统创建该 Agent 的不可变 Publication 并返回 revision、config hash、发布人和时间

### Requirement: Web 支持多个 Application 的完整发布和激活生命周期
系统 SHALL 列出当前用户有权管理的全部 Application，并 SHALL 为每个 Application 提供 Draft、校验、Publication、历史、回退以及按环境激活和停用。页面 MUST 明确区分“已发布版本”和“环境当前激活版本”。

#### Scenario: 激活 Application Publication
- **WHEN** 管理员在允许环境中激活一个验证通过的 Application Publication
- **THEN** 系统原子更新该环境的活动引用并显示 publication revision、config hash、操作者和时间

#### Scenario: 停用 Application 环境
- **WHEN** 管理员确认停用某 Application 在指定环境的活动入口
- **THEN** 新入口 Job 被拒绝，历史 Publication 和 Job 保持可查
