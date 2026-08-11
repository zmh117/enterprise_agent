## Why

当前 Compose 运行库仍保留精确 legacy `042` ledger，尚未登记 baseline `100` adoption；而当前工作区已经按 baseline generation 校验 schema head。与此同时，内置 runtime config definition 的重复注册即使语义未变化也会更新记录并递增 revision，导致启动与读取路径产生无意义写入、虚假版本变化和审计噪声。两项问题需要在下一次按当前代码重建服务前收敛，以免部署失败关闭或 runtime revision 失真。

## What Changes

- 复用已归档的 `2026-08-11-establish-schema-baseline-and-organize-docs` 已同步到 canonical `platform-operations` 的 baseline `100` 规范；本 change 不复制 baseline generation、legacy manifest 或 adoption 状态机。
- 为现有 legacy `042` 部署定义受控 rollout：只读 preflight、可恢复逻辑备份、由 one-shot Migrator 执行 adoption、业务服务启动闸门、数据与 revision 核验，以及 adoption-only 回滚证据；禁止手工伪造 ledger 或 adoption metadata。
- 让内置 runtime config definition reconciliation 按规范化后的语义字段判断变化；完全相同的定义不得执行 UPDATE、递增 revision、修改 `updated_at` 或产生“已变化”审计。
- 将 definition 列表、snapshot 等只读请求与 definition 注册分离；内置定义只允许在受控初始化或显式管理同步路径 reconciliation。
- 对真实定义变更保留受版本与审计保护的更新，并覆盖重复启动、重复读取、实际定义变化、并发 reconciliation 和 PostgreSQL 运行验证。
- 补充面向现有部署的中文 Runbook 和可重复验证命令，但不在普通测试或 apply 过程中自动修改当前 Compose 数据库。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `platform-operations`: 增加 baseline adoption 的部署验收边界，并要求内置 runtime config definition reconciliation 具有语义幂等性、真实 revision 和无副作用读取。

## Impact

- Schema 与部署：`backend/app/shared/migrations.py`、SchemaHeadValidator、one-shot Migrator 编排、Compose 数据库升级 Runbook 和 adoption 验证脚本／测试。
- Runtime config：definition registry、platform config repository/service/controller、runtime config loader、revision/hash 与配置审计。
- 验证：SQLite 单元测试、PostgreSQL 集成测试、重复服务初始化与只读 API 回归、`042 -> 100` adoption 数据保留与回滚演练。
- 前置 OpenSpec 已满足：`establish-schema-baseline-and-organize-docs` 已完成语义同步并归档；实施时仍须基于最新 canonical requirement 重新对账。
