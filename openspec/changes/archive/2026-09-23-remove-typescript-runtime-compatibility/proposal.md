## Why

TypeScript Agent Runtime 已退役，迁移 119 也已通过失败关闭守卫把 `agent_definition`、`agent_publication`、`agent_job` 的 runtime kind 收紧为只允许 `python-v1`；任何达到 119 及以上 head 的数据库都不可能再持有 TypeScript Definition、Publication 或 Job。canonical spec 却仍要求“保留历史 TypeScript 事实并保留原始 runtime kind”，并描述历史 TypeScript Application Publication 的只读、迁移与激活拒绝场景，这些都已无法对应任何可能存在的数据（Documented-intent 与 Confirmed-current 不一致）。同时数据库里仍有 `agent_runtime_invocation_claim.runtime_kind` 允许 `typescript-v1`，两条表注释仍写 TypeScript Runtime，注释、文档和零散守卫测试也保留 TypeScript Runtime 叙述，持续误导后续维护。

## What Changes

- 新增 contract migration：删除 `agent_runtime_invocation_claim` 中非 `python-v1` 的遗留占用（无主租约，Python Runtime 过期清理本就不区分 kind），并把该列约束收紧为只允许 `python-v1`；PostgreSQL 更新 `agent_runtime_event`、`agent_runtime_terminal_ledger` 的表注释。**BREAKING**：残留的非 Python 调用占用会在迁移中被删除。
- canonical spec 去除“保留历史 TypeScript 事实”“历史 TypeScript Publication 只读/迁移/拒绝激活”等条款，改为：数据库约束只允许 `python-v1`，任何非 `python-v1` 请求失败关闭且不改写。
- 保留通用的 runtime kind 失败关闭校验（`SUPPORTED_RUNTIME_KINDS`、`agent_runtime_kind_unsupported` 等），它们是对所有非 `python-v1` 输入的防御，不是 TypeScript 兼容。
- 清理 TypeScript Runtime 叙述：`backend/maintenance/agent_runtime_grants.sql` 头注释、`.env.example`、README、CONTEXT、`docs/` 相关页面。前端技术栈和 `dingtalk-runtime` 进程使用 TypeScript 语言的描述不属于本次范围。
- 零散的 TypeScript 守卫测试收敛到退役平台合同测试的标记检查；以 `typescript-v1` 作为非法输入样例的测试改用通用非法值。
- 已应用迁移（100–119）与 `legacy-v1-manifest.json` 中的历史 DDL 保持不变。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `agent-model`：Agent 定义、草稿发布、创建与管理界面不再承诺保留或只读展示 TypeScript 历史事实；非 `python-v1` 一律失败关闭。
- `business-application`：发布校验、历史 Publication 重新激活与 Runtime 选择去除 TypeScript 历史版本条款与场景。
- `execution-delivery`：默认部署场景改为不提供任何其它 Runtime 实现或跨实现 fallback。
- `platform-operations`：以“当前运行态只支持 Python Runtime”替换“当前运行态只支持 Python 并保留历史 TypeScript 事实”，并覆盖调用占用约束收紧。

## Impact

- 数据库：新增迁移 145（SQLite 重建 `agent_runtime_invocation_claim`，PostgreSQL 替换 CHECK 约束并更新 2 条表注释）；`schema_fact_sources.json` 证据引用；迁移 head 相关测试。
- 代码：业务代码不变（已无 TypeScript 分支）；运维 SQL 注释、`.env.example`。
- 测试：后端 TypeScript 守卫测试收敛、前端测试样例；迁移 head 断言改为从迁移目录计算。
- 文档：README、CONTEXT、`docs/README.md`、`docs/architecture/*`、`docs/reference/enterprise-agent-system-design-for-chatgpt.md`。
