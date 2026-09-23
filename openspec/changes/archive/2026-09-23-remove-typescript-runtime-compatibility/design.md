## Context

Confirmed-current（以代码、迁移与本机库核对）：

- 迁移 119 以失败关闭守卫阻止非 `python-v1` 的 `agent_definition`、`agent_publication`、`agent_job`，并把三列 CHECK 收紧为 `= 'python-v1'`。任何 head ≥ 119 的库都没有 TypeScript Definition/Publication/Job。
- 最终 schema 中唯一仍允许 `typescript-v1` 的约束是 `agent_runtime_invocation_claim.runtime_kind`（PostgreSQL 约束名 `agent_runtime_invocation_claim_runtime_kind_check`）。该表是 Python Runtime 的短期调用占用，`backend/app/python_runtime/invocations.py` 按 `expires_at` 清理，不区分 runtime kind；表上没有外键引用。
- PostgreSQL 表注释 `agent_runtime_event`、`agent_runtime_terminal_ledger` 仍写 “TypeScript Runtime”，实际由 Python Runtime 写入。
- `backend/app` 已无 TypeScript 分支；`SUPPORTED_RUNTIME_KINDS`、`agent_runtime_kind_unsupported` 等是对任何非 `python-v1` 输入的通用失败关闭。
- 本机库：Definition/Publication/Job 全部为 `python-v1`，调用占用表 0 行。

## Goals / Non-Goals

**Goals:**

- 数据库不再允许任何非 `python-v1` 的 runtime kind。
- canonical spec、注释、文档与测试不再描述或守护 TypeScript Agent Runtime 的历史兼容。
- 退役守卫集中到一个位置，防止 TypeScript Runtime 配置或服务名回流。

**Non-Goals:**

- 不修改已应用迁移（100–119）与 `legacy-v1-manifest.json`，其 checksum 不可变。
- 不移除通用的 runtime kind 校验，不移除 Python Runtime 协议 1.4 兼容或 `historical_read_only`（二者属于 Python 协议，不属于 TypeScript）。
- 不改写前端技术栈、`dingtalk-runtime` 进程等以 TypeScript 作为编程语言的描述。
- 不改动 archive 中的历史记录。

## Decisions

### D1：迁移 145 删除非 Python 占用后收紧约束

先 `DELETE ... WHERE runtime_kind <> 'python-v1'`，再收紧 CHECK。备选方案是沿用 119 的守卫表，发现残留就让迁移失败。没有采用它，因为这些行只是无主租约：没有任何 Runtime 能持有或续约它们，Python Runtime 过期后也会按 `expires_at` 删除，不属于审计事实。直接删除与运行时语义一致，也不会给运维增加手工步骤。

### D2：SQLite 重建表、PostgreSQL 替换约束

SQLite 不支持修改 CHECK。119 的“重命名列 + 新增列”做法会把列移到末尾并引入默认值；claim 表只有 6 列、1 个索引，没有外键引用，所以改为整表重建，保持列顺序与无默认值，然后重建 `idx_agent_runtime_invocation_claim_expires`。PostgreSQL 用 `DROP CONSTRAINT` 加同名 `ADD CONSTRAINT`，列注释保持不变；两条表注释用 `COMMENT ON TABLE` 更新。

### D3：守卫集中到退役平台合同测试

零散断言（Compose 服务名、环境变量名、Workflow 文本中不得出现 `typescript-agent-runtime`）收敛为 `test_retired_legacy_platform_contract.py` 的活动标记：`typescript-agent-runtime`、`TYPESCRIPT_AGENT_RUNTIME`、`typescript-v1`。扫描范围沿用现有的 `.env.example`、Compose、`backend/app`、`frontend/src`、`scripts`。canonical spec 增加禁止回流的正向标记。以 `typescript-v1` 作为非法输入样例的测试改用通用非法值，继续覆盖“任何非 `python-v1` 被拒绝”。

### D4：迁移 head 断言从迁移目录计算

新增迁移时，大量测试写死的 `result.head == "144"` 需要逐一修改，与种子哈希属于同一类漂移。凡是语义为“已迁移到最新 head”的断言，改为从部署目录计算；登记型的显式清单（例如迁移目录注册表、某版本之后应用的序列）仍保持显式，作为有意的守卫。

## Risks / Trade-offs

- [其它环境存在非 Python 占用] → 迁移会删除这些行。由于没有持有者，删除不会影响任何执行；Definition/Publication/Job 与审计表不受影响。
- [SQLite 重建遗漏约束或索引] → 迁移测试核对重建后的 CHECK、主键与索引，并验证拒绝写入 `typescript-v1`。
- [PostgreSQL 约束名与预期不一致] → 已在本机 PG 18 核对约束名；PostgreSQL 集成测试覆盖真实迁移链。
- [守卫收敛后覆盖面变窄] → 标记扫描覆盖的文件范围大于原来零散的断言，并新增 canonical spec 回流检查。

## Migration Plan

1. Migrator 应用 145（一次性，随常规升级执行）。
2. 回滚：迁移只向前。若需回退，应部署新的 expand 迁移，不能修改 145。
3. 145 不访问对象存储，不影响 Job、Publication 或审计。

## Open Questions

（无）
