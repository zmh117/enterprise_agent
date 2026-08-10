## MODIFIED Requirements

### Requirement: Connector secrets are referenced, not persisted in job payloads
系统 SHALL 让新建和发布的 Connector 只保存由后端解析的加密平台 Credential 引用；MUST NOT 将 Secret、Token、Webhook credential 或可复制内部 Secret Ref 写入 Job、audit、Delivery attempt、浏览器 DTO 或 Resource Revision。`env:`、`vault:`、`kms:` 和未知 Provider MUST 被拒绝。

#### Scenario: Connector uses platform Credential
- **WHEN** Channel adapter 需要认证入口或发送 Delivery
- **THEN** infrastructure 层从 Connector 内部引用解析 Credential，并只记录 Connector ID、Credential 安全标识和 configured 状态

#### Scenario: Audit summary is written
- **WHEN** 系统记录 Connector 相关审计
- **THEN** payload 不包含真实 Token、Secret、密文、内部 Secret Ref 或敏感 URL 参数

#### Scenario: New Connector submits env reference
- **WHEN** 新建或发布 Connector 使用 `env:`、`vault:`、`kms:` 或任意 Secret Ref 字符串
- **THEN** 系统拒绝并要求从有权限的 Credential 选择器选择可用项

### Requirement: DingTalk enterprise App connector uses secret references
系统 SHALL 使用受信 Connector 配置表达钉钉企业 App 的非敏感 Client ID，并 MUST 通过后端内部 Credential 引用解析 Client Secret。真实值不得写入 Job、audit、Delivery attempt、仓库文件或浏览器响应。

#### Scenario: Enterprise connector resolves credentials
- **WHEN** `dingtalk_enterprise_robot` 或 Stream adapter 需要调用钉钉
- **THEN** infrastructure 层解析受治理 Credential，并只在日志和审计中记录 Connector ID 和安全状态

#### Scenario: Enterprise connector is missing credentials
- **WHEN** Connector 未绑定可用 Client Secret Credential
- **THEN** 系统将 Connector 标记为 MISCONFIGURED、停止相应入口和投递，且不发起钉钉网络请求

## ADDED Requirements

### Requirement: 管理端恢复渠道与触发器治理页面
系统 SHALL 在认证管理 Shell 中提供 Channel Connector、Trigger Binding 和 Delivery Binding 的列表、详情、新建、编辑、启用、停用和测试入口，并 MUST 使用真实管理 API、当前 Publication 和审计事实。

#### Scenario: 管理员打开渠道页面
- **WHEN** 当前用户具有渠道读取权限
- **THEN** 页面显示其范围内的受信 Connector、方向、企业归属、发布引用、运行状态和脱敏错误，不使用静态 fixture

#### Scenario: 无管理权限用户提交编辑
- **WHEN** 用户没有渠道管理权限却直接调用 Connector mutation API
- **THEN** 后端拒绝请求且不修改 Connector、Binding 或 Secret

### Requirement: Connector 类型和表单 Schema 由服务端拥有
系统 SHALL 只允许服务端注册的 DingTalk、Grafana、email、generic webhook 和 none 等 Connector/route 类型，并 SHALL 为每种类型返回或固定允许字段、方向和认证策略。浏览器 MUST NOT 定义任意 Connector kind、adapter、脚本或认证协议。

#### Scenario: 新建受支持 Connector
- **WHEN** 管理员选择受信类型、填写允许字段并选择兼容 Credential
- **THEN** 后端按类型 Schema 校验并创建停用或待验证配置

#### Scenario: 客户端提交任意 adapter
- **WHEN** 客户端提交未注册 kind、任意代码、脚本或认证 Header 模板
- **THEN** 系统拒绝整个请求且不得加载动态 adapter

### Requirement: Connector 测试不得改写发布事实
系统 SHALL 提供按 Connector 类型限定的受控连接测试，测试 MUST 使用已保存配置和受治理 Credential，并 MUST 只更新健康事实。测试不得创建 Publication、Agent Job、任意外部目标或隐式启用 Connector。

#### Scenario: 测试钉钉 Connector 成功
- **WHEN** 管理员对已保存钉钉 Connector 执行服务端定义的凭据/连通性测试
- **THEN** 系统更新最近测试时间和安全状态，不返回 Token 且不自动启用

#### Scenario: 客户端在测试中覆盖 endpoint
- **WHEN** 客户端试图在测试请求中提交另一个 endpoint、Connector ID 或 Credential
- **THEN** 系统拒绝覆盖并只使用已保存的受信配置

### Requirement: 渠道写操作使用统一并发与审计
Connector、Trigger 和 Delivery 的创建、编辑、启用、停用和测试 SHALL 要求 Session、CSRF、代码拥有权限、expected revision 和幂等键，并 SHALL 记录不含消息正文和 Secret 的审计。

#### Scenario: 两名管理员同时编辑 Connector
- **WHEN** 后提交者使用过期 expected revision
- **THEN** 系统返回冲突且不覆盖当前配置，页面要求刷新

