## Context

本 change 处理两个相互制约但不应混写为同一状态机的问题。

- `Canonical baseline`：`2026-08-11-establish-schema-baseline-and-organize-docs` 已完成语义同步并归档；baseline `100`、精确 legacy `042` adoption、失败关闭和 adoption-only rollback 已进入 canonical `platform-operations`。
- `Confirmed-current`：当前工作区的 Migrator 和 SchemaHeadValidator 已实现 baseline generation；2026-08-11 的只读 Compose 检查显示运行库仍为 legacy `042`、没有 adoption marker，当前 validator 会拒绝该 ledger 形态。
- `Confirmed-current`：`RuntimeConfigRegistry.ensure_builtin_definitions()` 在服务初始化时逐项调用 repository upsert，definition 列表 GET 也会调用同步；repository 对所有既有记录无条件 UPDATE 并递增 revision。运行库仅 72 条 definition，但 PostgreSQL 累计统计已经记录 14,055 次更新。
- 当前 runtime snapshot 使用 definition、value 和 Secret 的最大单行 revision 作为聚合 revision；高 revision definition 会掩盖较低 revision value 的后续真实更新，内容 hash 才能部分补足该缺陷。
- `Apply preflight 2026-08-11`：工作区活动 migration catalog 只有 `100_baseline_v1.sql`，对应提交晚于当前 Compose 容器创建时间；运行中旧 migrator 日志为 `head=042 baselined=0`，数据库 ledger 精确包含 `001`–`042` 且 `schema_baseline_adoption` 不存在。因此待部署状态是“代码要求 baseline `100`、现有运行库等待受控 adoption”，容器 healthy 不代表已完成该接轨。

约束包括 SQLite/PostgreSQL 双方言、one-shot Migrator 写 schema、业务服务 schema fail-closed、配置读取不得泄漏 Secret，以及现有脏工作区中其他 active change 的文件不得被修改。

## Goals / Non-Goals

**Goals:**

- 在下一次使用当前代码部署前，为现有精确 `042` 数据库形成可执行、可恢复、可审计的 baseline adoption 验收路径。
- 让内置 definition reconciliation 只有在语义变化时写库，并对并发启动保持确定性。
- 从 GET、snapshot 和 ready 等只读路径移除隐式 definition 写入。
- 让聚合 revision/hash 对真实配置变化敏感、对 no-op 和纯读取稳定。
- 用 SQLite 快速回归与 PostgreSQL 集成证据覆盖迁移、并发和数据库写入行为。

**Non-Goals:**

- 不重新设计 baseline `100`、legacy manifest、adoption metadata 或 rollback 状态机。
- 不在本 change 中停止 Agent Session/Job 旧字段双写，不治理 Workflow `graph_json`，也不删除任何业务表。
- 不合并 Outbox，不删除 Agent Runtime 恢复表或 ONES challenge 表。
- 不把本地 Compose 数据库自动迁移作为普通实现或测试步骤；真实 adoption 需要操作人单独授权。
- 不重置现有 definition 的历史 revision，也不伪造审计来掩盖既有空转更新。

## Decisions

### 1. 以已归档的 baseline Requirement 为实施前置

本 change 的 delta 只增加部署验收与 runtime config 稳定性，不复制 predecessor 的 baseline generation Requirement。前置 change 已同步并归档；apply 时仍须确认 canonical specs 保留其最终 Requirement，并对标题与语义重新对账，不满足时停止实施。

替代方案是在本 change 重复 ADDED baseline Requirement，但两个 active delta 会形成并行事实源，归档顺序也可能产生标题漂移或重复 Requirement，因此拒绝。

### 2. Baseline rollout 使用现有状态机，真实数据库操作与代码实施分离

实现只补齐可重复的 preflight、Runbook 和验收入口，复用现有 one-shot Migrator、SchemaHeadValidator、legacy manifest 与受控 rollback CLI。preflight 只输出 ledger/head、checksum/fingerprint、计数/digest、构建身份和备份位置摘要，不读取或打印业务行、Secret 或连接凭据。

实际顺序固定为：停止业务写入 → 创建并核验逻辑备份 → 使用将要部署的 migrator 镜像执行 preflight/adoption → 验证唯一 marker/metadata、数据计数和配置摘要 → 启动业务服务 → 验证 ready 与最小业务闭环。任何失败均保留旧镜像、旧卷和备份。

替代方案是手工插入 baseline marker，无法证明 schema、注释和保留数据等价，也绕过了事务与 immutable manifest 校验，因此禁止。

### 3. Definition 对账返回显式变化结果

repository 对目标 definition 先做规范化：JSON 对象按 key 稳定序列化，适用服务按去重排序后的集合比较，布尔与枚举使用验证后的规范值，描述统一换行但保留有意义文本。对账返回 `created`、`updated` 或 `unchanged` 以及实体；`unchanged` 分支不执行 UPDATE。

更新使用当前 revision 作为乐观并发条件；冲突时有界重读并重新比较。创建依赖 key 唯一约束，插入竞争失败后重读：若语义一致则返回 `unchanged`，不一致则进入同一有界更新流程。registry 汇总 created/updated/unchanged 数量，只有真实变化才能推动聚合版本。

替代方案仅在 Python 中先比较再无条件 UPDATE，仍有并发竞态；数据库触发器虽可拦截 no-op，但会把领域规范化与审计语义隐藏在双数据库 DDL 中，因此拒绝。

### 4. 读取和注册使用不同入口

服务进程初始化可在 schema head 验证之后、构建第一个 snapshot 之前执行一次受控 reconciliation；显式管理同步继续要求管理员权限并在真实变化时记录摘要审计。definition 列表 GET、snapshot builder 和 ready diagnostics 只读现有事实，不再调用 ensure/sync。

若只读路径发现缺失 definition，它返回稳定的 degraded 诊断并指向受控初始化或管理同步，不在读取事务中修复。这样既保留代码内置 definitions 的发布方式，也避免流量触发写入。

替代方案是只修复 no-op UPDATE、继续允许 GET 执行 upsert；虽然能减少物理写入，但读取仍拥有隐式创建权限，故拒绝。

### 5. 聚合 revision 使用可变化的聚合值，hash 保持内容身份

当前 `max(revision)` 会被历史上虚高的 definition revision 长期遮蔽。第一阶段改为聚合所有受支持实体的单行 revision，使任一既有行递增或新行创建都改变聚合值；受支持的生命周期继续以禁用/归档代替物理删除。snapshot 的脱敏内容 hash 继续作为内容身份，两个标识都不得包含 Secret 明文。

现有高 revision 不做破坏性归零；切换后聚合 revision 的具体数值会变化，因此 API/调用方只可把它当作不透明令牌。若未来引入 runtime config 实体物理删除，必须在新增删除能力时改为专用单调 generation，而不能让聚合 revision 倒退。

替代方案是新增 singleton generation 表与 migration `101`，全局单调性更强，但本 change 没有删除语义且首先需要安全完成 baseline adoption；现阶段增加状态表会扩大迁移面，故暂不采用。

### 6. 验证以“不发生写入”和“真实变化可见”为核心

SQLite 测试覆盖规范化、created/updated/unchanged、GET/snapshot 零写入和 revision/hash 稳定；PostgreSQL 集成测试覆盖条件更新、唯一键竞争、重复服务初始化和 `042 -> 100` adoption 数据保留。测试通过前后比较 definition 行 revision/`updated_at`、配置审计数量和聚合版本，不只断言 API 响应。

## Risks / Trade-offs

- [后续 canonical change 导致 baseline Requirement 标题或语义漂移] → apply 的第一项门禁重新检查 canonical 对齐；未对齐即停止，不从 archive 复制 delta。
- [并发 reconciliation 重复递增 revision] → 唯一 key、expected revision 条件更新、有界重读和 PostgreSQL 并发测试共同约束。
- [规范化规则误把顺序变化当作内容变化] → 仅对语义为集合的 service names 排序去重；默认 JSON 保持类型并稳定序列化，测试覆盖嵌套值。
- [聚合 revision 算法切换导致数值跳变] → 将 revision 文档化为不透明令牌，以 hash 证明内容；不重置历史行。
- [Adoption 期间仍有业务写入] → Runbook 要求先停止写入服务，并在备份、adoption 和计数核验期间保持闸门关闭。
- [验证命令泄漏业务数据或凭据] → 只输出计数、digest、版本和脱敏错误；日志测试禁止 DSN、Secret、Token 和原始消息。

## Migration Plan

1. 确认已归档 predecessor 的 baseline `100` 与精确 `042` adoption Requirement 仍完整存在于 canonical，并严格验证本 change。
2. 先以测试驱动方式实现 definition 规范化与显式 reconciliation result，再增加条件更新和并发重试。
3. 移除 definition GET、snapshot 与 ready 的隐式同步；保留 schema 校验后的受控进程初始化和显式管理同步。
4. 修正聚合 revision 计算与调用方契约，增加 no-op、真实更新、低 revision value 更新和 hash 稳定回归。
5. 完成 SQLite、PostgreSQL、API 权限、日志脱敏和 OpenSpec 严格验证；构建受影响服务镜像。
6. 编写并在 disposable PostgreSQL 副本演练 legacy `042` preflight、备份、adoption、验收和 adoption-only rollback。
7. 真实 Compose adoption 另行获得操作授权后执行；成功验收前不删除旧镜像、旧卷或逻辑备份。

回滚代码时恢复旧应用镜像，但不回退已经正确提交的 runtime config definition 内容。数据库若只完成 adoption 且未执行后续 migration，可用既有受控 rollback CLI；否则恢复逻辑备份和旧镜像。

## Open Questions

无。真实 Compose adoption 的执行时间与停机窗口属于部署授权，不在本提案中预先假定。
