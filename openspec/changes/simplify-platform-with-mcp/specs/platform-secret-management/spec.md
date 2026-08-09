## MODIFIED Requirements

### Requirement: Web-managed secrets are encrypted before persistence
系统 SHALL 只允许受认证 `platformctl` 通过管理 API 提交 Secret 明文值，且 MUST 在持久化前使用仓库外 Master Key 加密；Web 门户不得提供 Secret 写入口。系统 MUST NOT 在配置表、审计、日志、API 响应、命令输出或 Agent prompt 中保存明文。

#### Scenario: Admin creates a secret value through CLI
- **WHEN** 管理员从 stdin 提交 `code=order_db_password` 和 Secret 明文
- **THEN** 系统加密保存并返回稳定 `secret_ref`，CLI、API 响应和审计均不包含明文

#### Scenario: Secret value enters an error path
- **WHEN** Secret 创建或轮换请求经过异常处理和日志链路
- **THEN** 所有持久化或输出内容使用脱敏摘要，不得包含原始明文

### Requirement: Secrets are versioned and rotatable
系统 SHALL 为每个 CLI 管理的 Secret 保存版本信息，并支持新增版本、原子设为 active、禁用旧版本和审计轮换；当 Resource Ref 不变时，轮换 MUST 刷新运行时 generation 而不得要求重发 Resource Revision。

#### Scenario: Rotate secret
- **WHEN** 管理员通过 CLI 为已有 Secret 提交新明文
- **THEN** 系统创建新版本并原子设为 active，运行时刷新连接且旧版本不再用于新解析

#### Scenario: Disable secret
- **WHEN** 管理员禁用 Secret 或 active version
- **THEN** 后续解析失败为安全配置错误，不回退到旧版本或空值

### Requirement: Secret references resolve through provider abstraction
系统 SHALL 通过统一 SecretResolver 解析 `secret://platform/<code>`；新 CLI、Resource 和 Deployment MUST 只允许该 Provider。`env:`、`vault:`、`kms:` 和未知 Provider MUST 被拒绝，本次不得从旧环境变量或旧平台表导入 Secret。

#### Scenario: Resolve encrypted database secret
- **WHEN** Data MCP 解析 `secret://platform/order_db_password`
- **THEN** SecretResolver 读取 active 密文版本，并只向需要建立连接的基础设施层返回单次解密值

#### Scenario: Manifest attempts env reference
- **WHEN** 新建或发布资源时提交 `env:` 引用
- **THEN** 系统拒绝并要求先通过 CLI 创建平台 Secret

#### Scenario: Reserved provider is selected
- **WHEN** 配置尝试创建或发布 `vault:` 或 `kms:` 引用
- **THEN** 系统返回 Provider 未实现并失败关闭，不声称 Vault 已启用

### Requirement: Secret values are never displayed after save
系统 SHALL 在 CLI/API 查询 Secret 时只返回 code、provider、状态、版本、更新时间、用途和脱敏摘要，MUST NOT 提供明文回显、下载或浏览器可见密文。

#### Scenario: Admin lists secrets
- **WHEN** 管理员执行 `platformctl secret list`
- **THEN** 系统返回安全元数据，不返回明文、密文或 Master Key 信息

#### Scenario: Portal user requests secret endpoint
- **WHEN** 普通用户或轻量门户尝试读取 Secret 详情
- **THEN** API 拒绝请求且不返回 Secret 是否存在之外的可利用信息

### Requirement: Secret operations are authorized and audited
系统 SHALL 在创建、轮换、禁用和 usages 查询前校验细粒度平台配置权限、Session、CSRF 与 expected revision，并记录不含明文的审计；CLI MUST NOT 直接写数据库。

#### Scenario: Unauthorized user creates secret
- **WHEN** 未授权用户提交 Secret 创建请求
- **THEN** 系统拒绝请求，不保存任何 Secret 值

#### Scenario: Secret rotation audit
- **WHEN** 管理员轮换 Secret
- **THEN** 系统记录 actor、code、旧版本、新版本、动作和 correlation ID，但不记录明文

### Requirement: Secrets shall be smoke-verifiable through Compose curl
系统 SHALL 允许开发者在 Docker Compose 环境中通过 `platformctl` 或受认证管理 API 创建、查询、轮换和禁用 Secret，并验证返回、日志、审计和 MCP 调用历史不泄漏明文。

#### Scenario: Compose smoke creates a Secret
- **WHEN** 开发者在测试环境从 stdin 创建测试 Secret
- **THEN** 命令返回 `secret://platform/<code>` 与脱敏摘要，且输出不包含提交值

#### Scenario: Compose smoke disables a Secret
- **WHEN** 开发者禁用被测试 Resource 引用的 active Secret
- **THEN** 后续 Runtime 解析失败为安全配置错误且不得回退

### Requirement: Master Key 不实行在线周期轮换
本次系统 MUST NOT 实现 Web/CLI 在线 Master Key 管理、多 Key keyring、到期时间或自动周期轮换；仅允许文档化的紧急离线重加密流程，且该流程不构成本次旧平台数据备份或迁移。

#### Scenario: 管理员检查 Master Key 操作
- **WHEN** 管理员查看 CLI 命令或轻量门户
- **THEN** 系统不提供 Master Key 查看、编辑、在线轮换或下载功能

## REMOVED Requirements

### Requirement: 凭据中心必须支持资源表单安全选择
**Reason**: 凭据中心与 DB/Redis/Loki Web 表单被移除，资源与 Secret 统一改由 CLI 运维。

**Migration**: 不保留页面；声明式文件只保存 `secret://platform/<code>`，Secret 值通过 CLI stdin 单独创建。
