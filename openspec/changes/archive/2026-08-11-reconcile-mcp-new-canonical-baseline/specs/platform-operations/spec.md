## MODIFIED Requirements

### Requirement: Archive 保持完整且不参与默认规范解析
基线重建 SHALL 保留 `openspec/changes/archive/` 下的历史内容，不得为了减少默认上下文而删除或改写既有 archive。默认规范解析 MUST 排除 archive；历史内容只有在显式追溯时才参与证据分析。分叉分支合并涉及旧规格路径和 archive 内迁移快照的 rename／modify 交叉时，维护流程 MUST 独立验证 archive manifest，并将目标分支的已接受差异重新同步到 canonical domain，而不得接受仅有“无 Git 冲突”的结果。

#### Scenario: 重建 Canonical Baseline
- **WHEN** 维护者替换或重组主规格文件
- **THEN** 既有 archive 的目录、proposal、design、tasks、delta specs 和 evidence 保持不变

#### Scenario: 默认规格检索
- **WHEN** Codex 搜索当前领域要求且用户没有请求历史
- **THEN** 搜索范围排除 `openspec/changes/archive/`

#### Scenario: 分叉分支修改了被迁移的旧规格
- **WHEN** canonical baseline 提交把旧规格移动到 archive，而目标分支在共同基点后修改了同一旧规格路径
- **THEN** 合并流程验证 archive 快照仍与其冻结 manifest 一致，并把目标差异同步到对应 canonical domain
- **AND** 流程不得因为 Git merge 无文本冲突就宣称 canonical 对账完成

#### Scenario: 领域化后归档旧 Capability Delta
- **WHEN** 一个 completed change 的 delta 仍按领域化之前的 capability 路径组织
- **THEN** 维护流程先按明确映射把 delta 语义同步到 canonical domains，再使用跳过重复同步的方式归档
- **AND** 归档不得重新创建碎片主规格目录
