## Context

仓库当前没有 active change，`openspec/specs/` 包含 83 份主规格、755 条 Requirement。它们是多轮已归档 change 的累积结果，业务语义已经接受，但文件边界沿用历史 change 的 capability 切片，Purpose 也大量保留自动生成的 `TBD`。本次工作只重建规范信息架构，不以静态代码证据重新裁决 Requirement。

## Goals / Non-Goals

**Goals:**

- 将全部旧主规格一一映射到 8 个稳定领域，形成唯一 canonical baseline。
- 原样保留每条 Requirement 从标题到全部 Scenario 的正文和顺序，不翻译、不改写 SHALL／MUST 语义。
- 用来源注释保留旧 capability 可追溯性，并用自动校验证明没有漏项、重复项或正文漂移。
- 保持既有 archive 完整，完成后清空 active change。
- 让 Codex 在一般规格任务中只把 canonical specs 当作当前规范。

**Non-Goals:**

- 不判断 Requirement 是否已经实现，不把规划状态改写成运行事实。
- 不修改应用代码、数据库、API、测试或部署配置。
- 不清理 ADR、运行手册或 ChatGPT 上下文包中的历史描述。
- 不删除、重命名或改写既有 archive。

## Decisions

### 1. 使用 8 个领域作为 canonical capability

采用 `identity-access`、`agent-model`、`business-application`、`channel-conversation`、`execution-delivery`、`builtin-tool-resource`、`governed-api-capability`、`platform-operations`。完整的 83→8 映射记录在同一 change 的 `migration-map.tsv`，每个旧 capability 必须且只能出现一次。

选择领域级规格而不是继续按页面、测试环境或单次 change 拆分，是为了让规范边界跟随稳定业务职责；跨领域装配关系按拥有最终发布事实的领域归属。例如 Application 对 Tool／Capability 的组合要求归入 `business-application`，具体 Tool／Capability 的治理要求仍归入各自领域。

### 2. 以 Requirement block 为无损迁移原子

迁移原子从 `### Requirement:` 开始，到下一条 Requirement 或文件结束。每个 block 连同所有 `#### Scenario:`、空行、列表和内联代码原样复制。新文件只新增领域 Purpose、`## Requirements`、来源注释和 canonical 治理 Requirement。

不采用人工重写或摘要，因为即使标题和数量不变，也可能丢失 Scenario、限制条件或失败关闭语义。

### 3. 使用内容哈希和集合校验，而不只比较数量

迁移前后分别解析 Requirement block，以规范化末尾换行后的 SHA-256 建立多重集合，校验：

- 83 个源 capability 全部映射且没有未知项；
- 755 个旧 Requirement 标题全局唯一；
- 旧 block 哈希集合与新 canonical 中的迁移 block 哈希集合完全相等；
- 新增 canonical 治理 Requirement 单独计数，不混入无损迁移证明。

仅比较 `grep -c` 无法发现正文漂移，因此不作为充分证据。

### 4. 直接替换主规格路径，历史只由 archive 与 Git 承担

验证新领域规格已生成且无损后，删除 83 个旧 `openspec/specs/<capability>/` 目录。旧文件不复制到另一个“legacy specs”目录，避免 Codex 再次把两套规格都当作当前事实；完整历史继续由 `openspec/changes/archive/` 和 Git 保存。

### 5. Codex 默认读取边界由仓库指令与 OpenSpec context 双重声明

根级 `AGENTS.md` 规定：

- 一般规格、设计和实现任务只读取与请求相关的 `openspec/specs/*/spec.md`；
- `openspec/changes/<name>/` 仅在用户指定该 active change 或执行 propose/apply/sync/archive 时读取；
- `openspec/changes/archive/` 仅在用户明确要求历史、审计或追溯时读取；
- archive、proposal、design、tasks 和 evidence 不是当前规范来源。

`openspec/config.yaml` 同步提供相同项目上下文，避免生成新 artifact 时重新把 archive 当作主规格。

该限制只约束“规范事实”的默认来源，不禁止 Codex 在实现、诊断或验收任务中读取代码、migration、测试和运行证据。

## Risks / Trade-offs

- **风险：旧路径引用失效** → 在根级指令中公布 8 个新路径；用仓库搜索检查非 archive 内容中的旧主规格直链。
- **风险：机械拼接遗漏或重复** → 在删除旧目录前执行映射、标题、block 哈希和 Scenario 计数校验。
- **风险：领域文件变大** → Codex 默认只读取与任务相关的领域文件，不再全量加载 83 份规格；来源注释支持文件内定位。
- **风险：archive 被误认为当前规范** → AGENTS 与 OpenSpec context 都明确 archive 是非规范历史证据。
- **权衡：保留了可能尚未实现的要求** → 这是本次“无损已接受基线”的明确选择；实现状态审计应作为另一个 change 进行。

## Migration Plan

1. 冻结源清单、Requirement/Scenario 数量和 block 哈希。
2. 按 `migration-map.tsv` 生成 8 份 change delta specs，并验证 OpenSpec change。
3. 由相同映射生成 8 份 canonical main specs，加入 canonical 治理要求。
4. 比较源与目标 block 哈希集合，确认无损后删除 83 个旧主规格目录。
5. 新增根级 `AGENTS.md`，更新 `openspec/config.yaml`。
6. 执行 strict validation、读取边界搜索、archive 完整性和 `git diff --check`。
7. 使用 `--skip-specs` 归档本 change，因为 delta 已通过受校验的领域迁移直接落入主规格；归档后再次确认 active changes 为空。

回滚方式：在提交前恢复被替换的 `openspec/specs/` 和指令文件；提交后通过 Git 反向变更恢复。既有 archive 从不参与回滚，因为本次不修改它。

## Open Questions

无。用户已确认采用无损领域重组方案以及 8 个领域边界。
