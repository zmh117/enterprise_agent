## ADDED Requirements

### Requirement: 管理端提供认证后的基础页面
系统 SHALL 提供登录页和认证后的管理端外壳，并 MUST 对未认证用户隐藏管理数据和操作。

#### Scenario: 未登录访问管理页面
- **WHEN** 浏览器没有有效管理 session 访问用户或 Agent 页面
- **THEN** 前端跳转登录页，后台 API 返回未认证响应

#### Scenario: 已登录管理员进入控制台
- **WHEN** 拥有相应权限的用户登录
- **THEN** 前端根据权限展示可访问导航并加载当前用户安全摘要

### Requirement: 第一版 Web 管理用户角色和钉钉绑定
系统 SHALL 提供用户列表/详情、用户启停、角色列表/详情、用户角色分配和钉钉身份绑定管理页面，并 MUST 在操作前显示目标和影响范围。

#### Scenario: 管理员绑定钉钉身份
- **WHEN** 管理员在用户详情页选择 tenant/connector 并提交 `senderStaffId`
- **THEN** 页面调用绑定 API、显示成功摘要并刷新该用户身份列表

#### Scenario: 绑定发生冲突
- **WHEN** 目标钉钉身份已绑定其他用户
- **THEN** 页面显示明确冲突，不覆盖原绑定

### Requirement: 第一版 UI 只开放默认诊断 Agent
系统 SHALL 使用多 Agent API 和数据模型，但第一版 Web MUST 只展示 `default-diagnostic-agent`，并 MUST 不提供创建、删除或切换到其它 Agent 的入口。

#### Scenario: 管理员打开 Agent 配置
- **WHEN** 管理员进入 Agent 管理页面
- **THEN** 页面直接展示默认诊断 Agent 的草稿、当前 publication 和发布历史

#### Scenario: 数据库存在其它 Agent
- **WHEN** 后端数据中存在其它 Agent 定义
- **THEN** 第一版 UI 不列出或允许管理这些 Agent，但 API 权限和 repository 仍保持多 Agent 隔离

### Requirement: 默认 Agent 页面支持草稿校验发布和回滚
系统 SHALL 提供默认 Agent 的基础信息、业务指令、模型/限制、已有只读工具、Skill、Channel/Delivery、有效配置预览、校验、发布和回滚界面。

#### Scenario: 草稿校验失败
- **WHEN** 管理员提交包含无效工具或缺失 connector 的草稿
- **THEN** 页面显示字段级错误且不允许发布

#### Scenario: 发布成功
- **WHEN** 有发布权限的管理员发布合法草稿
- **THEN** 页面显示新 revision、config hash、发布人和发布时间

### Requirement: Web 不展示敏感认证和密钥材料
系统 SHALL 确保管理页面和浏览器 API 响应不包含密码 hash、session token/hash、secret value/ciphertext、完整敏感外部 payload 或钉钉凭证。

#### Scenario: 查看用户与 Agent 配置
- **WHEN** 管理员查看用户、外部身份或 Agent 模型配置
- **THEN** 页面只显示必要状态、引用和脱敏摘要

### Requirement: Web 写操作处理 revision 冲突
系统 SHALL 在用户、角色、身份绑定和 Agent 草稿写操作中携带 expected revision 或等价并发控制，并 MUST 在版本冲突时要求刷新而不是静默覆盖。

#### Scenario: 两个管理员同时编辑草稿
- **WHEN** 后提交者使用已经过期的 expected revision 保存
- **THEN** API 返回冲突，页面展示当前版本已变化并允许刷新比较
