## Context

当前 `100_baseline_v1.sql` 精确表达旧 `001..042` 链的最终 schema，但“基线稳定”并不等于“schema 已收敛”。代码仍存在三类重复事实：

1. Session/Job repository 同时写入旧钉钉专用或早期通用字段与新通用字段，读取时仍从新字段回退到旧字段。
2. Job 同时保存 `user_message`，又创建关联的 `agent_message`；Agent context 和查询接口仍直接读取 Job 副本。
3. Workflow template 保存可变 `graph_json`，node/edge API 又独立写规范化表；发布过程把两种表示一起装入 snapshot，存在静默漂移风险。

另一方面，多个相似名称的表并非重复事实。Webhook、Channel ingress、Job dispatch 和 Delivery outbox 分属四个事务边界；Runtime terminal ledger、invocation claim/event 承担幂等、执行所有权和恢复；ONES identity challenge 承担安全验证。它们即使为空或低行数，也不能仅凭代码搜索或行数退役。

2026-08-11 对本地 Compose 数据库的只读聚合检查显示：21 个 Session 与 21 个 Job 的已核对旧/新字段无不一致，21 个 Job 均存在可关联的 user message；Workflow 草稿表为空；各运营表存在从 0 到 31 不等的记录。该结果仅是 `Observed-local` 迁移可行性证据，不替代全量 preflight，也不证明生产可安全 contract。当前本地 migration ledger 仍为精确 `042`，因此真实数据库必须先单独完成 `042 → 100` adoption。

相关方包括 Job/Channel/Workflow 模块维护者、Runtime 维护者、数据库迁移管理员、安全/审计负责人和依赖历史查询的管理端。

## Goals / Non-Goals

**Goals:**

- 为关键表和字段建立可版本化、可审计的事实源与生命周期 manifest。
- 消除 Session/Job 兼容双写与读回退，使新记录只写通用事实。
- 让 `agent_message` 成为消息正文事实，同时保持 Job 查询 API 可通过关联查询返回兼容响应。
- 让规范化 Workflow node/edge 成为唯一可变草稿图，保留不可变 publication snapshot。
- 用一致的阶段和门禁退役兼容列及已证明无职责的一次性表。
- 保持历史 provenance、审计、消息可靠发布、Runtime 恢复和身份安全能力不变。

**Non-Goals:**

- 不合并 Webhook、Channel ingress、Job dispatch 或 Delivery outbox。
- 不删除 Runtime terminal ledger、invocation claim/event、ONES identity challenge、publication/history/audit 表。
- 不重新设计身份、RBAC、Capability、Tool、MCP 或业务应用模型。
- 不把 `project_code` 等仍承担隔离/执行边界的字段仅因跨表重复而删除；有意的不可变快照必须显式登记后保留。
- 不在生成或 apply 本 OpenSpec 时执行真实 baseline adoption、backfill、cutover 或 drop。
- 不修改 `add-identity-aware-ones-mcp` 等其他 active change；migration 版本在实施时按实时 catalog 分配。

## Decisions

### 1. 先建立事实源 manifest，再允许 schema contract

新增版本控制内的 manifest，至少包含：对象/列、领域 owner、语义、分类、canonical source、派生来源、writer、reader、保留/审计要求、迁移阶段、退役 gate 和证据引用。实现形式优先选择仓库内可机器校验的结构化文件，并由测试检查它与 migration/schema catalog 的关键对象一致。

分类固定为：

- `canonical_mutable_fact`：唯一可变业务事实。
- `immutable_snapshot`：发布或执行时冻结、用于重放与追溯的有意冗余。
- `derived_projection`：可从 canonical fact 重建，不得反向覆盖事实源。
- `compatibility_shadow`：限时迁移副本，必须有截止阶段。
- `operational_coordination_fact`：Outbox、claim、ledger、幂等和恢复状态。
- `one_time_migration_artifact`：只服务一次性 cutover，满足门禁后才可退役。

选择 manifest 而不是仅写 migration 注释，是因为退役判断跨代码 reader/writer、运行协议、保留期和审计，无法只靠 DDL 表达。替代方案“发现重复就直接删”无法区分快照和双写，拒绝采用。

### 2. Session/Job/Message 按领域职责收敛

目标映射如下：

| 对象 | 最终事实 | 兼容/派生处理 |
|---|---|---|
| Session | `source_channel`、`source_connector_id`、`external_conversation_id`、`requester_id`、session key/type、Project、Application ID/Publication、execution scope、路由与摘要游标 | `dingding_conversation_id`、`dingding_user_id`、`source` 归类为 compatibility shadow，分阶段退出 |
| Job | Session 引用、幂等键、Project、通用来源/requester、固定 Agent/Application provenance、执行快照、状态/重试/结果 | `user_id`、`source` 归类为 compatibility shadow；Project 和固定 provenance 作为执行事实保留 |
| Message | Session/Job 引用、role、sequence、sender、类型、正文及安全元数据 | `agent_job.user_message` 归类为 compatibility shadow；API 通过关联 user message 保持响应语义 |

`create_agent_job` 的事务边界保持不变：解析/创建 Session、插入唯一有序 user message、创建 Job 和 Job dispatch outbox 必须原子完成。为避免 Job 与 Message 的循环外键问题，Job 可以先生成稳定 ID，再以同一事务插入相互可解析的记录；若 schema 需要显式 `input_message_id`，它必须唯一引用 role=`user` 的消息，并有完整性检查。

读取切换先改变 domain model/repository/context builder/API assembler，从通用字段和关联 message 读取；写切换随后停止旧列赋值。不会在同一发布里同时停止旧读和删除旧列。

替代方案“保留 Job 消息副本以避免 join”会继续制造正文漂移和数据删除困难；当前规模和查询路径不支持为此承担长期双写。若未来需要性能投影，应建立明确的 derived projection，而不是恢复可写副本。

### 3. Application Publication 参与 Session 隔离

同一稳定 Business Application 切换 Publication 后创建新 Session，不复用旧 Publication 的消息与摘要。该决定消除现有 canonical 规范中“Publication 可复用旧 Session”与执行侧“Session 固定 Publication”的冲突，并与当前 schema 已存在的 `application_publication_id`、`execution_scope_hash` 和 `history_read_only` 一致。

旧 Session 不迁移到新 Publication，也不按当前 Deployment 回填，只保持历史只读。替代方案“仅按 Application ID 复用”会让新工具/权限/指令版本读取旧上下文，扩大越权和不可复现风险。

### 4. Workflow 使用规范化草稿和不可变发布快照

`agent_workflow_node`/`agent_workflow_edge` 是唯一可变草稿图；template 只保存编码、名称、状态、revision、入口、schema version 和设置。发布在一个一致读取/锁定 revision 内按稳定排序组装 graph，校验后生成不可变 snapshot/hash。

迁移期对 `graph_json` 只做确定性解析和 parity 检查：

- 两者等价：记录验证通过，切换读取并停止写入 `graph_json`。
- 仅 `graph_json` 有有效草稿：在显式 backfill 阶段解析到规范化 rows，校验后再切换。
- 两者非空但不等价：失败关闭，人工选择前不得覆盖。
- 两者均空：保留空草稿语义。

观察期通过后删除 `graph_json`。不可变 `agent_workflow_publication.graph_snapshot_json` 永久保留，不能被视为双写。替代方案“以 graph_json 为事实、node/edge 为投影”不符合现有节点/边独立编辑 API，且更难施加关系约束。

### 5. 运营事实默认保留，一次性 artifact 条件退役

以下对象在本 change 中登记但不退役：

- `webhook_outbox`、`channel_ingress_outbox`、`job_dispatch_outbox`、`delivery_outbox`；
- `agent_runtime_terminal_ledger`、`agent_runtime_invocation_claim`、`agent_runtime_invocation_event`；
- `ones_identity_verification_challenge`；
- Agent/Business Application/Workflow publication、历史、审计和 delivery attempt 类事实。

`job_dispatch_cutover_quarantine` 作为首个 `one_time_migration_artifact` 候选，但 drop 是条件结果，不是本 change 的预设结果。只有所有环境都完成旧 cutover、记录已处置、代码和运维脚本无读写、保留期满足、审计导出与恢复证据完成并获得 owner 批准后，才能纳入 contract migration；否则 manifest 保持 `blocked`。

### 6. 使用六阶段迁移，避免长期双写

1. **Expand**：加入 manifest、必要约束/索引/关联字段和安全 preflight；保持旧应用兼容。
2. **Verify/Backfill**：在事务批次内核对/补齐通用事实、message 关联和 Workflow normalized graph；只输出 ID/分类/计数，不输出正文。
3. **Read cutover**：应用仅从 canonical facts 读取，保留旧写以支持快速应用回滚。
4. **Write cutover**：停止 compatibility shadow 写入；旧列仍存在但冻结。
5. **Observation**：覆盖至少一个完整重试/恢复保留周期和一个生产发布周期，收集旧列零访问、parity、历史查询、队列与 Runtime 恢复证据。
6. **Contract/Drop**：单独 migration 删除已通过 gate 的列/表，随后验证全链路和恢复。

每个阶段必须可单独部署。读写切换使用明确、短期、默认 fail-closed 的兼容阶段配置或版本边界，但不得新增长期顶层 feature flag。contract 完成后不支持降级到仍依赖旧列的应用版本。

替代方案“一次 migration 内 backfill + 切换 + drop”回滚面过大，也无法观察隐藏 reader，拒绝采用。

### 7. Baseline 与 deployment authority 分离

本 change 的 migration 不硬编码为 `101`。实施开始时读取 immutable migration catalog，为 expand/backfill/contract 分配未占用版本并冻结 checksum。任何目标数据库必须先通过 `100` adoption 检查；精确 `042` 只能报告 ready-for-adoption，不得顺带采用或执行 consolidation。

代码合并、镜像构建、单元测试、OpenSpec apply 和服务启动都不构成真实数据库写授权。每次真实 adoption、backfill、cutover 与 contract/drop 都需要明确目标、备份位置、维护窗口和批准记录。

### 8. 验证以静态、迁移和运行链路三层证据组成

- 静态：禁止 compatibility 列出现在生产 SQL/domain 输入、Workflow `graph_json` 出现在草稿读写、以及未登记持久化对象。
- 迁移：空库、精确 baseline、代表性历史快照、失败回滚、checksum 和并发锁测试。
- 运行：Session 连续上下文隔离、Job 创建/重试、消息查询、四段 Outbox、Runtime claim/recovery、Delivery、历史只读与 Workflow 发布回归。

验收报告必须区分 `Confirmed-current`、`Documented-intent` 与 `Observed-local`，不把本地零行或静态搜索当作生产退役证据。

## Risks / Trade-offs

- [隐藏 SQL、报表或旧镜像仍读取兼容列] → manifest 全量 reader inventory、read-cutover 遥测、至少一个发布周期观察，并在 contract 前验证部署清单。
- [Job 消息关联不唯一或顺序异常] → backfill 使用稳定规则和唯一约束，任何 0/多候选记录进入阻塞清单，不自动猜测正文。
- [Workflow 两套草稿已漂移] → 双非空不一致时失败关闭，保存安全差异摘要，要求 owner 选择来源后重新校验。
- [停止双写后需要应用回滚] → contract 前保留旧列并允许短期兼容版本恢复写入；contract 后只支持 forward fix 或数据库恢复，不运行旧镜像。
- [误删低流量安全/恢复表] → 分类默认 `operational_coordination_fact`，必须证明职责替代而非仅证明零行。
- [另一个 active change 占用 migration 版本或修改相邻 schema] → apply 时重读 catalog 和 git diff，分配新版本并重新生成 checksum，不修改已部署 migration。
- [大表 backfill 锁竞争或放大日志] → 分批、可恢复、高水位 checkpoint、限速和维护窗口；正文不进入进度日志。
- [更严格 Publication 会话隔离增加 Session 数量] → 接受存储成本，换取权限/上下文边界清晰；通过索引和历史归档治理规模。

## Migration Plan

1. 完成并部署 `042 → 100` Baseline Adoption；验证 ledger、checksum、备份和恢复，不执行本 change 数据写入。
2. 建立 schema fact-source manifest、reader/writer inventory、静态检查和安全 preflight；为 migration 分配未占用版本。
3. 部署 expand migration 与兼容应用，加入必要关联/约束但不删除旧对象。
4. 在单独授权窗口运行只读 parity，然后运行可重入 backfill；异常记录只保留标识、类型和计数。
5. 部署 read-cutover 应用并验证 API、Worker、Channel、Workflow、Outbox、Runtime recovery 与历史读取。
6. 部署 write-cutover 应用，停止兼容双写，进入明确观察期。
7. 对每个列/表逐项签署 retirement gate；未通过者留在 schema，不阻塞其他已独立通过对象。
8. 在单独维护窗口备份并执行 contract migration；重建服务镜像，运行 schema、迁移和真实链路验收。
9. 归档不含敏感内容的证据，更新 manifest 为 `retired`，随后才能归档本 OpenSpec change。

contract 前回滚以应用版本回退和兼容列仍存在为主；contract 后回滚必须使用已验证备份恢复或 forward migration，禁止手工重建旧事实或修改 immutable migration。

## Open Questions

没有阻塞 proposal 的产品决策。实施阶段仍须在 contract 前由 owner 确认：

- 各生产环境一个完整“重试/恢复保留周期”的具体时长及最低观察窗口；
- 是否存在仓库外报表或只读副本直接查询目标兼容列；
- `job_dispatch_cutover_quarantine` 的法定/审计保留期与导出责任方；
- 历史 Job 若存在 0 个或多个候选 user message 时的业务展示文案，但不得自动选择或复制正文。
