## 1. 冻结旧迁移证据

- [x] 1.1 为当前 001–042 目录生成逐文件 version/name/checksum 与整体 catalog digest，并将结果保存为不可变 `legacy-v1-manifest`
- [x] 1.2 在 SQLite 与 PostgreSQL 上执行旧链，导出最终 owned table/column/constraint/index fingerprint 和 PostgreSQL comment manifest digest
- [x] 1.3 盘点迁移文件名、旧 head、042 注释清单和 `default_migrations_dir()` 的全部代码、测试、Compose、Docker 与文档引用
- [x] 1.4 增加 manifest 漂移测试，禁止修改旧 checksum、catalog digest、legacy head 或 target baseline

## 2. 建立 Schema Baseline 100

- [x] 2.1 从 042 最终状态生成并人工审查 `100_baseline_v1.sql`，直接创建当前保留的 SQLite/PostgreSQL schema
- [x] 2.2 将最终 PostgreSQL 项目表和字段中文注释纳入基线，并保持静态 comment manifest 100% 覆盖门禁
- [x] 2.3 增加基线静态门禁，禁止已退役表/列、数据清理 DML、默认业务 fixture、明文 Secret 和默认用户数据进入 schema DDL
- [x] 2.4 比较旧 001–042 链与基线 100 的双数据库 schema fingerprint，修复全部表、类型、约束、索引和注释差异

## 3. 实现 Legacy 042 Baseline Adoption

- [x] 3.1 重构 migration catalog/ledger 模型，明确 fresh baseline generation 与 legacy 042 generation 两种合法账本形态
- [x] 3.2 增加 baseline adoption metadata，记录 source head、legacy catalog digest、schema fingerprint、baseline checksum、migrator build 和时间
- [x] 3.3 实现空库执行 100、精确 042 只登记 100 等价 marker、已采纳数据库幂等退出的状态机
- [x] 3.4 在 adoption 前验证旧 ledger、最终 schema、PostgreSQL 注释和关键保留数据不变量，并保证 marker/metadata 原子写入
- [x] 3.5 让 SchemaHeadValidator 同时接受 `100[,101...]` 与 `001..042,100[,101...]`，并拒绝缺少或伪造 adoption metadata
- [x] 3.6 对 001–041、空洞或漂移 ledger、无 ledger 非空 schema、未知 head 和 schema/comment 漂移实现安全失败关闭提示
- [x] 3.7 增加仅在没有 101+ migration 时可用的受控 adoption rollback CLI，原子移除 100 marker/metadata 且不修改业务 schema

## 4. 空库初始管理员 Bootstrap

- [x] 4.1 将初始管理员创建收敛为复用 AuthService、Argon2 和 RBAC repository 的幂等服务，不在 baseline SQL 中插入身份数据
- [x] 4.2 新增非交互 bootstrap CLI：local/test 缺少密码文件时创建 `admin` / `Administrator` 并兼容 `111111111111`，但日志和数据库不出现明文
- [x] 4.3 为 staging/production 只接受权限受限密码文件、容器 Secret 或交互输入；缺少输入时失败关闭且不接受 CLI 参数或普通 env 明文
- [x] 4.4 保证已有任意平台管理员时 no-op，重复运行不重置密码、不覆盖状态/revision、不重复创建角色或成员关系
- [x] 4.5 将 Compose/部署脚本顺序改为 `migrate -> bootstrap initial admin -> apply runtime grants`，任一步失败都阻止依赖业务服务启动
- [x] 4.6 增加 local/test 首次登录、production 缺失 Secret 拒绝、已有管理员保留、重复执行和敏感值不泄露测试

## 5. 切换活动迁移目录

- [x] 5.1 将活动 head、迁移测试、schema comment 测试、运行时 readiness 和 fixture 引用更新到 baseline 100 generation
- [x] 5.2 在双数据库等价与 042 adoption 测试通过后，从活动目录删除 001–042 SQL，只保留 100、未来 migration 和 legacy manifest
- [x] 5.3 更新 Docker build context、镜像复制清单、Makefile/脚本和 CI，确保运行镜像包含基线与 manifest 但不依赖已删除旧 SQL
- [x] 5.4 增加后续 migration 版本必须从 101 单调递增且不能重用 001–100 的目录校验

## 6. 重组项目文档

- [x] 6.1 建立全部现有文档的 current architecture、guide、operation、verification、reference 或 archive 分类清单并标注移动目标
- [x] 6.2 新增 `docs/README.md` 总索引和事实层级说明，创建 architecture、guides、operations、verification、reference、archive 目录
- [x] 6.3 将当前有效文档和 ADR 移入对应主题目录，将退役 API Platform ADR 与旧实施基线移入历史目录并保留审计说明
- [x] 6.4 将 ChatGPT context 移入 reference，按当前 `Worker -> Runtime -> tool-mcp -> Resource`、身份/RBAC 和双 Runtime 边界刷新过期内容
- [x] 6.5 更新根 README、backend README、CONTEXT、OpenSpec artifact、脚本和全部 Markdown 相对链接，清除旧平铺路径引用
- [x] 6.6 新增无网络依赖的 Markdown 本地链接检查器并接入质量命令，拒绝缺失文件目标和无法解析的仓库内引用

## 7. 运维文档与回滚

- [x] 7.1 编写空库 baseline 100 + 初始管理员 bootstrap Runbook，区分 local/test 默认凭据与 production Secret 输入
- [x] 7.2 编写旧库升级前置检查，要求备份、精确 042 ledger、schema/comment fingerprint 和关键数据计数验证
- [x] 7.3 文档化 001–041 使用旧镜像先升级 042 的路径，以及 adoption-only 与 101+ 两种不同回滚策略
- [x] 7.4 更新 Compose 启动、数据库恢复和故障排查文档，明确禁止手工伪造 ledger 或绕过 `service_completed_successfully`

## 8. 验证与验收

- [x] 8.1 运行 SQLite 空库 100、重复迁移、042 adoption、部分 head/漂移拒绝和 rollback 全量测试
- [x] 8.2 运行 PostgreSQL 空库 100、042 备份副本 adoption、schema/comment 等价、数据计数/hash 保留和并发 Migrator 测试
- [x] 8.3 用全新 Compose 数据卷验证 schema、`admin` 登录、平台管理员角色、Runtime grants 和所有依赖服务 readiness
- [x] 8.4 验证 production 空库缺少管理员密码 Secret 时 migrator 失败，提供 Secret 后成功且日志/账本/审计无明文
- [x] 8.5 运行文档链接检查、旧路径/退役术语残留扫描、Ruff、mypy、后端全量测试、Compose config 和受影响镜像构建
- [x] 8.6 重新检查 active change 对 identity/platform/documentation 的 delta 冲突，运行 `openspec validate --all --strict` 与 `git diff --check`
