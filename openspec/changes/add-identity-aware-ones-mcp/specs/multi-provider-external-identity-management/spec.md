## MODIFIED Requirements

### Requirement: 外部身份管理不得暴露凭据和敏感载荷
系统 MUST 在 API、页面、Prompt、RabbitMQ、日志、审计和错误中排除密码、Session Token、CSRF 值、Provider Token、AppSecret、完整 Webhook URL、Principal JWT、Authorization/Cookie、私钥、密文和 nonce。数据库 MAY 只在专用 credential 表中保存使用平台主密钥加密的 Provider 登录材料与 Token，不得把密码/Token 明文或任何凭据密文复制到 Identity metadata、Claim、Verification Attempt 公开投影或审计。受 `audit:*:read` 和保留期保护的审计 MAY 原样保存邮箱/User ID 及有界 Provider 业务请求/响应，但不得保存 Provider 认证请求/响应原文。

#### Scenario: 查看身份与验证历史
- **WHEN** 用户或管理员查看 Identity、Claim、Verification Attempt 或 credential 状态
- **THEN** 系统只返回 Provider、实例、subject、受控上下文、配置状态、方法、revision 和安全时间
- **AND** 不返回明文、密文、nonce、key ID、Authorization Header 或任何可重放认证材料

#### Scenario: 检查数据库明文
- **WHEN** ONES 本人绑定、查询和 Token 自动刷新完成
- **THEN** 密码与 Token 只存在于 AES-GCM 密文列，且不出现在其它业务表或 JSON metadata；登录邮箱可作为身份事实原样出现在授权审计字段中

## ADDED Requirements

### Requirement: Provider凭据必须与外部身份独立治理
系统 SHALL 为支持运行时调用的外部身份保存一条独立当前 credential，包含 Provider、状态、revision、加密登录材料、加密 Token、验证/刷新时间和安全错误码；身份绑定本身 MUST NOT 自动授予 Agent、Application、MCP Tool 或业务数据权限。

#### Scenario: 用户同时绑定钉钉和ONES
- **WHEN** 同一内部用户具备钉钉身份和 ONES 身份
- **THEN** 只有 ONES 身份可以关联 ONES credential，钉钉身份解析和权限保持独立

#### Scenario: 身份停用
- **WHEN** 外部身份或内部用户被停用
- **THEN** 运行时不得解析或解密其 credential，即使 credential 行仍为 ACTIVE

#### Scenario: 身份软解绑
- **WHEN** 用户软解绑 ONES 身份
- **THEN** 系统把 credential 标记为 UNBOUND 并清除登录和 Token 密文，同时保留不含秘密的审计事实

### Requirement: Provider Adapter必须代码注册并限制能力
统一身份模块 SHALL 使用代码注册的 Provider Adapter 实现验证和 Token 生命周期；客户端、管理员或模型 MUST NOT 创建任意登录 URL、Header、OAuth 模板、脚本或通用认证执行器。

#### Scenario: ONES Adapter执行验证
- **WHEN** 用户发起 ONES 本人绑定
- **THEN** 系统只使用代码固定的 ONES 登录路径、响应 schema、host allowlist、超时和大小限制

#### Scenario: 请求未知Provider
- **WHEN** 客户端请求未注册 Provider 或自定义认证模板
- **THEN** 系统拒绝请求且不执行外部网络访问
