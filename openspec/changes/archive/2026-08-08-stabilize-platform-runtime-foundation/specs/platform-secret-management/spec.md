## MODIFIED Requirements

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

## ADDED Requirements

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
