## Why

当前 Session、Job 与 Workflow 持久化同时保留旧字段、通用字段或多套可变表示，写侧双写、读侧回退与事实源边界没有形成可验证的退役契约；继续叠加迁移会放大漂移、回滚和历史追溯风险。现有数据抽样已表明部分兼容字段保持一致，适合在不牺牲发布快照、审计、幂等和恢复事实的前提下，采用分阶段 consolidation 收敛事实源并退役已证明无用的字段或表。

## What Changes

- 为 Session、Job、Message、Workflow、Outbox、Runtime ledger/claim/event、身份验证 challenge 与一次性 cutover artifact 建立明确的事实源分类、所有者、写入者、读取者、保留期和退役状态。
- 将 Session 的通用 Channel/Connector/External Conversation/Requester、业务应用 Publication 与执行范围字段确认为当前事实源；经过一致性验证和读写切换后退役钉钉专用兼容影子字段。
- 将 Job 的通用来源、请求人、Project 边界、Agent/Application provenance 与执行快照确认为不可变执行事实，将用户消息正文归一到有序 `agent_message`；经过关联完整性验证后退役 Job 上的旧来源、用户及消息正文影子字段。
- 将规范化 Workflow node/edge 记录确认为草稿图唯一事实源，将 Workflow publication snapshot 保持为已发布运行事实；经过等价校验后退役模板上的可变 `graph_json` 副本。
- 明确不同阶段的 Webhook、Channel ingress、Job dispatch 和 Delivery outbox，以及 Runtime 幂等/恢复和身份 challenge 表是各自领域的运营事实，不能因命名或低行数被合并或删除。
- 对 `job_dispatch_cutover_quarantine` 等一次性 artifact 建立基于零写入者、零读取者、保留期、审计导出和回滚边界的条件退役门禁；未满足门禁时保持现状。
- 采用 expand → verify/backfill → read cutover → write cutover → observation → contract/drop 的分阶段迁移，禁止长期双写；真实 schema adoption 依赖 baseline `100` 已部署，并需单独部署授权和维护窗口。
- **BREAKING**：完成 contract 阶段后，旧 Session/Job 兼容列、Job 消息正文影子列与 Workflow `graph_json` 不再可读写；依赖这些列的内部代码、查询和运维脚本必须先迁移。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `agent-model`: 明确 Workflow 草稿图和已发布快照的唯一事实源，并定义 `graph_json` 的兼容退役边界。
- `channel-conversation`: 明确通用会话身份字段与 Application Publication 共同构成会话复用边界，移除对钉钉专用影子字段的长期依赖。
- `execution-delivery`: 明确 Session、Job、Message 的事实分工、不可变 provenance 例外和旧字段读写退役要求，同时保护各阶段 outbox 与 Runtime 恢复事实。
- `platform-operations`: 增加 schema 事实源登记、分阶段 consolidation、退役门禁、baseline 前置条件和可审计部署证据要求。

## Impact

- 受影响代码主要包括 Session/Job domain model 与 repository、Job 创建和查询、Channel ingress、Workflow repository/service、迁移目录、schema verification、运维手册和针对兼容回退的测试。
- 数据库变更将新增核对/约束及后续 contract migration；实际 migration 编号在实施时根据当时目录分配，避免与其他 active change 冲突。
- 不改变外部 Channel、Job 或 Workflow API 的业务语义，但内部直接依赖旧列的调用方必须在 contract 前完成迁移。
- 不合并或删除活跃 outbox、Runtime ledger/claim/event、身份 challenge、不可变 publication/history/audit 表，也不在本 proposal 阶段修改真实数据库。
- 与 `stabilize-schema-baseline-and-runtime-config` 的关系仅为部署前置：先完成真实 `042 → 100` adoption，再另行授权执行本 change 的数据库迁移。
