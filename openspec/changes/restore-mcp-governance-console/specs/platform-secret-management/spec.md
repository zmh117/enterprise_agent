## MODIFIED Requirements

### Requirement: Web-managed secrets are encrypted before persistence
系统 SHALL 允许受认证、具备权限的 Web Credential Center 或 `platformctl` 通过管理 API 提交 Secret 明文值，但 MUST 在写入持久化存储前使用仓库外 Master Key 和 AES-256-GCM-AAD 加密。系统 MUST NOT 在 PostgreSQL 明文字段、审计、日志、API 响应、命令输出、浏览器状态、事件或 Agent prompt 中保存明文。

#### Scenario: Admin creates a Credential through Web
- **WHEN** 管理员通过受保护表单提交 Credential 名称、kind 和明文值
- **THEN** 系统在持久化前加密，响应只返回稳定安全标识和元数据，不返回明文、密文或内部 Secret Ref

#### Scenario: Secret value enters an error path
- **WHEN** Secret 创建或轮换请求经过校验、异常处理、审计和日志链路
- **THEN** 所有持久化或输出内容使用固定错误码和脱敏摘要，不得包含原始明文

### Requirement: Secret values are never displayed after save
系统 SHALL 在 Web、CLI 和 API 查询 Secret 时只返回稳定标识、名称、kind、provider、状态、版本、更新时间、用途和非敏感摘要，MUST NOT 提供明文回显、下载、密文、nonce、认证标签、Master Key 或浏览器可复制的内部 Secret Ref。

#### Scenario: Admin lists Credentials
- **WHEN** 管理员打开 Credential 列表
- **THEN** 系统返回安全元数据和用途计数，不返回明文、密文或内部解析引用

#### Scenario: Admin views Credential detail
- **WHEN** 管理员查看某个 Credential 详情
- **THEN** 页面只显示版本、状态、用途和审计摘要，不提供“显示密码”或“复制 Secret Ref”动作

### Requirement: Secret operations are authorized and audited
系统 SHALL 在创建、轮换、停用和用途查询前校验细粒度 Credential 权限。Web 写操作 MUST 校验 Session、CSRF、expected version 和幂等键；CLI MUST 使用受认证管理 API且不得直接写数据库。所有结果 SHALL 记录不含明文的审计。

#### Scenario: Unauthorized user creates secret
- **WHEN** 未授权用户提交 Credential 创建请求
- **THEN** 系统拒绝请求，不保存任何 Secret 值且不通过响应泄露目标是否存在

#### Scenario: Secret rotation audit
- **WHEN** 管理员轮换 Credential
- **THEN** 系统记录 actor、Credential 安全标识、旧版本、新版本、动作和 correlation ID，但不记录明文或内部 Secret Ref

## ADDED Requirements

### Requirement: Web Credential Center 提供安全生命周期管理
系统 SHALL 在 MCP 配置中提供 Credential 列表、详情、创建、轮换、停用和用途查看。页面 MUST 使用安全 DTO，且 MUST NOT 提供 Master Key、Provider 任意配置或 Secret 导出功能。

#### Scenario: 创建 Credential
- **WHEN** 有权限管理员提交名称、受支持 kind 和符合规则的明文
- **THEN** 系统创建加密版本、清空浏览器输入并返回不含敏感材料的成功摘要

#### Scenario: 轮换 Credential
- **WHEN** 管理员为启用 Credential 提交新值和当前 expected version
- **THEN** 系统创建新 active 版本，使新运行解析新版本，并保留旧版本审计而不回显任何值

### Requirement: Resource 表单通过安全 Credential 标识选择
Database、Redis、Loki 和受信 Connector 表单 SHALL 通过有权限的选择器保存 Credential 安全标识，后端 MUST 将其解析为内部 Secret 引用。Resource/Connector DTO MUST NOT 返回明文、密文或可复制内部 Secret Ref。

#### Scenario: 数据库表单选择密码 Credential
- **WHEN** 管理员选择一个 kind 兼容且启用的 Credential 并保存 Resource
- **THEN** Resource 只保存后端内部引用关系，浏览器响应只显示 Credential 名称和状态摘要

#### Scenario: 选择不兼容 Credential
- **WHEN** 客户端为数据库密码字段提交不兼容或已停用 Credential
- **THEN** 后端拒绝保存且不解析或返回 Secret 值

### Requirement: 在用 Credential 不得无保护停用
系统 SHALL 在停用 Credential 前检查启用 Resource、Connector 和活动 Publication 用途，并 MUST 在存在活动依赖时拒绝直接停用或要求先完成明确依赖切换。系统 MUST NOT 自动回退到环境变量、旧版本或空值。

#### Scenario: 停用在用数据库 Credential
- **WHEN** Credential 被启用的 Database Resource 使用
- **THEN** 系统拒绝停用、返回受影响对象安全摘要并保持当前版本有效

#### Scenario: 停用无活动用途 Credential
- **WHEN** Credential 没有任何启用 Resource、Connector 或活动 Publication 用途
- **THEN** 系统停用该 Credential，后续解析 fail-closed 并记录审计

