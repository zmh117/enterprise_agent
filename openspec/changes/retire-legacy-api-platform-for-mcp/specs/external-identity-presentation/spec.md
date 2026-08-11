## MODIFIED Requirements

### Requirement: ONES 身份与凭据状态分别治理
ONES 身份页面 MUST 只治理身份绑定状态；用于旧 API Capability 的个人业务调用凭据状态、Revision、最近调用事实和错误码 MUST 删除，且身份不得因 Credential 不存在而显示为不可用。

#### Scenario: 身份已启用且没有个人业务调用凭据
- **WHEN** 当前 ONES 身份已启用并具有已验证 Team
- **THEN** 本人摘要显示身份已绑定，不提示缺少 Credential 或要求为业务调用重新验证

### Requirement: ONES 默认摘要只展示业务字段
ONES 本人与治理摘要 SHALL 展示用户名称、身份状态、默认 Team、最近验证和适用操作；MUST NOT 展示 API Connection、个人 Credential、MCP 状态或调用错误。

#### Scenario: ONES 身份已绑定
- **WHEN** 页面加载具有默认 Team 的当前身份
- **THEN** 默认卡展示身份与 Team 事实，不展示 Connection/Credential Revision

### Requirement: ONES 账户详情按本人和管理员划分
系统 SHALL 允许本人展开自己的 ONES User ID 和全部已验证 Team；管理员治理详情 SHALL 只展示身份记录 ID、Revision、状态和验证时间，MUST NOT 显示邮箱密码表单、API Connection、个人 Credential 或代用户重新验证入口。

#### Scenario: 管理员展开 ONES 技术详情
- **WHEN** 具备身份治理权限的管理员查看他人 ONES 身份
- **THEN** 系统只返回允许的身份元数据和审计事实

## REMOVED Requirements

### Requirement: ONES 凭据记录真实使用事实
**Reason**: 用于旧 API Capability 的个人业务调用凭据和调用链永久退役。
**Migration**: 身份仅保留验证时间；未来 ONES MCP 的调用事实由独立工具规格定义。
