## 1. 冻结与恢复

- [x] 1.1 冻结 `mcp_new` 的 84 份合并前主规格输入并生成源 manifest
- [x] 1.2 从 `fd00d39` 恢复原 canonical archive 的 4 份文件并重新通过原 manifest verifier

## 2. Canonical Delta 重放

- [x] 2.1 按 TypeScript Runtime → legacy retirement 顺序重放两个 completed change 的 delta 并生成 8 份 staging specs
- [x] 2.2 验证每个 ADDED/MODIFIED/REMOVED 操作、最终 Requirement hash、Scenario、标题唯一性及治理场景
- [x] 2.3 保存当前 9 份主规格快照并切换为 8 个 reconciled canonical domains

## 3. Change 收口

- [x] 3.1 使用 `--skip-specs` 归档 `migrate-claude-agent-sdk-to-typescript`
- [x] 3.2 使用 `--skip-specs` 归档 `retire-legacy-api-platform-for-mcp`
- [x] 3.3 验证 `add-identity-aware-ones-mcp` 保持 0/61 且成为唯一业务 active change

## 4. 最终验收

- [x] 4.1 执行 OpenSpec strict validation、archive 完整性、canonical 数量、旧路径和 whitespace 检查
