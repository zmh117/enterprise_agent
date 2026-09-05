## Context

Confirmed-current implementation 已具备确定性的文件上下文解析、Gate 评估、Task Workspace 与 schema v5 Job File Manifest，但其 public seam 是浅的：

- `file_workspace/manifest_service.py` 识别文字输出文件意图；`CreateAgentJobService` 又把 ingress hint 与该识别结果组合两次，分别传给 Workspace 与 resolver。
- `CreateAgentJobService` 在准入决策前创建或复用 Workspace，随后根据 `TIME_WINDOW` 依赖补建 Workspace，并继续解释绑定原因、能力类型与候选数量来决定 Manifest 自动物化。
- `attachments/service.py` 从持久化 payload 重建依赖并直接调用 Gate evaluator；初始准入与等待恢复共享规则，但没有共享完整的准入结果。
- 2026-09-04 的回归表明该 seam 会使“生成 md 文件记录我今天的对话”被时间词误判为历史附件查询。

Documented-intent 由 canonical `task-file-workspace` 约束：只允许确定性执行前绑定；时间窗口只提供最多 20 个 `METADATA` 候选；Job File Manifest 使用 schema v5 冻结精确身份而不冻结授权；物化时由 File Service 重新授权。本 change 必须保持这些行为及现有中文通知不变。

## Goals / Non-Goals

**Goals:**

- 在 Job application 层建立一个 deep 的文件准入 module，以单一不可变计划隐藏文字分类、依赖解析、Gate、Workspace 需求和 Manifest binding plan 的组合复杂度。
- 让 Job 创建、系统通知、附件等待恢复与 File Service adapter 使用同一套冻结语义。
- 删除调用方对 `TIME_WINDOW`、能力类型、候选数量和自动物化规则的解释。
- 通过完整链路特征测试证明重构前后行为等价，并兼容部署前已持久化的等待中 Job。

**Non-Goals:**

- 不新增或调整自然语言关键词、格式识别、绑定优先级、候选范围或通知文案。
- 不改变 Task Workspace、Job File Manifest schema v5、File MCP、Runtime、Channel 或 Business Application 的外部协议。
- 不把 File Service 的持久化、Manifest hash、物化、保留期检查或授权复检移入 Job module。
- 不引入模型分类、概率判断、新数据库表、migration、第三方依赖或长期双路径开关。

## Decisions

### 1. 在 Job application 层建立单一文件准入 seam

将现有 `file_context.py` 深化为 `file_admission.py`（或等价的单一内部 module），由它公开不可变的准入计划；现有正则、时间窗口解析、候选选择、Gate 与安全通知 helper 保持为该 module 的内部 implementation。输出文件意图识别从 Manifest implementation 移入此处。

选择 Job application 层，是因为准入的最终结果是“创建 Agent Job、等待输入或只发送系统通知”。File Service 仍是 Workspace、文件身份、Manifest 和物化授权的权威 adapter，不反向依赖 Job application 类型。

备选方案：仅缓存一次 `requests_file_output`。该方案不能消除 Workspace 补建、Manifest 规则和等待恢复的 seam，拒绝。

备选方案：让 File Service 或新协调器接管整个 Agent Job 持久化事务。该方案会把 Job、授权、Outbox 与投递复杂度搬入文件领域，形成新的巨型 module，拒绝。

### 2. 使用一个不可变 Admission Plan，而非多个相互推导的布尔值

准入计划概念上包含：有效输出意图、Gate action/原因码、安全通知事实、冻结文件依赖、Workspace requirement、Manifest references/Working Set/自动物化计划，以及等待恢复所需的兼容 payload。ingress `requests_file_output` 继续作为原始 hint 输入；有效输出意图只在准入 module 内计算一次，调用方不得覆盖。

计划内部可以保留细分的 parser、resolver 和 evaluator，但 public interface 只暴露完成后的计划与使用冻结依赖重新评估 Gate 的能力。计划不携带凭据、对象位置、文件正文或未授权业务消息。

### 3. 在同一 Unit of Work 内先计划、后应用副作用

`CreateAgentJobService` 保持幂等命中与业务授权的现有顺序。Session 确定后，在当前 Unit of Work 内只读获取活动 Workspace、当前会话候选和仍有效的保留候选，以单一观测时刻形成 Admission Plan；随后按计划创建或复用 Workspace、持久化系统通知或 Agent Job、冻结 Tool Snapshot 与 Manifest。

Workspace adapter 接收计划已经确定的有效输出意图和 Workspace requirement；Manifest adapter 接收计划已经确定的 references 与自动物化事实。调用方可以负责调用次序和事务，但不得通过检查 dependency reason/capability/count 改写计划。

Task Workspace 的既有创建行为保持不变，包括输出请求、当前附件、显式引用以及有合法时间窗口候选但尚无活动 Workspace 的情况。系统通知路径也保持变更前的 Workspace 生命周期结果。

### 4. 等待恢复只刷新状态，不重新做语义解析

继续持久化现有 `file_turn_dependencies` 安全 payload，确保在途 Job 无需 migration。当前附件使用的 `current:<ordinal>` 占位身份在附件持久化后按既有规则解析；附件完成时只刷新来源与可读性状态，并通过准入 module 的同一 Gate 规则重新评估。

恢复过程不重新解析消息、不重新计算输出意图、不读取新增候选，也不改变原绑定集合。这样既保持 Manifest 与 Job 的冻结语义，又防止等待期间的工作区变化造成决策漂移。

### 5. File Service 权威和依赖方向保持不变

`JobFileManifestService` 继续负责 Workspace 创建/复用、request registration、schema v5 finalize 与 Runtime Manifest。准入 module 只形成 plan，不直接读写 File Service 数据库，也不把 plan 当作授权。

为避免 File Service 依赖 Job 类型，Job application 侧使用一个窄 adapter 把 plan 的已决事实传给现有 File Service interface；adapter 不包含新的业务条件。物化、交付和按需查询继续逐次校验当前用户、Application Publication 与文件授权。

### 6. 以行为冻结测试驱动迁移和删除旧 seam

先在 `CreateAgentJobService.execute()` 层增加覆盖输出时间词、显式时间窗口来源、空/超限/歧义候选、当前附件等待、显式引用和 Workspace 开关的特征测试。再增加 Admission Plan 单元测试与部署前 `file_turn_dependencies` 恢复测试。

新调用路径通过上述测试后，一次性删除旧分类位置、重复有效意图计算、`_file_turn_gate` glue、调用方 `TIME_WINDOW` Workspace 补建判断及 Manifest 自动物化条件。不得长期保留可切换的双 implementation。

## Risks / Trade-offs

- [风险] 重排分支时无意改变绑定优先级或中文通知 → 先冻结完整链路行为矩阵，逐项对照 canonical scenario，并保留现有 resolver/Gate 回归测试。
- [风险] 新计划类型无法读取部署前等待中 Job 的 payload → 保持 `file_turn_dependencies` schema 兼容，并增加旧 payload 恢复测试；本 change 不做 migration。
- [风险] 单一 module 继续增长成为难以维护的大文件 → 保持一个 public seam；只有在内部实现明显独立且无需额外 public interface 时才拆分私有 parser/model 文件。
- [风险] 调用方为了事务编排再次解释计划内部字段 → 计划直接提供 Workspace 与 Manifest 的已决事实，代码评审和测试禁止按 reason/capability/count 分支。
- [权衡] Job application 仍负责事务调用顺序 → 这是为了保持 Agent Job、Outbox 与 File Service 的依赖方向；复杂度被限制为机械执行计划，而非再次做文件语义决策。

## Migration Plan

1. 增加变更前行为特征测试和旧 `file_turn_dependencies` 恢复 fixture。
2. 引入不可变 Admission Plan，将现有解析、Gate 和输出意图识别收敛到单一 module；暂不改变调用结果。
3. 迁移 `CreateAgentJobService`，使 Workspace、Job/通知和 Manifest 只消费 plan。
4. 迁移附件完成恢复路径，使其通过同一 module 刷新 Gate。
5. 删除旧 helper、重复布尔推导和调用方语义分支，运行定向及完整回归验证。
6. 无数据库或协议迁移；若部署后出现行为漂移，回滚该代码提交即可，既有 Job payload 仍由旧 implementation 读取。

## Open Questions

无阻塞规格问题。实现阶段只需用现有 fixture 确认系统通知路径的 Task Workspace 副作用与变更前完全一致，不得借重构清理或改变该行为。
