## ADDED Requirements

### Requirement: Schema 事实源必须登记并可审计
系统 SHALL 在版本控制中维护 schema fact-source manifest，按表及关键列登记领域所有者、事实语义、分类、writer、reader、生命周期、保留/审计要求和退役状态。分类至少 MUST 区分 canonical mutable fact、immutable snapshot、derived projection、compatibility shadow、operational coordination fact 和 one-time migration artifact。

#### Scenario: 新增或修改持久化字段
- **WHEN** migration 新增表、关键列、快照或兼容表示
- **THEN** 同一 change 更新 manifest 并声明唯一事实源、允许的派生关系、所有 writer/reader 和退役条件

#### Scenario: 重复表示具有不同职责
- **WHEN** 两个字段或表包含相似数据但分别承担可变草稿和不可变发布快照职责
- **THEN** manifest 将二者登记为不同生命周期事实
- **AND** consolidation 不得把不可变历史误判为需要消除的双写

### Requirement: Schema consolidation 必须按阶段推进并禁止长期双写
系统 MUST 按 expand、verify/backfill、read cutover、write cutover、observation、contract/drop 的顺序推进事实源收敛，每个阶段 SHALL 具有可重复的前置检查、成功证据、失败关闭行为和回滚边界。兼容双写只能存在于已登记且有截止门禁的迁移窗口。

#### Scenario: 进入读切换阶段
- **WHEN** verify/backfill 尚未证明全量 parity、唯一映射与引用完整性
- **THEN** 系统不得取消旧读路径或进入写切换

#### Scenario: 写切换完成后的观察期
- **WHEN** 新版本已停止兼容列双写
- **THEN** 观察期持续核对缺失事实、旧列访问、队列重试、Runtime 恢复和历史查询
- **AND** 任何回归都会阻止 contract/drop

#### Scenario: 需要回滚写切换
- **WHEN** contract 尚未执行且观察期发现新事实源不可用
- **THEN** 运维方可以回滚应用版本并按已登记边界恢复兼容写入
- **AND** 不删除新事实或重写不可变历史

### Requirement: 字段和表退役必须满足统一门禁
系统 SHALL 仅在目标字段或表已证明零生产 writer、零生产 reader、无未完成事务/重试/恢复职责、达到保留期、完成必要审计导出、具备备份恢复证据且所有 owner 批准后执行 contract/drop。行数为零、名称含 `legacy` 或 `cutover`、以及本地代码搜索无引用均 MUST NOT 单独满足退役门禁。

#### Scenario: 评审一次性 cutover quarantine 表
- **WHEN** `job_dispatch_cutover_quarantine` 被提议退役
- **THEN** 评审必须证明历史 cutover 已结束、所有隔离记录已处置、部署与恢复代码不再读取或写入、保留期已满且审计证据已导出
- **AND** 任一条件不满足时保持表存在并把退役状态标记为 `blocked`

#### Scenario: 评审安全或恢复表
- **WHEN** 身份 challenge、outbox、Runtime ledger、claim 或 event 表被提议退役
- **THEN** 评审必须证明其安全、幂等、重试或恢复职责已被一个明确的新 canonical fact 完整替代并完成所有调用方切换
- **AND** 不得仅因当前零行或低行数批准删除

### Requirement: Consolidation migration 必须以 Baseline 100 adoption 为前置
系统 MUST 在目标数据库已完成精确 `042 → 100` Baseline Adoption、migration ledger 与 baseline checksum 校验通过后，才允许执行本 change 的后续 migration。真实 backfill、cutover 或 contract/drop SHALL 分别获得部署授权和维护窗口，不得由构建、测试、应用启动或 OpenSpec apply 自动执行。

#### Scenario: 目标数据库仍停留在042
- **WHEN** consolidation preflight 发现 migration ledger 的精确 head 仍为 `042`
- **THEN** 系统仅报告应先执行 Baseline 100 Adoption
- **AND** 不写入本 change 的 migration ledger、业务表或兼容字段

#### Scenario: Active change 发生migration编号竞争
- **WHEN** 实施时发现另一个 active change 已占用计划中的 migration 版本
- **THEN** 实施者根据当前 migration catalog 重新分配唯一版本并更新 checksum 与测试
- **AND** 不修改已部署 migration 的内容或身份

#### Scenario: 执行contract drop
- **WHEN** 所有 consolidation 门禁通过并获得明确部署授权与维护窗口
- **THEN** Migrator 在全局互斥和完整事务边界内执行 contract migration
- **AND** 保存不含业务正文或凭据的 migration、备份和验收证据
