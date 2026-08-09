## MODIFIED Requirements

### Requirement: 管理端提供认证后的基础页面
系统 SHALL 提供登录页和认证后的轻量用户门户，并 MUST 对未认证用户隐藏本人外部身份、会话、Job 历史与调试数据；认证后导航 MUST 只包含登录安全、本人身份、历史和受限调试功能。

#### Scenario: 未登录访问历史页面
- **WHEN** 浏览器没有有效 Session 访问 Job 或 Tool Call 历史
- **THEN** 前端跳转登录页且后台 API 返回未认证

#### Scenario: 已登录用户进入门户
- **WHEN** 用户完成系统账号登录
- **THEN** 前端加载当前用户安全摘要、本人身份和其有权读取的历史，不展示平台配置入口

### Requirement: Web 不展示敏感认证和密钥材料
系统 SHALL 确保轻量门户与浏览器 API 响应不包含密码 Hash、Session Token/Hash、Secret Ref/Value/Ciphertext、MCP Authorization Header、Provider Token、完整连接地址或可重放外部 Payload。

#### Scenario: 查看身份和失败 Tool Call
- **WHEN** 用户查看本人外部身份或 MCP 调试详情
- **THEN** 页面只显示状态、版本、安全错误与脱敏 provenance

### Requirement: Web 写操作处理 revision 冲突
系统 SHALL 在本人身份、默认 Team、密码修改和 Session 撤销等仍保留的写操作中使用 expected revision 或等价并发控制，并 MUST 在冲突时要求刷新而不是静默覆盖。

#### Scenario: 两个请求同时更新默认 Team
- **WHEN** 后提交请求使用过期 revision
- **THEN** API 返回冲突且页面要求重新验证或刷新当前状态

## REMOVED Requirements

### Requirement: 第一版 Web 管理用户角色和钉钉绑定
**Reason**: 人员/角色管理控制台退出前端，钉钉身份改为当前用户通过受信 Challenge 本人绑定。

**Migration**: 不保留旧管理页面；必要禁用/解绑通过受控管理 API/CLI，不能由管理员填写外部 subject。

### Requirement: 第一版 UI 只开放默认诊断 Agent
**Reason**: Agent 管理页面整体删除，轻量门户不展示或切换 Agent。

**Migration**: 无页面迁移；Agent/渠道运行所需发布事实保留在后端受控运维接口。

### Requirement: 默认 Agent 页面支持草稿校验发布和回滚
**Reason**: Agent 草稿、发布和回滚不再由 Web 前端管理。

**Migration**: 移除页面和前端 API Client；需要的运维通过受认证管理 API/CLI 执行。
