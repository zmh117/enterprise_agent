# TypeScript Agent Runtime 分阶段退役

本文只描述部署与回滚门禁。历史 `typescript-v1` Definition、Publication、终态 Job、Runtime Event 和审计不会被改写或删除，数据库 CHECK/枚举继续允许读取该值。

## 阶段 1：部署冻结版本

先部署仍能读取历史 TypeScript 事实、但拒绝创建 TypeScript Agent、草稿、Publication、Application revision、回滚、激活和新 Job 的版本。此时暂不停止旧 Runtime，让已经存在的非终态 Job 按原快照完成、取消或进入确定终态。

每个目标环境分别执行只读预检，且 `--expected-environment` 必须列出此次退役涉及的全部环境：

```bash
.venv/bin/python -m app.cli.typescript_runtime_retirement preflight \
  --target-environment <environment> \
  --expected-environment <environment-a> \
  --expected-environment <environment-b>
```

报告只包含 checkout、环境名、标识、计数、状态和配置键名。数据库、RabbitMQ 或目标环境覆盖不可验证时失败关闭；不得用本地零计数替代其它环境证据。

## 阶段 2：显式迁移活动应用

每次只迁移一个精确 deployment。操作员必须提供旧 Application Publication、旧 TypeScript Agent Publication、目标 Python Agent Publication、Application revision 和 deployment revision。命令不会猜测替代 Agent、复制 Secret 或修改旧快照。

先运行默认 dry-run：

```bash
.venv/bin/python -m app.cli.typescript_runtime_retirement migrate \
  --target-environment <environment> \
  --source-application-publication-id <exact-id> \
  --source-agent-publication-id <exact-id> \
  --target-python-agent-publication-id <exact-id> \
  --expected-application-revision <revision> \
  --expected-deployment-revision <revision> \
  --actor-id <operator-principal> \
  --correlation-id <change-correlation>
```

dry-run 走与 apply 相同的 revision、hash、MCP Tool、文件策略、权限和 Python Runtime readiness 校验，然后回滚整个事务。报告为 `ready` 后，使用完全相同的参数增加显式确认：

```bash
.venv/bin/python -m app.cli.typescript_runtime_retirement migrate \
  --target-environment <environment> \
  --source-application-publication-id <exact-id> \
  --source-agent-publication-id <exact-id> \
  --target-python-agent-publication-id <exact-id> \
  --expected-application-revision <revision> \
  --expected-deployment-revision <revision> \
  --actor-id <operator-principal> \
  --correlation-id <change-correlation> \
  --apply --confirm-target <environment>
```

apply 在一个数据库事务中创建新的 Application revision/publication 并显式激活；任一步失败都会回滚新事实。审计只记录旧新 ID、revision/hash、actor、correlation、环境和结果，不记录配置正文、Prompt、Secret 或业务消息。

## 阶段 3：排空与删除门禁

逐环境重新运行 preflight，并同时保存以下证据：

- active TypeScript Application deployment 为零；
- `WAITING_INPUT`、`PENDING`、`RUNNING`、`RETRY_WAIT` TypeScript Job 为零；
- TypeScript Job 的非终态 dispatch outbox 为零；
- RabbitMQ 主队列、retry 队列和 dead-letter 拓扑均可验证，待执行消息为零；
- TypeScript Runtime URL、allowed host、数据库 Runtime 配置和健康依赖为零；
- Python Runtime 合成 E2E 已产生新鲜 Job、Tool/File 审计、终态和 Delivery 证据。

任一环境未知或未通过时，不得部署删除 TypeScript service/client/image 的阶段。排空不得把 Job 或 Publication 的 runtime kind 改成 Python，也不得跨 Runtime fallback。

## 回滚

冻结和切流阶段仍保留旧 TypeScript Runtime 时，可通过创建新的控制面 revision 显式切回旧 Application Publication；不得直接修改现有 deployment 或 Publication snapshot。

删除阶段之后若需要回滚，必须先同时恢复匹配版本的旧代码、TypeScript Runtime 镜像、固定 URL/host、网络、Secret mount、Runtime Grant 和 readiness 配置，并验证旧 Publication 的完整性与旧 Runtime readiness；完成这些步骤之前不得激活历史 TypeScript Publication。只恢复数据库指针而不恢复执行服务属于禁止操作。

本变更不收窄数据库 `runtime_kind`/`agent_runtime_kind` CHECK 或枚举。未来若要删除历史值，必须另建 OpenSpec contract change，并具备保留期、可恢复备份、全环境零引用和历史审计处置证据。

## 残留分类与本地实现证据

2026-08-17 对 `typescript-agent-runtime`、`typescript-v1`、`TYPESCRIPT_AGENT_RUNTIME_*` 与 `agent-runtime/` 做了仓库级扫描。分类如下：

- **删除阶段已删除**：`agent-runtime/` 下的 TypeScript 源码、测试、合同副本、生成器、Dockerfile、package/lockfile 和 Runtime 专用脚本已在 local 零门禁通过后移除；语言无关事实源保留在仓库级 `contracts/agent-runtime/`。
- **必须保留的历史事实语义**：数据库 migration/CHECK、语言无关合同 schema 与 generated validators、历史 Job/Publication repository 与 API serializer、前端“已退役、只读”标签，以及证明旧事实不被改写、重新激活或执行的测试。
- **必须保留的退役保护语义**：preflight/迁移命令对旧 runtime kind、旧配置键名和旧服务名的检测，Registry/Worker/readiness 的稳定拒绝错误，以及受控迁移审计。这里的字符串用于发现或拒绝旧路径，不是执行依赖。
- **规范与历史证据**：本 active change 的 proposal/design/delta/tasks、尚未 sync 的 canonical baseline 和 `openspec/changes/archive/` 会继续出现旧名称。它们必须按 OpenSpec 生命周期同步或作为不可变历史保留，不得在 apply 阶段直接篡改。
- **非 TypeScript 残留**：`python-agent-runtime`、`contracts/agent-runtime/`、Runtime protocol 和 `agent-runtime-control` 网络是 Python 单 Runtime 的现行通用命名，不应因字符串扫描误删。

本次退役的完整目标环境集合由用户明确限定为 `local`。2026-08-17 在 branch `one_runtime` / commit `e4ab3d5b202b820651e2807d6e75a7134297a289` 上运行只读 preflight，`local` 为唯一 expected/verified environment，报告状态为 `ready` 且 blocker 为空。当前 Compose 定义不含 `typescript-agent-runtime`；数据库聚合为 active TypeScript deployment `0`、非终态 TypeScript Job `0`、非终态 TypeScript dispatch outbox `0`、TypeScript Runtime 配置 `0`，因此无需迁移、等待、取消或终结任何执行事实。1 条 Definition 与 1 条 Publication 是历史测试事实，按本变更的只读历史契约保留且不重新激活。RabbitMQ 主队列消息为 `0`，retry 与 legacy retry 队列经被动声明验证为不存在，按零可执行消息记录为 `verified_absent`，不会为了形成证据而创建空队列。该结果只适用于 `local`，不外推到任何未纳入本次退役范围的环境；local 零门禁已经批准进入 `agent-runtime/` 删除阶段。

## 2026-08-17 验证摘要

- Focused backend：Runtime 合同、Python Runtime、模型 probe、Agent/Application、Worker、MCP、文件工作区、历史投影与 preflight 共 `216 passed`；随后新增的 PostgreSQL pattern 与队列 absent 语义也有独立回归。
- 完整 backend：删除后的最终回归为 `1069 passed, 30 skipped, 2 subtests passed`。schema/migration 专项为 `128 passed, 18 skipped, 2 subtests passed`；18 项均因未提供 `MIGRATION_POSTGRES_DSN` 而跳过，不能作为目标 PostgreSQL migration 现场证据。
- 静态检查：全量 `ruff check backend` 通过，`mypy backend/app` 对 `372` 个源文件通过，Python compileall 通过。原有 Ruff `2` 个 unused-import 与 Mypy `38` 个类型错误已通过显式类型收窄、真实可空建模和 MCP `_meta` 字段修正收口，没有增加宽泛 `ignore`。
- Frontend：`15` 个 test files、`112 passed`，lint、typecheck 与 production build 通过；仅有既有 Vite config 与大 chunk 警告。
- 镜像与运行态：API、Worker、Python Runtime 构建通过；API/Worker 不含 Claude Agent SDK/CLI 或旧 `/app/agent-runtime`，Python Runtime 包含所需 SDK/CLI，三者均从 `/app/contracts/agent-runtime` 读取合同。最终本地 Compose readiness 为 ready，只报告 `python-v1` / protocol `1.3`，没有退役配置键。
- Python 单 Runtime 新鲜闭环：使用独立 Compose project `enterprise-agent-python-runtime-acceptance`、独立 PostgreSQL/RabbitMQ/MinIO volume 和 testing-only deterministic provider，通过真实 HTTP Debug API 新建 6 个 Job。成功、一次延迟重试、不可重试失败、Tool MCP、ONES MCP 双并发/凭据刷新和 File Service/Principal JWT 场景均到达预期 Job 与 Delivery 终态；最后一轮 Job 分别为 `job_d39588fab9944317853e1f1a48c19809`、`job_eb802a5c403e4c768259f5d99c2e37cc`、`job_aaabf535d60a46699e0f79f9c0b4638a`、`job_24f28db43b434af3a9bbf5f590dcb25a`、`job_b1bc8554a9664a93b5c85790840ce482`、`job_90096255aa404700b98378b0e8df6171`。每个 Job 均核对 dispatch outbox、Worker claim、精确 Runtime invocation/terminal、MCP Tool Call 与审计关联、Job 终态及 Delivery 终态；File Service Job 冻结 `text-v2` / protocol `1.3` 工作区和 File Tool。
- Python 安全与故障合成证据：同一 Compose 运行确认 retry count、retry scheduled/released、不可重试终态及认证材料不进入 Runtime event、Tool Call、Delivery、provenance 或 terminal ledger；另运行 `66 passed` 的 Python Runtime/恢复/文件传输/文件冲突/任务工作区/重试专项，覆盖取消胜出、重启后唯一终态、digest replay/conflict、Principal 缺失、非冻结/危险 Tool 与越界路径拒绝、stale-base conflict candidate、沙盒 finally 清理和 Secret 脱敏。
- 规格与仓库：OpenSpec strict、Markdown link check、`git diff --check` 与生产装配残留扫描通过。
- 删除门禁结论：本次完整目标环境集合只有 `local`；正式 host preflight 已同时核对 checkout、local PostgreSQL 与 RabbitMQ，活动引用、非终态 Job/Outbox 和可执行队列均为零。5.4–5.6 已完成；`agent-runtime/` 已删除，本地 TypeScript Runtime 镜像已移除，两个残留旧依赖标签的 Worker 已重建为健康且不再声明 TypeScript Runtime。删除后 focused regression 为 `57 passed`（首轮 55 项，加 MCP meta/CLI 2 项），API readiness 只报告 `python-v1`，第二次 local preflight 仍为 `ready`。最终完整 backend、frontend、静态检查、OpenSpec strict、Markdown links、diff check 和残留扫描全部通过，9.8 已关闭，本 change 已具备归档条件。
