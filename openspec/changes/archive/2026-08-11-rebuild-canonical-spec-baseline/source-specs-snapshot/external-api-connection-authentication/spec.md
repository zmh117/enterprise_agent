# external-api-connection-authentication Specification

## Purpose
TBD - created by archiving change add-governed-api-capability-handlers. Update Purpose after archive.
## Requirements
### Requirement: API Connection 使用 Draft Verify Publish 生命周期
API Connection MUST 具有稳定身份、可编辑 Draft、验证证据和不可变 Published Revision，正常发布路径为 `DRAFT → VERIFIED → PUBLISHED`；Draft 内容改变 MUST 使原验证证据失效。

#### Scenario: 发布已验证 Connection
- **WHEN** 授权管理员发布 Revision 与内容 hash 均匹配的 VERIFIED Draft
- **THEN** 系统创建不可变 Connection Revision并记录发布者、时间和安全验证摘要

#### Scenario: 发布未验证 Connection
- **WHEN** Draft 未验证或验证后 Origin/Authentication Profile 已变化
- **THEN** 系统拒绝发布且不创建部分 Revision

#### Scenario: 修改 Published Connection
- **WHEN** 管理员尝试原地修改已发布 Origin 或认证配置
- **THEN** 系统拒绝并要求复制为新 Draft

### Requirement: Connection 固定请求 Origin
Connection Revision MUST 固定 scheme、host 和 port；Handler 只能引用该 Connection 并配置相对路径。系统 MUST 拒绝用户信息、动态 host、完整请求 URL 和跨 Origin 认证材料传递。

#### Scenario: 组合合法相对路径
- **WHEN** 已发布 Connection Origin 为受信任 ONES 地址且 Handler 使用合法相对路径
- **THEN** 执行器只向规范化后的同一 Origin 发起请求

#### Scenario: Handler 提交完整 URL
- **WHEN** Handler 路径包含 scheme、host、userinfo 或网络位置
- **THEN** 系统拒绝保存、验证和执行

#### Scenario: 外部服务返回跨 Origin 重定向
- **WHEN** 请求响应要求跳转到不同 scheme、host 或 port
- **THEN** 执行器不得携带认证材料跟随重定向，并将调用归类为非重试安全失败

### Requirement: Connection 明文 HTTP 必须显式授权
外部 API Connection SHALL 默认使用 HTTPS；管理员 MAY 在企业内网、开发、测试或生产 Connection Draft 中显式启用 `allow_plain_http` 以使用 HTTP。系统 MUST 拒绝未显式授权的 HTTP Origin，MUST 将授权纳入内容 hash 和不可变 Connection Revision，并 MUST 在管理界面说明密码、Token 和业务数据可能被窃听或篡改。该授权 MUST NOT 被描述为网络区限制或完整 SSRF 防护。

#### Scenario: 企业内网显式配置 HTTP ONES
- **WHEN** 管理员配置固定 HTTP Origin、显式启用明文 HTTP 并完成验证
- **THEN** 系统允许在生产环境发布和调用该精确 Origin，并保留明文传输警告和不可变授权事实

#### Scenario: HTTP 未显式授权
- **WHEN** 任一环境的 Connection 使用 HTTP 但未启用 `allow_plain_http`
- **THEN** 系统拒绝保存、验证和发布，且不发起登录或业务调用

#### Scenario: HTTPS Connection
- **WHEN** Connection 使用 HTTPS
- **THEN** 系统允许按固定 Origin 规则处理，并将无意义的明文 HTTP 授权规范化为 false

### Requirement: Authentication Profile 固定登录与认证协议
Authentication Profile Revision MUST 定义固定登录相对路径、登录请求字段、Token/User/Team 提取规则和认证 Header 注入规则；系统 MUST 静态校验提取类型并 MUST NOT 将登录动作暴露为 Capability 或模型 Tool。

#### Scenario: 验证合法 ONES 登录协议
- **WHEN** 登录响应包含匹配规则的 User、Team 集合与 Token
- **THEN** 系统返回内部验证结果供绑定或 Connection Verify 使用，不向模型注册登录 Tool

#### Scenario: 登录响应结构不符
- **WHEN** User ID、Team 集合或 Token 缺失或类型错误
- **THEN** 系统判定验证失败，不创建身份、凭据或发布证据

### Requirement: 首个 Connection 可临时使用当前管理员自验证
当系统尚无可供正式绑定的 Published ONES Connection Revision 时，具备 `api_connections.verify` 的当前管理员 SHALL 能在 Connection Verify 请求内临时输入自己的邮箱密码，验证 Draft Origin、登录、字段提取和认证注入；密码和 Token MUST 在请求完成后丢弃，不得创建身份、凭据或运行时回退账号。

#### Scenario: 首连接启动验证成功
- **WHEN** 当前管理员提交有效个人邮箱密码且 Draft 全链验证通过
- **THEN** 系统只保存验证证据与安全摘要，并允许后续发布该 Connection Revision

#### Scenario: 启动验证后直接测试 Capability
- **WHEN** Connection 已发布但管理员尚未通过该 Revision 完成正式自助绑定
- **THEN** 系统拒绝 Capability Test/Verify，并提示完成本人绑定

#### Scenario: 启动验证失败
- **WHEN** 登录、提取或认证注入测试失败
- **THEN** 系统返回安全错误，且数据库、缓存、日志和审计均不保存密码、Token 或原始响应

### Requirement: Connection 失效时运行时失败关闭
Published Connection Revision SHALL 支持禁用和归档；被禁用、无法解析或完整性校验失败的 Connection MUST 阻止依赖它的新外部调用，且不得回退到其他 Origin 或浮动 Revision。

#### Scenario: 禁用当前 Connection Revision
- **WHEN** 某 Capability Release 冻结的 Connection Revision 被禁用
- **THEN** 新调用返回安全配置错误，不尝试其他 Connection

#### Scenario: 新 Connection Revision 已发布
- **WHEN** Connection 发布新 Revision 但既有 Capability Release 未重新发布
- **THEN** 既有 Release 继续冻结旧 Revision，不自动漂移到新版本

### Requirement: 网络调用边界不得被描述为完整 SSRF 防护
系统 MUST 实施固定 Origin、相对路径、HTTP 显式授权、拒绝跨 Origin 重定向、超时和响应大小限制；在完整网络区/CIDR/DNS 出站治理交付前，管理状态和文档 MUST NOT 宣称具备通用 SSRF 防护。

#### Scenario: 管理员查看 Connection 安全状态
- **WHEN** Connection 只具备第一版 Origin 边界
- **THEN** 界面准确显示已实施约束和未覆盖的网络区治理，不显示“完整 SSRF 防护”

