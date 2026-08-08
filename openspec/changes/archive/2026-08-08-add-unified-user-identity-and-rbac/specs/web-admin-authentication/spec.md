## ADDED Requirements

### Requirement: 管理端支持安全的本地账号登录
系统 SHALL 支持启用用户通过用户名和密码登录管理端，并 MUST 使用经过审计的强密码哈希算法保存密码验证材料。系统 MUST NOT 保存或返回明文密码。

#### Scenario: 正确凭证登录
- **WHEN** 启用用户提交正确用户名和密码
- **THEN** 系统创建服务端 session、记录登录成功审计并返回不含密码材料的当前用户信息

#### Scenario: 错误凭证登录
- **WHEN** 用户提交错误密码、未知用户名或已禁用账号
- **THEN** 系统返回一致的安全失败响应、记录受限审计，并不泄漏账号是否存在

### Requirement: Web 使用可撤销的服务端 session
系统 SHALL 生成高熵随机 session token，只在安全 cookie 中返回明文 token，并 MUST 只在数据库保存 token hash、用户、创建时间、最后使用时间、过期时间和撤销状态。

#### Scenario: 有效 session 访问管理 API
- **WHEN** 浏览器携带未过期且未撤销的 session cookie
- **THEN** authentication middleware 解析内部用户 principal 并把它传给管理 API

#### Scenario: 用户退出
- **WHEN** 用户调用退出接口
- **THEN** 系统撤销当前 session、清除 cookie，并拒绝后续使用原 token

#### Scenario: 用户被禁用
- **WHEN** 管理员禁用一个拥有多个活动 session 的用户
- **THEN** 系统撤销或立即拒绝该用户的所有 session

### Requirement: 管理端请求具备 CSRF 和 cookie 安全保护
系统 SHALL 对基于 cookie 的状态修改请求执行 SameSite、Origin 和 CSRF 防护，并 MUST 在生产环境使用 Secure、HttpOnly cookie。

#### Scenario: 合法 Web 表单提交
- **WHEN** 已认证页面携带有效 CSRF token 和允许的 Origin 提交修改
- **THEN** 系统继续执行权限和业务校验

#### Scenario: 跨站请求缺少 CSRF 证明
- **WHEN** 状态修改请求来自不允许的 Origin 或缺少有效 CSRF token
- **THEN** 系统拒绝请求且不执行配置修改

### Requirement: 管理 API actor 来自可信认证上下文
系统 SHALL 从 authentication middleware 注入的内部 principal 获取 actor，生产模式 MUST NOT 信任客户端直接提交的 `x-admin-user-id` 或 `x-agent-user-id`。

#### Scenario: 客户端伪造管理员请求头
- **WHEN** 未认证请求仅携带 `x-admin-user-id`
- **THEN** 生产管理 API 返回未认证错误且不执行操作

#### Scenario: 测试适配器注入 principal
- **WHEN** 测试环境显式启用 test-only identity adapter
- **THEN** 测试可以注入内部 principal，但该能力不能在生产配置中默认启用

### Requirement: 首个管理员通过显式 bootstrap 创建
系统 SHALL 提供显式运维命令创建首个管理员，并 MUST NOT 在生产 migration 或 seed 中创建已知默认密码。

#### Scenario: 空系统创建首个管理员
- **WHEN** 运维人员在没有管理员的环境执行 bootstrap 命令并安全输入凭证
- **THEN** 系统创建内部用户、管理员角色关系和审计记录

#### Scenario: 重复执行 bootstrap
- **WHEN** 系统已经存在管理员并再次执行未授权 bootstrap
- **THEN** 系统拒绝创建额外默认管理员
