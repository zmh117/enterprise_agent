## REMOVED Requirements

### Requirement: 外部身份与个人 API 凭据分离持久化
**Reason**: 个人 API Credential 仅服务于已退役 API Connection/Capability。
**Migration**: 删除 Credential；保留其它规格拥有的外部身份事实。

### Requirement: ONES 自助验证分为 Challenge 两阶段
**Reason**: ONES 通用 API Capability 登录链删除。
**Migration**: 删除未完成 Challenge，不保存密码或 Token。

### Requirement: Challenge 确认原子保存默认 Team 和凭据
**Reason**: ONES Credential 存储删除。
**Migration**: 不迁移默认 Team/Token 到 MCP。

### Requirement: 切换默认 Team 必须重新验证
**Reason**: ONES Credential/Team 运行时删除。
**Migration**: 无需迁移。

### Requirement: 第一版每个用户只有一个有效 ONES 账号
**Reason**: ONES Capability 身份约束退出本平台。
**Migration**: 通用外部身份历史可保留，但不再构成工具凭据。

### Requirement: 本人和管理员复用外部身份面板
**Reason**: ONES Credential 操作从面板删除。
**Migration**: 面板可继续展示其它外部身份，只移除 API Credential 控件。

### Requirement: 当前身份与历史记录明确分层
**Reason**: 本规格的 ONES Credential 分层退出。
**Migration**: 通用身份历史由身份领域规格继续约束。

### Requirement: ONES 身份与个人凭据精确关联
**Reason**: 个人 API Credential 删除。
**Migration**: 删除关联，不迁移 Token。

### Requirement: 个人凭据操作使用本人权限和受限管理员权限
**Reason**: 个人 API Credential 操作删除。
**Migration**: 移除对应 RBAC 动作。

### Requirement: 解绑和凭据错误具有明确状态
**Reason**: Credential 状态机删除。
**Migration**: 外部身份解绑仍由其它身份规格处理。

### Requirement: 现有 ONES 身份记录非破坏迁移
**Reason**: ONES Capability 专用迁移不再适用。
**Migration**: 保留通用身份审计记录，删除 Credential 密文与 usage。

