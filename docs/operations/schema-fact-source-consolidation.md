# Schema 事实源收敛与兼容字段退役

本手册治理 `agent_session`、`agent_job` 与 Workflow 草稿图的分阶段收敛。它本身不授权任何真实数据库写入。代码合并、镜像构建、测试通过、服务启动或 OpenSpec apply 都不构成 Baseline Adoption、回填、切换或 contract/drop 授权；每次写操作仍需明确目标、已验证备份、维护窗口和操作人批准。

## Evidence labels

- `Confirmed-current`: verified in repository code, migration catalog, or tests.
- `Documented-intent`: required by the active OpenSpec change but not yet proven in a deployed environment.
- `Observed-local`: bounded read-only evidence from one local environment.
- `Deployment-gated`: requires separately authorized environment evidence.

## 已冻结的版本边界

| 阶段 | 版本 | 默认行为 |
|---|---:|---|
| Expand | `101` | 放宽影子列、增加 canonical message linkage/约束/索引；不删除旧列 |
| Backfill checkpoint | `102` | 增加内容安全 checkpoint 与独立 contract approval gate |
| Contract/drop | `103` | 文件已冻结在仓库，但默认 migrator 不加载；只有显式 `--include-schema-contract` 才进入 catalog |

默认应用和 migrator 的 deployable head 是 `102`。`103` 不是普通启动迁移，不能在 read/write cutover 观察期自动执行。数据库一旦已合法到达 `103`，普通启动会识别并接受该 head，但不会反向修改 schema。不得重命名、重排或修改任何已应用 migration。

## Repository reader/writer inventory

The machine-readable authority is
`backend/app/shared/schema_fact_sources.json`. The table below explains the
current repository inventory behind its compatibility entries.

| Object | Production writers | Production readers | Tests / CLI / runbooks | Declared external readers |
|---|---|---|---|---|
| `agent_session.dingding_conversation_id`, `dingding_user_id`, `source` | 当前 write-cutover 代码无写入者；read-cutover artifact 仅为回滚保留兼容写入 | 仅 102 阶段的受控 preflight/backfill | migration、回填和契约前 characterization tests | 仓库内未声明；每个目标环境必须另查报表与只读副本 |
| `agent_job.user_id`, `source`, `user_message` | 当前 write-cutover 代码无写入者；read-cutover artifact 仅为回滚保留兼容写入 | 仅 102 阶段的受控 preflight/backfill | migration、回填、debug/retry/result projection tests | 仓库内未声明；直接 SQL/report 仍是 deployment gate |
| `agent_workflow_template.graph_json` | 当前 write-cutover 代码无写入者 | 仅 102 阶段的受控 preflight/backfill | migration、回填和 Workflow characterization tests | 仓库内未声明；导出工具仍须在 contract 前清点 |
| `job_dispatch_cutover_quarantine` | Job dispatch cutover repository | Job dispatch cutover repository/service | `backend/app/cli/job_dispatch_cutover.py`, Job cutover/schema tests, `docs/operations/agent-retry-failure-delivery.md` | Per-environment cutover/audit consumers are not yet signed off; retirement stays `blocked` |

Management APIs are indirect consumers through the Job and Workflow service /
repository projections. They must keep their response contracts by joining the
canonical message and normalized graph facts rather than reading removed
physical columns.

## Retained operational facts

The following are not consolidation targets:

- Webhook, Channel ingress, Job dispatch, and Delivery outbox tables;
- `agent_runtime_event`, terminal ledger, invocation claim, and invocation event;
- ONES identity verification challenge;
- Agent, Business Application, Workflow, and Webhook Trigger publications;
- audit and immutable historical provenance.

Zero rows, low row counts, local static search, or a name containing `legacy`
or `cutover` are never sufficient retirement evidence.

## 固定执行顺序与命令

所有命令均在部署镜像内执行。`MIGRATOR_BUILD`、`TARGET_LABEL` 只能是非敏感 release/commit 和环境标签；证据目录必须是仓库外绝对路径，且不得包含消息正文、Workflow 配置正文、业务 payload、凭据或 Secret。

### 0. Baseline 前置条件

旧数据库必须先使用 baseline-only build 单独完成精确 `042 → 100` adoption，并执行只读 verify。禁止让包含 `101+` 的 build 顺带 adoption。完整步骤见 [Baseline Adoption 手册](schema-baseline-upgrade.md)。若目标不是精确 `100`，停止本流程。

### 1. Expand 到 102

在业务写入停止、备份恢复演练完成且目标已确认后，普通 migration 命令只会应用 `101`、`102`：

```bash
python -m app.cli.migrate --build "$MIGRATOR_BUILD"
```

成功条件是 `head=102`。若输出要求 Baseline Adoption、checksum 不一致或 head 不是 `102`，立即停止。此步不能带 `--include-schema-contract`。

### 2. 只读核对与有界回填

先运行只读 preflight：

```bash
python -m app.cli.schema_consolidation preflight --expected-head 102
python -m app.cli.schema_consolidation backfill-session-job-message \
  --expected-head 102 --limit 100
python -m app.cli.schema_consolidation backfill-workflow \
  --expected-head 102 --limit 100
```

dry-run 不需要也不接受写授权。出现 `session_parity`、`job_parity`、`message_cardinality`、`workflow_parity`、`head_or_checksum_mismatch` 或任何 bounded blocker ID 时停止，不得猜测/复制正文修复。

只有单独批准回填后才能加 `--apply`：

```bash
python -m app.cli.schema_consolidation backfill-session-job-message \
  --apply --expected-head 102 --limit 100 \
  --target-label "$TARGET_LABEL" --confirm-target "$TARGET_LABEL" \
  --evidence-dir "$SCHEMA_EVIDENCE_DIR"

python -m app.cli.schema_consolidation backfill-workflow \
  --apply --expected-head 102 --limit 100 \
  --target-label "$TARGET_LABEL" --confirm-target "$TARGET_LABEL" \
  --evidence-dir "$SCHEMA_EVIDENCE_DIR"
```

回填按稳定 ID 分批，在 `schema_consolidation_checkpoint` 保存高水位；整批冲突或中断会回滚，重复执行从 checkpoint 继续。循环到 `processed_count=0`，再重跑只读 preflight。证据只允许版本、稳定 ID、分类、计数、时间和 SHA-256。

### 3. Read cutover

Read-cutover 镜像必须只从 canonical Session/Job/Message 与 normalized Workflow rows 读取，同时仍保留旧影子写入能力。部署单必须记录该镜像 digest 为 `READ_CUTOVER_IMAGE`。若没有可独立回滚的 read-cutover artifact，不得把 read/write cutover 合并部署。

验证 Job/Channel/Workflow/管理历史 API 均从 canonical facts 投影，且 Publication ID、execution scope、Project、Connector、conversation/requester isolation 没有串会话。失败时回退到 expand-compatible 镜像；旧列仍在。

### 4. Write cutover

当前 consolidation 应用版本是 write-cutover 边界：只写 canonical facts，旧列保留但冻结。部署单记录 `WRITE_CUTOVER_IMAGE`，并确认它与 head `102` 兼容。失败时只能回退到已验证的 `READ_CUTOVER_IMAGE`；该镜像必须优先读 canonical facts，恢复旧影子写入后重新核对 parity。

不得以长期顶层 feature flag 代替两个不可变镜像版本，也不得在本阶段执行 `103`。

### 5. Observation 与 contract approval

至少观察一个完整 retry/recovery retention cycle 和一个生产发布周期，并覆盖所有目标环境。每个目标对象都必须具备：零旧列 reader/writer、消息 cardinality、Workflow 等价、历史只读、未完成 retry/claim 清零、保留期、恢复演练、外部报表/只读副本清单以及 domain、Runtime、database、security/audit、operations 批准。

`job_dispatch_cutover_quarantine` 的仓库决策当前为 `blocked`，所以 `103` 明确保留该表。未来即使获得批准，也必须新增 forward-only migration，不能修改 `103`。

`schema_consolidation_contract_approval` 只能由外部受控 DBA/change-management 工作流写入。本仓库故意不提供“自我批准”命令。该记录仅保存目标标签、expected head、内容安全 evidence/backup reference SHA-256 和已签署 gate，不得保存原始证据或凭据。

### 6. Contract/drop

在新的单独维护窗口停止入口、排空队列和 retry、确认无 active Runtime claim，重新创建并恢复演练备份。只有 approval row 已由授权工作流登记且数据库仍精确为 `102` 时，运行：

```bash
python -m app.cli.migrate --include-schema-contract --build "$MIGRATOR_BUILD"
```

迁移器会在全局 migration lock 下再次检查 predecessor、approval 完整性、Session/Job/message live parity 和 pending retry/recovery；任一失败都会在 DDL 前终止。成功后 head 为 `103`，旧 Session/Job 影子列和 Workflow `graph_json` 不存在，隔离表仍存在。此后禁止部署依赖旧列的镜像。

## 回滚与恢复

- `100` 且未应用 `101+`：按 Baseline 手册允许的 marker-only rollback 边界处理。
- `101/102`、contract 前：schema 不回退；使用已记录的兼容应用镜像回滚，保留旧列并重新核对 canonical parity。禁止删除 ledger 行或逆向 DDL。
- `103` 后：旧镜像不再兼容。只能把维护窗口前已验证的备份恢复到隔离数据库/新卷并切换，或发布经评审的 forward-fix migration。不得修改 `100..103` 的 SQL/checksum，也不得手工重建旧正文事实。

## Stop conditions

出现以下任一情况立即停止并保留内容安全证据：目标/head/confirmation 不匹配；checksum 或 catalog 漂移；零/多个 canonical user message；Workflow 双非空不等价；任何非终态 Job、pending retry/outbox、active claim/recovery；未完成 retention/backup restore；外部 reader/writer 未清点；任一 owner 未批准；证据目录位于仓库内；输出可能包含业务正文或 Secret。

## 2026-08-12 本地验证快照

- `.venv/bin/pytest -q backend/tests`：`702 passed, 27 skipped, 2 subtests passed`；跳过项依赖未提供的 PostgreSQL DSN 或外部运行条件，唯一 warning 为既有 Starlette/httpx deprecation。
- `npm test`（`frontend/`）：12 个 test files、84 项通过。
- `npm run build`（`frontend/`）：TypeScript 与 Vite build 通过；仅有既有的单 chunk 超过 500 kB 提示。
- 退役前快照中的 `npm test`（当时的 `agent-runtime/`）：31 项通过；该结果仅是 2026-08-12 历史证据，不代表 TypeScript Agent Runtime 仍是当前受支持执行路径。
- SQLite 已覆盖默认 fresh head `102`、显式 fresh contract `103`、exact-head/precondition failure、整批回填中断回滚、幂等和 contract 后普通启动。
- PostgreSQL migration/comment integration test 已更新为分别验证默认 `102`（1002 columns）与显式 `103`（995 columns），但本次没有 `MIGRATION_POSTGRES_DSN`，因此仍是 `Deployment-gated`，不能宣称现场通过。
- 本次未启动 Compose、未连接真实数据库、未执行 RabbitMQ 全链路，也未写入任何目标环境。

## 当前状态

- `Confirmed-current`：仓库 migration 文件为 `100..103`；默认 deployable catalog 为 `100..102`，`103` 仅显式加载。代码已切到 canonical reads/writes，manifest 已分类 retained/compatibility/operational/one-time facts，隔离表退役决策为 `blocked`。
- `Observed-local`：SQLite 空库、102 阶段回填、显式 103 contract、失败回滚与相关模块测试；这不是任何真实目标环境的退役证据。
- `Documented-intent`：独立 read-cutover artifact 与 write-cutover artifact 的部署顺序和回滚边界。
- `Deployment-gated`：真实 `042 → 100` adoption、目标数据库 expand/backfill、外部 reader inventory、观察周期、owner approvals、备份恢复、PostgreSQL 现场验证、Runtime/RabbitMQ 全链路和 contract/drop。当前 apply 未执行其中任何写操作。
