## Context

`mcp_new` 在 canonical baseline 分支创建后继续演进：4 份旧主规格被修改，新增 `agent-runtime-service-contract`，并保留两个已完成 change 和一个未实施 change。普通 Git merge 无文本冲突，但 rename detection 将目标分支的旧规格修改应用到了 canonical 重建 archive 的 `source-specs-snapshot`；8 个新领域规格仍是 master 版本，因此“merge clean”不等于规格语义已正确合并。

## Goals / Non-Goals

**Goals:**

- 恢复已归档 canonical 重建 change 的 Requirement-block 源快照完整性，并规范化无语义 EOF 空行。
- 冻结 `mcp_new` 合并前实际主规格作为独立对账输入。
- 按提交语义顺序重放两个 completed change 的 delta，并输出 8 个领域主规格。
- 用 Requirement block 哈希、operation log、strict validation 和 active change 清单证明结果。
- 归档两个已完成 change，保留 ONES MCP change 为唯一 active change。

**Non-Goals:**

- 不修改应用实现、测试、migration 或运行配置。
- 不把 `add-identity-aware-ones-mcp` 的 61 项任务标记完成，不同步其 delta。
- 不把已归档历史当作新的业务要求；archive 只用于恢复和追溯。

## Decisions

### 1. 先冻结目标分支基线，再恢复原 archive

当前被 Git 自动改写的 83 份 `source-specs-snapshot` 实际包含 `mcp_new` 对 4 份旧主规格的修改，因此先将其复制到本 change 的 `target-source-specs-snapshot`，再加入当前 `agent-runtime-service-contract`，形成 84 份目标输入。随后从源提交 `fd00d39` 恢复原 archive 的 4 份文件，并要求原 manifest verifier 重新通过。

不直接把被改写的 archive 当作正确结果，因为 archive 必须保持创建时的历史事实；也不丢弃其中的目标修改，因为它们是 `mcp_new` 进入领域基线的必要输入。

### 2. 使用 capability→domain 映射和 Requirement 操作重放

沿用原 83→8 映射，并新增：

- `agent-runtime-service-contract` → `execution-delivery`
- `typescript-agent-runtime-service` → `execution-delivery`
- `standard-mcp-tool-runtime` → `builtin-tool-resource`

先读取 84 份目标基线 Requirement blocks，再依次重放：

1. `migrate-claude-agent-sdk-to-typescript`
2. `retire-legacy-api-platform-for-mcp`

`ADDED` 在标题不存在时追加、存在时按 implicit modified 替换；`MODIFIED` 必须找到并完整替换；`REMOVED` 必须找到并删除；任何缺失、重复标题或未知 capability 都失败关闭。这样保留 OpenSpec 智能同步语义，同时不会按旧 capability 路径重建 30 份碎片主规格。

`claude-agent-runtime-integration` 中同一 MCP 暴露边界连续出现两次 Requirement 标题漂移，明确按 `in-process SDK MCP server` → `governed MCP servers` → `deployment-fixed standard MCP server` 的演进链执行 modify+rename，并在 operation manifest 中记录旧标题；除此之外不做模糊匹配。

### 3. 以 staging 和 manifest 控制切换

生成器写入 `_canonical_staging`，记录源 block 哈希、每个 delta operation、最终 block 哈希和计数。只有 staging 与 manifest 完全一致、标题全局唯一、每条 Requirement 至少一个 Scenario 时，才把当前 9 份主规格保存为 `pre-reconcile-canonical-snapshot` 并切换为 8 份目标规格。

### 4. Completed changes 只在同步证明后使用 `--skip-specs` 归档

两个 completed changes 的 delta 已由对账生成器落入领域主规格。归档时使用 `--skip-specs`，避免 OpenSpec CLI 以旧 capability 名重新创建主规格目录。归档前检查 artifact 和 tasks 全部完成；归档后 active list 必须只剩 `add-identity-aware-ones-mcp`。

### 5. 不把未实施 change 混入当前基线

`add-identity-aware-ones-mcp` 虽然 artifacts 完整，但 tasks 为 0/61，继续作为 active delta 保留。它不会进入 canonical baseline，也不会因本次整理被标记完成或归档。

## Risks / Trade-offs

- **风险：Markdown delta 解析与 OpenSpec 语义不一致** → 仅支持规范的 ADDED/MODIFIED/REMOVED/RENAMED headers；对未知结构失败；最终再由 OpenSpec strict validation 验证。
- **风险：同名 Requirement 被错误覆盖** → 基线和最终标题必须全局唯一；MODIFIED/REMOVED 精确匹配 capability 内标题。
- **风险：归档后失去 delta 输入** → 本 reconciliation archive 保存源快照、operation manifest 和生成器；原 completed change 也完整移动到 archive。
- **风险：未实施 ONES MCP delta 仍使用旧 capability 名** → 保持其 active 和非默认读取边界；后续实施前需单独把该 change rebase 到 8 个 canonical domain。

## Migration Plan

1. 冻结 84 份目标主规格输入与哈希。
2. 恢复原 canonical archive 的 4 份文件并验证原 manifest。
3. 生成 staging：目标基线 + TypeScript Runtime delta + legacy retirement delta + 本 change 治理场景。
4. 验证 operation、Requirement、Scenario、哈希和标题唯一性。
5. 保存当前 9 份主规格快照并切换到 8 个领域规格。
6. 归档两个 completed changes（`--skip-specs`）。
7. strict validation、active list、archive、Git whitespace 和 clean status 验证。
8. 归档本 change，提交后将 `mcp_new` 快进到最终提交。

回滚：在提交前从 `pre-reconcile-canonical-snapshot` 恢复 9 份主规格，并把 completed change archive 移回 active；提交后使用反向提交。不得用回滚再次改写原 canonical archive。

## Open Questions

无。用户已确认保留 0/61 的 ONES MCP change 为唯一 active，其余目标分支差异全部收口。
