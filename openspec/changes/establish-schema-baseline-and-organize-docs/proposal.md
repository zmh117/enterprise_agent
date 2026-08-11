## Why

仓库当前有 43 个活动迁移 SQL、6,176 行历史演进脚本，以及大量平铺且部分已失效的文档和 ADR；全新部署必须重放已被后续迁移撤销的旧结构，维护者也难以区分当前说明与历史设计。需要建立与当前 042 最终 schema 等价的单一数据库基线，并重组文档事实层级，同时确保空库启动后存在可登录的初始管理员。

## What Changes

- 新增最终 schema 基线 `100_baseline_v1.sql`，全新 SQLite/PostgreSQL 数据库从该基线创建当前表、约束、索引及 PostgreSQL 中文注释，后续迁移从 101 开始。
- **BREAKING**：001–042 不再作为活动迁移 SQL；旧 SQL 由 Git 历史保留，仓库仅保留不可变 legacy manifest（版本、文件名、checksum、catalog digest）用于兼容验证。
- 为已完整执行到 042 的数据库增加显式 baseline adoption：验证旧 ledger、最终 schema、注释和关键数据不变量后，只登记 100 等价标记，不重复执行 DDL、不删除历史 ledger 记录。
- **BREAKING**：只直接支持空库和精确 042 旧库；001–041、缺失记录、checksum 漂移或 schema 漂移的旧库失败关闭，并要求先使用旧版本迁移器升级到 042。
- 将空库流程收敛为“迁移基线 → 幂等 bootstrap/seed → Runtime grants”；local/test 空库创建 `admin`/`Administrator`、`platform-admin` 角色和成员关系，并兼容现有本地密码 `111111111111`，只保存 Argon2 哈希。非本地环境不得回退到固定密码，必须通过安全输入或文件提供初始密码。
- 重组 `docs/` 为带总索引的 architecture、guides、operations、verification、reference 和 archive 目录；当前文档与历史材料明确分区，旧 API Platform ADR 移入历史区但不删除审计记录。
- 更新根 README、backend README、CONTEXT、OpenSpec/脚本引用和全部内部链接，并增加文档链接与当前性检查。
- 增加空库、精确 042 adoption、部分旧 head 拒绝、ledger/checksum/schema 漂移拒绝、数据保留、注释覆盖、bootstrap 幂等和管理员登录验证。

## Capabilities

### New Capabilities

- `project-documentation`: 定义项目文档目录、当前/历史事实分区、总索引、链接完整性和失效内容治理规则。

### Modified Capabilities

- `platform-operations`: 将逐版本活动迁移目录改为 baseline generation，定义空库基线、精确 042 adoption、旧 ledger 兼容、失败关闭和 bootstrap 编排要求。
- `identity-access`: 明确空库初始管理员、local/test 固定开发凭据边界、非本地安全密码输入、哈希存储和幂等创建要求。

## Impact

- 后端迁移器、schema head validator、migration ledger 兼容模型、迁移与 bootstrap CLI。
- `backend/migrations/`、legacy manifest、`backend/seeds/local_seed.sql`、Compose migrator 命令及镜像复制清单。
- SQLite/PostgreSQL 迁移测试、空库/042 升级测试、身份 bootstrap 与登录测试。
- `docs/` 全目录、根 `README.md`、`backend/README.md`、`CONTEXT.md` 及仓库内文档链接。
- 已部署数据库在切换新版本前必须处于精确 042；不满足条件的部署需要先用旧镜像完成升级。
