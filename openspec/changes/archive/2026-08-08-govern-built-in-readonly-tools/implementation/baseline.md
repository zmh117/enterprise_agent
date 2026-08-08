# 实施基线（任务 1.1–1.3）

采集日期：2026-08-06（Asia/Shanghai）

本文件只记录代码结构、schema、状态和计数，不记录 Secret、连接地址、用户名、业务消息、原始 Job 内容或工具响应。

## 1. 依赖 Gate 与 schema head

- 依赖变更：`stabilize-platform-runtime-foundation`。
- OpenSpec 状态：规划工件完整，实施进度 `88/110`，尚未归档。
- 已同步的依赖能力：该变更任务 7.1–7.12（Resource Revision、Handler Registry/Publication、Application Publication Binding、Job Execution Scope）和 8.1–8.10（runtime generation、LKG、resource reset）均已完成。
- 仓库 migration catalog：28 个 migration，head 为 `027_dingtalk_enterprise_identity_observations.sql`。
- 当前运行 PostgreSQL 的 `schema_migration` head：`027`。
- 本变更采用的实施基线：schema head `027`；后续首个 migration 版本预留为 `028`。
- Gate 解除证据：2026-08-06，用户显式确认 `stabilize-platform-runtime-foundation` 已完成并要求继续本变更；因此本变更以已冻结的 schema head `027` 开始创建 `028`。该确认只解除本变更的实施 Gate，不把依赖变更目录中的历史任务勾选状态冒充为归档状态。
- 后续约束：若依赖变更的 022/023 模型再次变化，必须先更新本变更设计、delta specs 和本基线，再创建后续 migration；不得回写已发布的 `028`。

已确认可复用的基础对象：

- `platform_resource`、`platform_resource_draft`、`platform_resource_verification`、`platform_resource_revision`、`platform_resource_activation`
- `handler_installation`、`handler_publication`
- `business_application_publication_handler`、`business_application_publication_resource`
- `agent_job_execution_scope`、`agent_job_execution_binding`
- `secret://platform/<code>` 及统一 Secret 解析边界

需要由本变更扩展而不能直接复用的约束：

- `handler_publication` 当前只有 `PUBLISHED/DISABLED/ARCHIVED`，没有 Tool Release 的 `ACTIVE/DEPRECATED`、机器验证证据和生命周期审计。
- `business_application_publication_resource` 当前唯一键为 `(application_handler_id, resource_slot)`，一个 slot 只能绑定一条资源。
- `agent_job_execution_scope.schema_version` 当前固定为 2，未冻结 Tool Release、placement、Partition Policy 或 Loki Scope Policy。

## 2. 内置工具与 legacy 现状

### 2.1 代码 Registry

代码 Registry 当前包含 10 个 `1.0.0` 内置 Handler，均可稳定计算 Implementation Digest：

1. `diagnose_loki_label_values`（loki slot）
2. `diagnose_loki_labels`（loki slot）
3. `diagnose_loki_probe`（loki slot）
4. `get_business_flow_context`（无资源 slot）
5. `get_er_context`（无资源 slot）
6. `get_schema_directory`（database slot）
7. `query_database`（database slot）
8. `query_loki`（loki slot）
9. `query_redis_get`（redis slot）
10. `query_redis_scan`（redis slot）

Registry 已拒绝 `cap__` 保留命名空间和动态实现字段，但尚未包含本变更要求的 Tool Manifest semantic version、Verifier Plan 与安全边界扩张判定。

### 2.2 当前 PostgreSQL 计数

| 项目 | 数量/状态 |
|---|---:|
| `tool_definition` | 10 |
| enabled + read-only `tool_definition` | 10 |
| 历史 `agent_tool_binding` 名称级绑定 | 134 |
| 当前 Agent Publication 的名称级绑定 | 8 |
| 活动 Application Publication 间接引用的名称级绑定 | 8 |
| 当前 Agent Publication | 1 |
| 活动 Application Publication | 1 |
| `handler_installation` | 0 |
| `handler_publication` | 0 |
| 活动 Application 的精确 Handler binding | 0 |
| 活动 Application 的精确 Resource binding | 0 |

当前 Agent 选择的 8 个名称级工具为 Loki 三个诊断工具、schema directory、DB query、Loki query、Redis GET 和 Redis SCAN。

`legacy-v1` 是代码在缺少精确 Handler 版本时合成的旧格式标记；数据库中没有独立 `legacy-v1` Release。当前 `agent_job_execution_binding.handler_version=legacy-v1` 和 Execution Scope JSON 显式 legacy 标记均为 0，但 134 条 `agent_tool_binding` 仍然是名称级旧引用，不能据此认定迁移完成。

### 2.3 Job 风险清单

| Job 状态 | 数量 |
|---|---:|
| SUCCEEDED | 40 |
| FAILED | 1 |
| PENDING/RUNNING | 0 |
| FAILED 且仍满足 retry count 条件 | 1 |
| 非终态/可恢复且含显式 legacy execution binding | 0 |
| 可恢复 FAILED 且缺少 Execution Scope | 1 |

该 1 个可恢复 FAILED Job 必须在 cutover 报告中归类；在不能从原 Publication、代码 digest、资源与策略事实唯一物化前，不得自动 retry 或 replay。

## 3. Topology 与资源现状

### 3.1 Topology 计数

| 对象 | enabled 数量 |
|---|---:|
| Environment | 4 |
| Base | 11 |
| Workshop | 16 |

- Environment leaf：0。
- Base leaf：4（`agent_test/mysql`、`agent_test/sqlserver`、`mmk/main`、`xt/mes51`）。
- code 为 `default`/`none` 的占位候选：0。
- 明确的 cloud/edge 伪 Base 候选：6，分别为 `chenzhou_cloud`、`chenzhou_edge`、`guanlan_cloud`、`guanlan_edge`、`shunfeng_cloud`、`shunfeng_edge`。
- `sanjiu/guanlan` 另有非 placement Base，并包含 GL001、GL002；伪 Base 下重复保存 Workshop，证明当前模型把物理位置错误编码进业务 topology。

### 3.2 Resource 与绑定

- Published Resource Revision：5。
- 当前 Resource：database 2、Redis 2、Loki 1，均为 `agent_test` Environment scope。
- `platform_resource_binding`：0。
- `business_application_publication_resource`：0。
- 当前 Loki 只有 Environment scope；schema 还不能表达 global Loki。
- `business_application_publication_resource` 的唯一索引固定 `(application_handler_id, resource_slot)`，确认一个 slot 只能有一条绑定。

### 3.3 Workshop 旧隔离字段

16 个 Workshop 均直接保存非空 `table_prefix`、`redis_key_prefix` 和 `loki_labels_json`。这些字段是可变 topology 属性，不是不可变 Published Policy Revision；本变更需要把 DB/Redis 边界迁移为 Workshop Partition Policy，并停止把 Workshop Loki labels 当作授权隔离。

## 4. 只读采集方式

- migration catalog：通过 `load_migration_catalog(default_migrations_dir())` 读取。
- live schema head 与计数：通过运行中 `api-server` 的 Database abstraction 执行只读 `SELECT`。
- 代码工具：通过 `build_builtin_handler_registry()` 枚举。
- 未读取或输出 `platform_resource_revision.config_json`、`secret_refs_json`、Secret 表、连接地址、原始 Job payload 或业务 key。
