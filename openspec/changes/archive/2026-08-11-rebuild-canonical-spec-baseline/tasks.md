## 1. 冻结与生成

- [x] 1.1 校验 83→8 映射全覆盖，生成源 Requirement/Scenario 哈希清单和 8 份 delta specs
- [x] 1.2 生成 8 份 staging canonical specs，并验证 755 条迁移 Requirement 的 block 哈希集合完全一致

## 2. 切换 Canonical Baseline

- [x] 2.1 将 83 份旧主规格保存为本 change 的只读迁移快照，并以 8 份领域规格替换 `openspec/specs/`
- [x] 2.2 新增仓库级 `AGENTS.md` 并更新 `openspec/config.yaml`，限制 Codex 默认只读取相关 canonical specs

## 3. 验收

- [x] 3.1 验证 755 条旧 Requirement、1716 个旧 Scenario 无损迁移，且 3 条 canonical 治理 Requirement 单独新增
- [x] 3.2 执行 OpenSpec strict validation、旧路径引用检查、archive 完整性检查和 `git diff --check`
