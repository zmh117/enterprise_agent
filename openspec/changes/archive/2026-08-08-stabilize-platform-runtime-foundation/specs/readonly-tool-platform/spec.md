## MODIFIED Requirements

### Requirement: Tool platform resolves secrets only in infrastructure layer
系统 SHALL 仅在 Internal API Platform infrastructure adapter 建立 DB、Redis、Loki 外部连接时解析 `secret://platform/<code>`。Agent、模型、Tool Service、Job、Resource Revision、审计和响应 MUST NOT 接收或保存原始 Secret。

#### Scenario: Database tool uses platform secret ref
- **WHEN** 已发布数据库 revision 的 `password_ref` 为 `secret://platform/order_db_password`
- **THEN** infrastructure adapter 在创建受限连接前解析该 Secret，其他层只看见 reference 和 configured 状态

#### Scenario: Secret value appears in tool result
- **WHEN** 上游结果或异常意外包含 credential
- **THEN** 平台必须在返回、持久化或发送给模型前脱敏

#### Scenario: Unsupported provider reference appears
- **WHEN** 运行时快照包含新的 `env:`、`vault:` 或 `kms:` 引用
- **THEN** 快照装载必须失败并保留 Last Known Good，不得尝试回退解析

## ADDED Requirements

### Requirement: 工具平台只能解析 Job 固化的已发布资源
每次工具调用 MUST 从服务端 Job 事实取得 Handler、Resource Revision 和 Execution Scope，且只能访问已安装、已发布、已绑定、已授权并有效装载的交集。

#### Scenario: 请求直接提交另一个 Resource ID
- **WHEN** Agent 或 HTTP Header 指定未绑定到该 Job 的资源
- **THEN** 平台必须拒绝且不打开连接

### Requirement: 数据库工具必须使用可验证只读账户和结构化 SQL 策略
已发布数据库 revision MUST 通过只读账户权限验证；查询 MUST 经 SQL AST 验证为单条 `SELECT` 或只读 `WITH`，并受 timeout、行数和字节数限制。

#### Scenario: 账户权限无法确定
- **WHEN** 数据库连接成功但验证器无法证明账号不具备写权限
- **THEN** Resource Draft 不得进入 VERIFIED 或 PUBLISHED

#### Scenario: 查询包含 PL/SQL 或存储过程
- **WHEN** 工具请求提交匿名块、CALL、EXEC 或多语句
- **THEN** 平台必须在执行前拒绝

### Requirement: Redis 和 Loki 必须使用发布 binding 的范围边界
Redis key prefix、Loki tenant/label selector 和查询上限 MUST 来自 Job 固化的 Published Resource Revision 与 Execution Scope，调用参数不得扩大范围。

#### Scenario: Redis 请求越过车间前缀
- **WHEN** 工具参数请求不属于当前 workshop 的 key
- **THEN** 平台必须拒绝并记录安全摘要

#### Scenario: Loki payload 覆盖 tenant
- **WHEN** 调用参数提交不同 tenant 或移除强制 label
- **THEN** 平台必须忽略或拒绝该扩大范围的值
