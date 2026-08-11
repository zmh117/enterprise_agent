## Context

当前活动迁移目录包含 001–042 共 43 个 SQL 文件、约 6,176 行。新数据库会先创建随后已退役的 API Platform、Tool Release 和旧授权结构，再依靠后续 migration 删除；迁移器又以版本、文件名和 checksum 严格校验账本，因此不能简单把文件拼接或删除。现有部署数据库已经以 042 为当前 head，必须在不重放 DDL、不重建数据的前提下接入新基线。

`docs/` 当前同时平铺运行手册、实现基线、验证快照和当前架构说明；49 个 ADR 中只有一部分仍是当前身份/渠道边界，其余旧 API Capability 设计仅有历史审计价值。根 `CONTEXT.md` 和 ChatGPT context 也包含已退役术语，需要与 Canonical OpenSpec 事实层级重新对齐。

当前 `bootstrap_admin` 是交互式 CLI，`local_seed.sql` 已含 `admin`、Argon2 哈希、`platform-admin` 角色和成员关系，但 Compose migrator 只执行 schema migration 与 Runtime grants，空库不保证先创建可登录管理员。

## Goals / Non-Goals

**Goals:**

- 让空数据库只执行当前最终 schema 基线，而不是重放历史演进。
- 让精确 042 的现有数据库可验证、无损、可审计地采纳 100 基线。
- 保持旧 ledger 证据，拒绝部分 head、checksum 漂移和 schema 漂移。
- 在业务服务启动前完成幂等初始管理员 bootstrap。
- 为文档建立当前事实、规范意图、验证快照和历史审计的稳定目录边界。
- 用 SQLite/PostgreSQL 对比、数据计数、注释覆盖和链接检查证明结果。

**Non-Goals:**

- 不支持新 Migrator 直接把 001–041 升到 100。
- 不提供通用 migration squash 工具或任意 head 自动推断。
- 不把业务 fixture、默认 Agent、应用、渠道或 Secret 合并进 schema 基线。
- 不把 local/test 固定密码开放到 staging/production。
- 不删除 Git 历史或 `openspec/changes/archive/`。
- 不借文档整理改变 Canonical Requirement 或声称未验证的运行能力已实现。

## Decisions

### 1. 使用 100 作为第一代活动 Baseline

活动目录最终只包含 `100_baseline_v1.sql` 和未来 101+ migration。100 避免与旧 001–042 版本碰撞，也让 ledger 能明确表示“历史 generation 已被最终基线替代”。基线是最终状态 DDL，不是把 43 个旧文件顺序拼接；它必须直接创建当前保留表、字段、约束和索引，并包含与 042 静态 manifest 一致的 PostgreSQL 中文注释。

替代方案是保留 001–042 并新增 043 marker，但空库仍要重放全部历史，不能解决本次问题；另一个方案是把旧 SQL 移到子目录并按数据库状态选择两套链路，这会永久维护双迁移实现，也被拒绝。

### 2. 删除活动旧 SQL，保留不可变 Legacy Manifest

实施时先从当前 43 个文件生成并审查 `legacy-v1-manifest.json`，至少冻结：

- 每个版本、文件名、checksum；
- 旧 catalog digest；
- 最终 owned tables、columns、constraints、indexes 的 schema fingerprint；
- PostgreSQL 项目表和字段 comment manifest digest；
- legacy head `042` 与 target baseline `100`。

旧 SQL 在完成等价验证后从活动树删除，历史内容由 Git 保留。运行时不依赖 Git，也不依赖已删除 SQL；它只依赖 manifest 完成旧账本验证。

### 3. 用显式 Adoption 状态机兼容精确 042

迁移器识别三种状态：

```text
EMPTY ──execute 100──▶ BASELINE_V1

LEGACY_042 ──verify ledger/schema/comments/data──▶ ADOPTED_V1

LEGACY_001..041 / DRIFTED / NONEMPTY_WITHOUT_LEDGER ──▶ REJECTED
```

042 adoption 在一个事务中插入 100 ledger marker 和独立 baseline adoption metadata；metadata 记录 source head、legacy catalog digest、schema fingerprint、baseline checksum、时间与 migrator build。旧 001–042 ledger rows 保持原样，SchemaHeadValidator 明确接受以下两种合法 ledger 形态：

- 新库：`100[, 101...]`；
- 旧库：`001..042, 100[, 101...]`，且存在匹配的 adoption metadata。

Adoption 不执行 100 业务 DDL。任何校验失败都发生在 marker 写入前并失败关闭。部分旧 head 必须先使用仍包含 001–042 的旧构建升级到 042。

### 4. 基线生成与等价性使用双数据库证据

在删除旧 SQL 前，测试流程分别用旧链和新基线建立临时 SQLite/PostgreSQL 数据库，比较 owned tables、columns、类型的归一化表示、主外键、唯一约束、索引和 comment manifest。PostgreSQL 还执行 042 数据样本到 adoption 的计数/关键 hash 对比；SQLite 用于快速全量单测，但不能代替 PostgreSQL DDL 与注释证据。

基线文件允许使用现有 `-- sqlite-only` / `-- postgres-only` 语句边界。静态检查禁止基线包含已退役表、明文 Secret、默认业务 fixture 或数据清理语句。

### 5. 管理员 Bootstrap 与 Schema Migration 分离

新增非交互、幂等的初始管理员 bootstrap 入口，复用 `AuthService.bootstrap_admin`、密码策略、Argon2 hasher 和现有 RBAC repository；schema baseline 不插入用户或密码。Compose migrator 顺序调整为：

```text
migrate schema → bootstrap initial admin → apply runtime grants
```

local/test 在管理员计数为零且未提供密码文件时使用现有开发凭据 `admin` / `111111111111`。staging/production 必须从权限受限文件、Docker Secret 或交互式输入读取密码；不接受命令行明文或普通环境变量。若任意管理员已存在则整体 no-op，绝不重置密码或覆盖 revision。默认 Agent、Application 与 Connector 仍属于独立 local seed，不进入此 bootstrap。

### 6. 文档采用入口、主题、证据状态三层组织

目标结构为：

```text
docs/
  README.md
  architecture/
  guides/
  operations/
  verification/
  reference/
    chatgpt-context/
    decisions/
  archive/
    legacy-api-platform/
    implementation-baselines/
```

当前有效 ADR 进入 reference/decisions；退役 API Platform ADR 进入 archive/legacy-api-platform。一次性验证记录进入 verification 并标注日期/head；可执行恢复和运维步骤进入 operations。移动使用 Git 可追踪的 rename，并全量更新 README、CONTEXT、OpenSpec artifact 和 Markdown 相对链接。

新增无网络依赖的链接检查器，解析仓库内 Markdown 相对路径并拒绝缺失目标。`docs/README.md` 为人工入口，Canonical OpenSpec 仍是规范事实源，文档索引不能覆盖 Requirement。

### 7. 回滚按数据库来源区分

- 文档移动通过 Git revert 回滚。
- 旧 042 数据库若只完成 adoption、尚未执行 101+，可在停止全部服务并验证 adoption metadata 后，用受控 CLI 原子移除 100 marker 与 adoption metadata；旧 ledger 和业务 schema 从未被删除。
- 已执行 101+ 或由空库直接创建的 100 数据库不得伪装回 042，必须恢复切换前逻辑备份和旧镜像。
- 部署前必须创建可恢复备份；不得以手工修改 ledger 代替受控回滚。

## Risks / Trade-offs

- [基线遗漏约束或索引] → 旧链/新基线在 SQLite 与 PostgreSQL 上做结构 fingerprint 对比，并保留静态 schema/comment manifest 门禁。
- [错误采纳漂移的 042 库] → 同时验证精确 ledger、schema、注释和关键数据不变量；任一不符都在事务前失败关闭。
- [旧库停在 001–041] → 明确要求旧镜像先升 042，错误输出 source head 和安全操作说明，不尝试自动修补。
- [固定开发密码误入生产] → 固定凭据仅允许 local/test；非本地缺少安全密码文件时整个 migrator 失败。
- [Bootstrap 重置现有管理员] → 以当前管理员事实为幂等边界，存在管理员时 no-op，并增加 revision/password hash 不变测试。
- [文档移动导致引用失效] → 自动链接检查覆盖整个仓库，并在移动后执行旧路径残留扫描。
- [现有 active change 同时修改 identity/platform 文档] → 实施和归档前重新检查 delta 冲突，按 Canonical spec 语义合并，不以无 Git 冲突代替规格对账。

## Migration Plan

1. 冻结当前 001–042 checksum、catalog digest、schema/comment manifest，并保存 042 数据库备份。
2. 生成 `100_baseline_v1.sql`，在临时 SQLite/PostgreSQL 上完成旧链与新基线等价验证。
3. 实现双 ledger generation 校验、042 adoption metadata、幂等执行和安全回滚入口。
4. 实现初始管理员 bootstrap，接入 Compose/部署脚本并验证 local/test 与 production 边界。
5. 删除活动 001–042 SQL，更新所有迁移测试、镜像复制和文档。
6. 按目标结构移动文档，更新索引、CONTEXT、链接与当前/历史标记。
7. 运行空库、042 adoption、拒绝路径、数据保留、注释、登录、全量后端、Compose 和文档链接验收。
8. 生产部署时先确认旧库精确 042并备份，再部署新 migrator；验证 adoption 后才启动业务服务。

## Open Questions

无。用户已确认只直接兼容空库与精确 042 旧库，并要求空库初始化创建 `admin`。
