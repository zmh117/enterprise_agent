## Context

Confirmed-current 的完整 backend 回归为 `1732 passed, 30 skipped, 5 failed`，5 条失败可归并为三个根因：

- `backend/seeds/local_seed.sql` 中默认 Agent Publication 已升级到 Runtime protocol 1.5 和新 config hash，但默认 Webhook Trigger Publication 的 snapshot 与独立 `agent_config_hash` 列仍冻结 protocol 1.4 时的旧 hash。Dispatcher 按既有安全规则失败关闭，三个 Webhook/Channel 测试因此无法创建 Job。
- migration 126 为实现 ONES unbound 后重新绑定而在 SQLite 重建 `user_external_identity`，但没有恢复 baseline 中两个钉钉企业身份唯一索引。PostgreSQL 没有重建表，因此不受这一遗漏影响；SQLite head 129 会错误允许同一内部用户在同一钉钉企业拥有两个当前身份。
- Python Runtime 的 SDK 升级增加了对固定模块 `claude_agent_sdk._cli_version` 的版本读取，架构测试仍精确断言旧的两个导入。该导入不做插件发现或 Runtime 路由，且失败时已有 CLI executable 回退。

Documented-intent 已存在：`identity-access` 要求钉钉企业 + Staff ID 唯一且内部用户 + 企业最多一个当前身份；`agent-model`、`business-application` 和 `channel-conversation` 要求 Publication 引用及 hash 不可变且可验证；`platform-operations` 要求前向 migration、稳定 checksum、SQLite/PostgreSQL 最终 schema 等价和完整回归不得隐藏失败。

## Goals / Non-Goals

**Goals:**

- 用新的前向 migration 恢复当前及既有数据库的钉钉唯一索引，不修改已发布 migration 身份或 checksum。
- 让 fresh seed 中默认 Agent/Webhook Publication 图自洽，并以直接完整性断言防止未来只更新一侧。
- 让 Runtime 架构测试准确允许固定 SDK 兼容导入，同时继续禁止动态插件发现和 Registry。
- 使当前 5 条失败全部通过，并保持完整 backend 测试没有新增失败。

**Non-Goals:**

- 不放宽 Webhook Dispatcher、Agent/Application Publication 或 config hash 的完整性校验。
- 不改写已经持久化的历史 Publication，不自动把历史引用切换到新版本。
- 不合并、猜测或静默修复已经存在的重复钉钉身份。
- 不改变 ONES unbound/rebind 语义、Runtime SDK 选择、Webhook 路由、Tool 集合、Secret 或外部协议。

## Decisions

### 1. 使用 migration 130 恢复索引，不修改 migration 100 或 126

新增唯一版本 `130_restore_dingtalk_identity_indexes.sql`，使用 `CREATE UNIQUE INDEX IF NOT EXISTS` 恢复：

- `dingtalk_enterprise_id + external_subject_id` 的当前钉钉主体唯一性；
- `user_id + dingtalk_enterprise_id` 在 `enabled|disabled` 状态下的当前身份唯一性。

这会在 PostgreSQL 中对仍存在的索引幂等跳过，在 SQLite 中补回表重建时丢失的索引。若 SQLite 已存在冲突数据，唯一索引创建自然失败并使 migration 事务整体回滚；不得自动选取或删除任一身份。

备选方案是编辑 migration 126。该方案会破坏已应用 migration checksum，违反 canonical migration 约束，拒绝。

### 2. 只修复版本控制下的 fresh-seed 快照，不追溯改写运行数据库

将默认 Webhook Trigger Publication snapshot 内的 Agent config hash 和同表的 `agent_config_hash` 更新为同文件中 `agent_publication_default_v1` 的当前 hash，revision 保持 1。Webhook revision config hash 不变，因为派生的 Agent revision/hash 不参与其 revision config canonical hash。

增加直接种子完整性测试，验证默认 Trigger 冻结的 Agent publication ID、revision 和 hash 与被引用的 seeded Agent Publication 一致；现有三条业务链路测试继续验证 Dispatcher 不会绕过完整性检查。

备选方案是在测试 helper 中临时改数据库或让 Dispatcher 接受 hash 漂移。前者掩盖坏种子，后者破坏 fail-closed 安全边界，均拒绝。

### 3. 架构测试使用固定允许列表而不是删除 CLI 版本读取

将合法动态导入集合扩展为 `claude_agent_sdk`、`claude_agent_sdk._cli_version` 和兼容 fallback `claude_code_sdk`，继续要求参数必须是字面量，并继续禁止 entry points、模块扫描和 Runtime Registry。增加 `_cli_version` 不可用时回退到受控 executable 的单元测试。

备选方案是删除版本读取或改为开放前缀匹配。前者丢失运行诊断事实，后者会允许未审查的 SDK 子模块，均拒绝。

## Risks / Trade-offs

- [风险] migration 130 在已有重复身份的 SQLite 数据库失败 → 保留失败关闭，通过只读重复数据查询先行诊断，由操作者另行决定人工治理，不在 migration 内删除数据。
- [风险] 手工更新种子 JSON 再次产生 hash 漂移 → 使用当前 Agent Publication 的确切 hash，并新增跨记录完整性测试；不重新计算或修改无关 Webhook revision hash。
- [风险] 固定私有 SDK 模块在后续版本消失 → 现有代码捕获 `ImportError` 并回退 executable；新增测试冻结该回退，不将私有模块作为唯一可用性条件。
- [权衡] 三个根因属于不同模块 → 统一在一个 baseline-regression change 中处理，因为共同交付门槛是恢复完整 backend 基线，且每项修改独立、边界明确。

## Migration Plan

1. 增加 migration 130 与 fresh/upgrade/duplicate-fail-closed 测试；先在空 SQLite 验证 head 130 和唯一索引，再验证冲突数据阻止升级。
2. 更新 local seed 的默认 Webhook Trigger 派生 Agent hash，并增加种子 Publication 图完整性测试。
3. 更新 Runtime 架构允许列表与 CLI 版本回退测试。
4. 运行原 5 条失败测试、migration/Webhook/Runtime 定向回归、Ruff、Mypy、Compose/OpenSpec 和完整 backend 测试。
5. 部署时先对目标数据库只读检查重复钉钉身份；有冲突则停止并治理，确认无冲突后由 one-shot Migrator 应用 migration 130。

回滚代码时不得删除已创建索引或回退 migration ledger；索引只收紧原本已接受的不变量。种子与测试修改只影响后续 fresh bootstrap 和构建验证。

## Open Questions

无阻塞问题。真实数据库若检测到重复钉钉身份，属于独立的数据治理决策，本 change 不自动处置。
