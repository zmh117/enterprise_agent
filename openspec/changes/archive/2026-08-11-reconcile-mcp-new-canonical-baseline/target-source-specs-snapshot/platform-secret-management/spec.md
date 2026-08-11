# platform-secret-management Specification

## Purpose
TBD - created by archiving change web-managed-secrets-and-env-config. Update Purpose after archive.
## Requirements
### Requirement: Web-managed secrets are encrypted before persistence
系统 SHALL 允许管理端提交 secret 明文值，但 MUST 在写入持久化存储前加密或转存到 Secret Provider，并且 MUST NOT 在 PostgreSQL 配置表、审计、日志、API 响应或 Agent prompt 中保存明文。

#### Scenario: Admin creates a secret value
- **WHEN** 管理端提交 `code=deepseek_api_key` 和 secret 明文值
- **THEN** 系统加密保存该值，返回稳定 `secret_ref`，且响应不包含明文

#### Scenario: Secret value appears in request logging path
- **WHEN** secret 创建或更新请求经过 API、异常处理、审计和日志链路
- **THEN** 所有持久化或输出内容 MUST 使用脱敏摘要，不得包含原始 secret 明文

### Requirement: Secrets are versioned and rotatable
系统 SHALL 为每个 Web 管理的 secret 保存版本信息，并支持新增版本、设为当前版本、禁用旧版本和审计轮换动作。

#### Scenario: Rotate secret
- **WHEN** 管理端为已有 secret 提交新明文值
- **THEN** 系统创建新版本并将其设为 active，旧版本不再用于运行时解析

#### Scenario: Disable secret
- **WHEN** 管理端禁用 secret 或其 active version
- **THEN** 后续运行时解析该 `secret_ref` MUST 失败为安全配置错误

### Requirement: Secret references resolve through provider abstraction
系统 SHALL 通过统一 SecretResolver 解析 `secret://platform/<code>`；新界面、新资源和新发布 MUST 只允许该 Provider。现有 `env:` 仅允许由显式导入操作读取一次并迁移为加密平台 Secret；`vault:`、`kms:` 必须作为尚未实现的预留 Provider 被拒绝。

#### Scenario: Resolve encrypted database secret
- **WHEN** 运行时解析 `secret://platform/order_db_password`
- **THEN** SecretResolver 从 encrypted DB provider 读取 active 密文版本，并只向 infrastructure 层返回解密值

#### Scenario: Import existing env secret reference
- **WHEN** 授权管理员显式导入仍被旧资源引用的 `env:ORDER_DB_PASSWORD`
- **THEN** 系统读取一次环境值、创建加密平台 Secret、生成 `secret://platform/` 引用并记录不含明文的审计

#### Scenario: New UI attempts env reference
- **WHEN** 新建或发布资源时提交 `env:` 引用
- **THEN** 系统必须拒绝并要求选择凭据中心 Secret

#### Scenario: Reserved provider is selected
- **WHEN** 配置尝试创建或发布 `vault:` 或 `kms:` 引用
- **THEN** 系统必须返回“Provider 尚未实现”，不得声称可用或尝试解析

### Requirement: Secret values are never displayed after save
系统 SHALL 在 Web/API 查询 secret 时只返回配置状态、版本、更新时间、用途和脱敏摘要，MUST NOT 支持明文回显。

#### Scenario: Admin lists secrets
- **WHEN** 管理端查询 secret 列表
- **THEN** 系统返回 secret code、provider、active version、configured 状态和更新时间，不返回明文 secret

#### Scenario: Admin views secret detail
- **WHEN** 管理端查看某个 secret 详情
- **THEN** 系统可返回脱敏摘要如 `sk-****abcd`，但 MUST NOT 返回完整 secret value

### Requirement: Secret operations are authorized and audited
系统 SHALL 在创建、更新、轮换、禁用和解析管理接口前校验平台配置管理权限，并记录不含明文的审计记录。

#### Scenario: Unauthorized user creates secret
- **WHEN** 未授权用户提交 secret 创建请求
- **THEN** 系统拒绝请求，不保存任何 secret 值

#### Scenario: Secret rotation audit
- **WHEN** 管理员轮换 secret
- **THEN** 系统记录 actor、secret code、旧版本、新版本、动作和 correlation id，但不记录明文

### Requirement: Secrets shall be smoke-verifiable through Compose curl
系统 SHALL 允许开发者在 Docker Compose 环境中通过 curl 创建、查询、轮换和禁用 Web-managed secret，并验证返回内容不泄漏明文。

#### Scenario: Compose curl creates DeepSeek secret
- **WHEN** 开发者调用 `POST /api/platform/secrets` 创建 `deepseek_api_key`
- **THEN** API SHALL 返回 `secret://platform/deepseek_api_key` 和脱敏摘要，且响应 MUST 不包含提交的原始 key

#### Scenario: Compose curl disables secret safely
- **WHEN** 开发者调用 `POST /api/platform/secrets/deepseek_api_key/disable`
- **THEN** 后续 runtime 解析该 secret SHALL 失败为安全配置错误，且不得回退到旧版本或空 key

### Requirement: Secret smoke documentation shall protect operator input
系统 SHALL 在 smoke 文档中要求开发者通过环境变量或交互输入提供真实 key，MUST NOT 要求把真实 key 写入命令历史、README、OpenSpec artifact 或 git tracked 文件。

#### Scenario: Real key is supplied for optional smoke
- **WHEN** 开发者执行真实 DeepSeek 可选验证
- **THEN** 文档 SHALL 使用 `DEEPSEEK_API_KEY` 或等价本地环境变量占位，不得展示真实 key

### Requirement: 平台 Secret 必须使用仓库外固定 Master Key
系统 MUST 从仓库外只读文件加载单个稳定 Master Key，并在持久化前加密 Secret；Compose 和代码不得提供硬编码回退，非测试环境缺失 Key 时必须启动失败。

#### Scenario: Master Key 未配置
- **WHEN** 非测试服务需要 Secret 功能但 Master Key 文件缺失或权限不安全
- **THEN** 服务必须拒绝启动或将 Secret 子系统标为不可用，且不得生成临时 Key

#### Scenario: Master Key 正常加载
- **WHEN** 受控文件包含有效 Key
- **THEN** 系统可以解密已保存版本，但健康状态和日志不得输出 Key 或可逆摘要

### Requirement: Master Key 不实行在线周期轮换
本次系统 MUST NOT 实现 Web 管理、多 Key keyring、到期时间或自动周期轮换；仅允许文档化的紧急离线重加密流程。

#### Scenario: 管理员查看凭据中心
- **WHEN** 管理员访问凭据中心
- **THEN** 页面不得提供 Master Key 查看、编辑、轮换或下载功能

### Requirement: 凭据中心必须支持资源表单安全选择
“平台治理 → 凭据中心” SHALL 管理平台 Secret metadata 和版本；DB、Redis、Loki 表单 SHALL 通过授权选择器保存 `secret://platform/<code>`，不得把明文写入 Resource Revision。

#### Scenario: 数据库表单选择密码
- **WHEN** 管理员选择一个可用平台 Secret 并保存 Draft
- **THEN** Resource Draft/Revision 只保存 `password_ref`，API 响应不包含明文或密文

#### Scenario: Secret 被禁用
- **WHEN** 已发布资源引用的 active Secret 被禁用
- **THEN** 相关资源必须重新装载失败或进入 MISCONFIGURED，并保留 Last Known Good 行为
