## Why

领域化 canonical baseline 从 master 合并到已分叉的 `mcp_new` 时，Git 将目标分支对 4 份旧主规格的修改自动应用到了归档迁移快照，而不是 8 个 canonical 领域；目标分支还保留第 9 份主规格和两个已完成 change。需要修复归档不变性，并把 `mcp_new` 已接受的规格增量按领域同步后归档。

## What Changes

- 恢复 `2026-08-11-rebuild-canonical-spec-baseline` 的 83 份源快照，使其重新匹配冻结 manifest。
- 独立保存 `mcp_new` 合并前的 84 份主规格基线，包含目标分支修改过的 4 份旧规格和 `agent-runtime-service-contract`。
- 先应用 `migrate-claude-agent-sdk-to-typescript`，再应用 `retire-legacy-api-platform-for-mcp` 的 delta，按 8 个 canonical 领域重建主规格。
- 将 `agent-runtime-service-contract`、`typescript-agent-runtime-service` 归入 `execution-delivery`，将 `standard-mcp-tool-runtime` 归入 `builtin-tool-resource`，不保留第 9 个主规格目录。
- 同步并归档上述两个 30/30、51/51 的 completed changes；使用 `--skip-specs` 防止 CLI 按旧 capability 路径重新创建碎片主规格。
- 保留 `add-identity-aware-ones-mcp`（0/61）为唯一 active change，不修改或伪造其任务状态。
- 增加分支合并时保护 archive 快照和重新对账 canonical baseline 的治理场景。

## Capabilities

### New Capabilities

- 无。

### Modified Capabilities

- `platform-operations`: 增加分叉分支合并导致 rename／modify 交叉时的 archive 完整性和 canonical 重新对账要求。

## Impact

- 受影响：8 个 `openspec/specs/*/spec.md`、两个 completed change 的 archive 状态、原 canonical 重建 archive 的 4 份被错误合并文件。
- 不修改应用代码、migration、数据库、运行配置或 `add-identity-aware-ones-mcp`。
- 最终必须满足：8 个 canonical specs、两个 completed changes 已归档、唯一 active change 为 0/61 的 ONES MCP change、全部 OpenSpec strict validation 通过。
