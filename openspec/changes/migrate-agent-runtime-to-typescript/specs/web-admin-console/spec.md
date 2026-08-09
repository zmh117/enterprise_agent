## MODIFIED Requirements

### Requirement: 管理端提供认证后的基础页面
系统 SHALL 提供登录页和认证后的控制台外壳，并 MUST 对未认证用户隐藏本人身份、历史和管理数据。认证后导航 SHALL 按权限包含账户/身份、运行历史、Agent Publication 和 Business Application；已退役 Capability、Internal API Platform、Resource/Secret 编辑器 MUST 不得恢复。

#### Scenario: 未登录访问管理页面
- **WHEN** 浏览器没有有效 Session 访问 Agent 或 Application 页面
- **THEN** 前端跳转统一登录页，后台 API 返回未认证

#### Scenario: 已登录管理员进入控制台
- **WHEN** 用户登录并具有相应权限
- **THEN** 前端展示允许的历史、Agent/Application 导航并加载安全用户摘要

#### Scenario: 普通用户进入控制台
- **WHEN** 用户只有本人身份和历史权限
- **THEN** 管理导航不可见且直接访问管理 URL 由 API 失败关闭

### Requirement: 第一版 UI 只开放默认诊断 Agent
系统 SHALL 使用正式多 Agent API，在本变更完成后列出用户有权读取的全部 Agent，并按每个 Agent 的 RBAC 与生命周期控制创建、编辑、发布、回退、停用和归档。默认诊断 Agent MUST 作为预置对象保留，但 MUST NOT 成为前端单例或阻止其他 Agent 管理。

#### Scenario: 管理员打开 Agent 配置
- **WHEN** 管理员进入 Agent 管理页
- **THEN** 页面展示真实 Agent 列表及各自 Draft、当前 Publication、Runtime 和引用应用摘要

#### Scenario: 数据库存在其它 Agent
- **WHEN** 后端存在第二个且用户有权读取的 Agent
- **THEN** UI 列出并允许按权限管理，而不是隐藏它或回退默认 Agent

### Requirement: 默认 Agent 页面支持草稿校验发布和回滚
系统 SHALL 为每个可管理 Agent 提供基础信息、业务指令、模型连接、执行限制、MCP Tool 最大集合、Skill、Effective preview、校验、Publication 历史和受控回退界面。页面 MUST 不允许编辑强制安全规则、自由 Tool、Provider URL 或 Secret。

#### Scenario: 草稿校验失败
- **WHEN** 管理员提交停用 Tool、无效模型连接或越权配置
- **THEN** 页面显示全部字段级错误且禁用发布

#### Scenario: 发布成功
- **WHEN** 有发布权限管理员发布合法 Draft
- **THEN** 页面显示新 Publication、revision、hash、Runtime version、发布人和时间

#### Scenario: Agent仍被应用引用
- **WHEN** 用户查看或回退一个被活动 Application 引用的 Agent
- **THEN** 页面展示安全 usage 摘要并说明应用不会被自动切换

### Requirement: Web 不展示敏感认证和密钥材料
系统 SHALL 确保页面、浏览器 API、前端状态、错误和构建产物不包含密码 hash、Session Token/hash、Secret ref/value/ciphertext、模型 Key、MCP Authorization、Provider Token、完整连接地址或可重放外部 Payload。

#### Scenario: 查看 Agent/Application 配置
- **WHEN** 管理员查看模型、MCP Tool、Resource、Channel 或失败 Runtime 记录
- **THEN** 页面只显示状态、版本、hash、脱敏 host 和安全 provenance

#### Scenario: 浏览器请求管理目录
- **WHEN** 页面加载 Tool/Resource/Connector 选项
- **THEN** API 只返回受治理公开摘要，不返回服务认证、Secret ref 或底层连接参数

### Requirement: Web 写操作处理 revision 冲突
系统 SHALL 在 Agent、MCP Tool Publication、Application、身份和账户写操作中携带 expected revision、CSRF 和幂等键，并 MUST 在冲突时要求刷新/人工合并而不是静默覆盖或自动重试非幂等发布。

#### Scenario: 两个管理员同时编辑草稿
- **WHEN** 后提交者使用过期 expected revision
- **THEN** API 返回冲突，页面显示当前版本变化并提供刷新比较

#### Scenario: 重复点击发布
- **WHEN** 浏览器因网络重试使用同一幂等键重复发布
- **THEN** 服务返回同一结果或明确冲突，不创建两个 Publication
