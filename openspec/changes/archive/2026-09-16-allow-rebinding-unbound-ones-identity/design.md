## Context

`user_external_identity` 当前以 `(provider, tenant_code, external_subject_id)` 全局唯一，并通过 `status='unbound'` 表示软解绑。ONES 本人解绑会同步清除 Credential 密文，但身份行仍保留原 `user_id`；后续绑定查询包含该历史行，所以任何其他用户都会被判定为冲突。

本次变更只调整 ONES：解绑必须释放当前归属，同时保留历史事实和审计关联。钉钉已解绑身份仍只能由原人员通过受信候选恢复，不得因共享表约束调整而改变语义。生产使用 PostgreSQL，测试与本地运行使用 SQLite，两种数据库必须维持同一约束。

## Goals / Non-Goals

**Goals:**

- 允许 B 在 A 本人解绑后，重新完成 ONES 登录验证并绑定同一 ONES 外部主体。
- 保证同一 ONES 外部主体最多只有一个 `enabled` 或 `disabled` 当前身份。
- 保留 A 的 `unbound` 身份行、原 `user_id`、已清除 Credential 和审计引用。
- 将并发绑定竞争收敛为稳定、安全的身份冲突，不产生双重当前归属。
- 保持 PostgreSQL、SQLite 的顺序迁移结果一致，不追溯改写固定的 v100 baseline。

**Non-Goals:**

- 不允许管理员强制转移 ONES 身份，也不绕过本人登录验证。
- 不让 `disabled` 身份释放当前归属。
- 不改变钉钉身份的永久历史归属与受信候选恢复规则。
- 不改变 ONES API 请求或响应结构，不新增身份 Claim、Connection 或冲突治理界面。

## Decisions

### 1. 将 ONES `unbound` 视为终止的绑定周期

ONES 身份从 `enabled` 或 `disabled` 进入 `unbound` 后，该行继续归属于原内部用户，仅作为历史记录，不再占用当前主体。后续任何用户绑定同一 ONES 主体都创建新的身份行和 Credential；不得改写历史行的 `user_id`，也不得恢复历史 Credential 密文。

选择新建绑定周期而不是转移旧行，是为了保持历史审计、Credential 清除事实和主体归属在时间上的可解释性。代价是同一 ONES subject 可以有多条 `unbound` 历史记录，但查询投影已经区分当前与历史。

### 2. 用两条 provider-aware 部分唯一索引替代全局唯一约束

移除表级 `(provider, tenant_code, external_subject_id)` 唯一约束，改为：

- 非 ONES provider：所有状态继续按该三元组唯一，保持钉钉历史归属规则。
- ONES provider：仅 `status IN ('enabled', 'disabled')` 的行按该三元组唯一。

数据库约束是并发写入的最终仲裁；应用层预检查只用于返回更早、更清晰的冲突。

### 3. ONES 绑定只检查当前归属

仓储在绑定 ONES 时只查询相同三元组的 `enabled` 或 `disabled` 行：

- 当前行属于同一用户时，继续幂等重验并更新受控元数据。
- 当前行属于其他用户时，返回 `identity_conflict`。
- 只有 `unbound` 历史行时，插入新的身份行。

钉钉绑定继续使用包含 `unbound` 的历史查询，不复用 ONES 的当前归属规则。

### 4. 并发唯一冲突映射为安全领域错误

ONES 身份插入仍位于确认 challenge 的数据库事务中。若两个用户并发确认同一主体，部分唯一索引只允许一个事务成功；失败方返回 `identity_conflict`，事务回滚，不留下活动 Credential 或双重当前身份。错误响应不得暴露数据库约束名或其他用户信息。

## Risks / Trade-offs

- [风险] SQLite 不能直接删除表内唯一约束，需要重建 `user_external_identity`。→ 迁移在关闭 SQLite 外键检查并保持引用表目标名的条件下复制全部字段，迁移后执行现有 schema/foreign-key 回归。
- [风险] 新代码先于迁移部署时，旧唯一约束会拒绝合法重绑。→ 部署顺序固定为先执行 migration，再启动新应用；旧应用运行在新 schema 上仍是安全但偏保守的行为。
- [风险] 并发插入可能绕过应用预检查。→ 以数据库部分唯一索引仲裁，并把唯一冲突转换为稳定领域错误。
- [风险] 历史查询出现同一 ONES subject 的多条记录。→ 当前投影只选择非 `unbound` 行，历史投影保留每个绑定周期并按时间展示，不把历史行恢复为当前行。
- [风险] 通用约束调整误放开钉钉转移。→ 非 ONES 的部分唯一索引覆盖全部状态，钉钉仓储与测试保持不变。

## Migration Plan

1. 保持 `100_baseline_v1.sql` 作为不可追溯改写的固定迁移起点。
2. 新增顺序 migration：PostgreSQL 删除原表级唯一约束；SQLite 无损重建 `user_external_identity`；两端创建相同的部分唯一索引。
3. 迁移前已有数据受更严格的旧约束保护，天然满足新约束，无需改写身份、Credential 或审计数据。
4. 部署仓储逻辑和回归测试，验证解绑后跨用户重绑、停用冲突、历史保留及钉钉不回退。
5. 应用回滚可保留扩展后的 schema；旧应用只会恢复为偏保守的冲突行为。若要恢复旧唯一约束，必须先确认不存在同一 ONES subject 的多条历史记录，否则禁止收缩。

## Open Questions

无。
