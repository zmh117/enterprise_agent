## 1. 数据库

- [x] 1.1 新增 `145_contract_python_runtime_invocation_claim.sql`：删除非 `python-v1` 占用；SQLite 重建表并保留列顺序与过期索引；PostgreSQL 替换 CHECK，更新 `agent_runtime_event`、`agent_runtime_terminal_ledger` 表注释
- [x] 1.2 `schema_fact_sources.json` 为调用占用、Runtime 事件与终态账本补充迁移 145 证据引用
- [x] 1.3 迁移测试覆盖：清理非 Python 占用、拒绝写入 `typescript-v1`、保留 Python 占用与索引
- [x] 1.4 “已迁移到最新 head”的断言改为从迁移目录计算；显式迁移清单追加 145

## 2. 代码、配置与测试清理

- [x] 2.1 `backend/maintenance/agent_runtime_grants.sql` 与 `.env.example` 去除 TypeScript Runtime 叙述
- [x] 2.2 零散的 TypeScript 守卫断言收敛到 `test_retired_legacy_platform_contract.py` 的活动标记与 canonical spec 回流检查
- [x] 2.3 以 `typescript-v1` 为非法输入样例的后端测试改用通用非法值；测试函数名去除 TypeScript
- [x] 2.4 前端测试样例去除 TypeScript Agent/Publication 叙述

## 3. 文档与规范

- [x] 3.1 README、CONTEXT、`docs/README.md`、`docs/architecture/*`、`docs/reference/enterprise-agent-system-design-for-chatgpt.md` 去除 TypeScript Runtime 历史兼容叙述（保留语言层面的 TypeScript 描述）
- [x] 3.2 delta 同步到 canonical spec，`openspec validate --all --strict` 通过

## 4. 本地验证

- [x] 4.1 后端快速层与迁移层测试通过；前端 lint/typecheck/test 通过
- [x] 4.2 在一次性 PostgreSQL 18 上从 100 迁移到 145 并核对约束与注释

## 5. 真实环境验收

- [ ] 5.1 目标环境升级后确认迁移 145 已应用、调用占用约束只允许 `python-v1`，且 Runtime 调用正常

## 本地验证证据（2026-09-23）

- PostgreSQL 18 一次性容器：`test_schema_migration_postgres_integration.py` 20 passed；新建库断言调用占用约束为 `CHECK ((runtime_kind = 'python-v1'::text))`，且 `pg_constraint` 与表/列注释均不含 typescript。
- PostgreSQL 18 升级路径（临时脚本）：迁移到 144 后写入 python 与 typescript 占用各一条，升级只应用 145，仅保留 python 占用，再写入 `typescript-v1` 被 `CheckViolation` 拒绝。
- 后端全量（仓库根目录）：3256 passed，86 skipped。
- 前端 `npm run lint`、`npm run typecheck`、`npm run test`：179 passed。
- `ruff format --check`、`ruff check`、`mypy backend/app`（本地依赖与 CI 同版依赖两套环境）通过。
- 已知与本变更无关的失败：`test_ones_bug_create.py`、`test_ones_task_update.py` 依赖被 `.gitignore` 排除的 `ones_mock/ones/查询条件字典.yaml`，文件缺失的检出环境（含 CI）会失败。
