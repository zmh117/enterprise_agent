## Why

当前测试及辅助代码约 6.9 万行，后端全量测试在本地基线中为 1377 通过、30 跳过，耗时 7 分 22 秒；同时测试仅有一个几乎未使用的 `integration` 标记，大量用例重复创建并迁移测试数据库。继续按单一全量门禁扩张会延长反馈周期，并增加跨领域测试 helper 和超大测试文件的维护成本。

本变更以反馈速度、隔离性和可维护性为目标，而不是以删除测试行数为目标；平台治理、拒绝/恢复路径和真实端到端验收覆盖必须保留。

## What Changes

- 建立可执行的 `unit`、`contract`、`integration`、`acceptance`、`migration` 测试分层，并为未显式分类的测试提供失败关闭的检查。
- 将 PR 快速门禁与完整回归门禁分开：参考环境下 PR 快速门禁目标不超过 2 分钟，后端完整套件目标不超过 5 分钟；主分支和发布流程仍执行完整回归。
- 为非迁移语义测试提供一次构建、逐测试隔离复制的 SQLite 迁移基线，避免重复执行完整 migration；验证 Migrator、baseline、checksum 和兼容性的测试继续从明确数据库状态独立运行。
- 按领域拆分跨职责测试 helper 和高维护热点文件，通过具名 scenario builder 复用 Arrange 逻辑，同时保持断言、拒绝路径和审计边界清晰可读。
- 增加测试清单、耗时报告和 canonical Requirement 到测试层级的覆盖映射；只有在证明行为与失败边界重复后才能删除测试。
- 不改变生产 API、数据库 schema、授权模型、Publication/Job 快照或运行时行为。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `platform-operations`: 增加测试套件分层、隔离数据库基线、反馈预算、完整回归保留和重复测试删除门禁要求。

## Impact

- 主要影响 `backend/tests/`、`frontend/src/**/*.test.*`、`pyproject.toml`、测试辅助模块、`Makefile` 和 `.github/workflows/ci.yml`。
- 可能增加轻量测试清单/预算校验脚本，不引入生产运行时依赖。
- CI 将新增快速与完整测试入口；完整回归的覆盖范围不缩减。
- 重构期间优先处理业务应用控制面、任务文件验收、Python Runtime、角色授权、Schema Migration 和 Agent Profile 前端测试等高体积、高变更热点。
