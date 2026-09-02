## Why

当前 ONES 本人解绑只把身份标记为 `unbound`，但历史记录仍永久占用 `provider + tenant_code + external_subject_id` 唯一键，导致已完成解绑的 ONES 账号无法由另一内部用户重新验证并绑定。解绑应终止当前归属，同时保留原用户的历史身份与已清除凭据记录。

## What Changes

- 将 ONES `unbound` 定义为释放该外部主体的当前绑定占用；`enabled` 和 `disabled` 仍视为当前归属并阻止其他用户绑定。
- 另一内部用户只有在重新完成受信 ONES 登录验证后，才能为同一外部主体创建新的当前身份与 Credential。
- 保留原用户的 `unbound` 身份、Credential 清除状态和审计关联，不改写历史记录的 `user_id`。
- 以数据库约束和事务逻辑保证同一 ONES 外部主体最多只有一个非 `unbound` 当前身份，并安全处理并发绑定冲突。
- 补充解绑后跨用户重绑、停用不释放、重绑后的反向冲突和历史保留回归测试。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `identity-access`：调整 ONES 外部主体唯一归属与解绑生命周期要求，使唯一性约束只覆盖非 `unbound` 当前身份，同时保留历史事实。

## Impact

- 修改 `identity-access` canonical requirement 的 ONES 解绑与跨用户绑定语义。
- 调整 `user_external_identity` 的数据库唯一约束及升级迁移。
- 调整身份仓储的 ONES 绑定查询与冲突处理；钉钉身份恢复和归属规则不变。
- API 请求与响应结构不变；现有 ONES 登录 challenge、Credential 清除和审计边界继续沿用。
