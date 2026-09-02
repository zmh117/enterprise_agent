## ADDED Requirements

### Requirement: ONES mutation必须绑定准备时的原始外部身份与Team
系统 MUST 在准备 ONES mutation 时由当前 Job 的内部用户服务端解析唯一启用的 ONES 外部身份、当前已验证 Team 与个人 Credential，并把外部身份 ID 和实际目标 Team 作为 Action Intent 执行事实。身份、Team 或 Credential 不得来自 Prompt、Tool 参数、卡片参数或短时 Principal 的自声明业务字段。

#### Scenario: 当前用户具有有效ONES身份
- **WHEN** 已授权的 `ones_update_task` 在当前 Job 中准备更新
- **THEN** ONES MCP 由服务端解析当前内部用户的唯一启用 ONES 身份和当前已验证 Team
- **AND** Intent 只保存外部身份 ID、Team 和无 Secret 的 Credential 引用事实

#### Scenario: Tool参数尝试指定Team或身份
- **WHEN** 调用参数包含 Team、ONES用户、邮箱、Credential、Token 或认证 Header
- **THEN** Tool 在 Provider 网络访问前拒绝

#### Scenario: ONES身份缺失或歧义
- **WHEN** 当前内部用户没有唯一启用的 ONES 外部身份、没有可用 Team 或 Credential 需要重新验证
- **THEN** 系统不创建 Action Intent 并返回稳定中文身份错误

### Requirement: ONES mutation执行前必须重新解析当前Credential并复核原始身份
worker MUST 在每次 ONES Provider 写调用前，以 Action Intent 中的内部用户和原始 ONES 外部身份 ID 重新验证用户状态、外部身份状态、Provider 主体、目标 Team、当前个人 Credential、Job Tool Snapshot 与业务授权。worker SHALL 使用同一外部身份当前有效或受控刷新后的 Credential；不得复用准备阶段短时 Principal、切换到其它身份或从持久化 Intent 读取 Secret。

#### Scenario: 用户确认后解绑ONES身份
- **WHEN** Action Intent 已批准但原始 ONES 外部身份在执行前已解绑或停用
- **THEN** worker 拒绝 ONES 写调用且不回退到用户后来绑定的其它身份

#### Scenario: 用户确认后换绑ONES身份
- **WHEN** 当前内部用户存在新的启用 ONES 身份但其外部身份 ID 与 Intent 不同
- **THEN** worker 拒绝当前 Intent
- **AND** 新身份必须重新发起并确认新的 Action Intent

#### Scenario: Credential常规刷新
- **WHEN** 原始外部身份仍有效且其 Credential 仅发生受控 Token 刷新
- **THEN** worker MAY 使用该同一身份当前有效 Credential 执行
- **AND** 不把 Secret 写入 Intent、卡片或审计

#### Scenario: 目标Team不再属于原始身份
- **WHEN** Intent 保存的 Team 已从原始外部身份的已验证 Team 集合移除
- **THEN** worker 拒绝执行且不得切换到新的默认 Team

#### Scenario: 默认Team变化但目标Team仍有效
- **WHEN** 用户默认 Team 已变化但 Intent 的目标 Team 仍属于原始身份的已验证 Team 集合
- **THEN** worker 继续按 Intent 冻结的目标 Team 复核 Task
- **AND** 不把新默认 Team 静默用于该确认

#### Scenario: Job授权或主体资格被撤销
- **WHEN** 内部用户停用、Job Tool Snapshot 不再匹配或角色/Application 授权在执行前失效
- **THEN** worker 在 ONES Provider 写调用前 fail closed
