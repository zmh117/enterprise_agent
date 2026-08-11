## Why

当前 `openspec/specs/` 由历史 change 归档后累积为 83 份细粒度 capability 规格，包含 755 条已接受 Requirement，但大量 Purpose 仍是自动生成的 `TBD`，同一业务领域被拆散在多份文件中。需要在不改变已接受业务语义的前提下，按稳定领域重建唯一主规格基线，并明确 Codex 默认不得把 active change 或 archive 当作当前规范。

## What Changes

- **BREAKING（规格路径）**：以 8 份领域级 canonical specs 取代现有 83 份碎片主规格；旧 capability 路径不再是主规格入口。
- 无损迁移现有全部 755 条 Requirement 及其 Scenario，不重写 SHALL 语义，不借本次整理判断实现状态。
- 为每个迁移分组保留原 capability 来源标记，建立旧路径到新领域的可追溯关系。
- 保留 `openspec/changes/archive/` 的全部历史，不修改既有归档内容。
- 在仓库级 Codex 指令和 OpenSpec 项目上下文中规定：默认只读取相关 canonical specs；仅在处理指定 change 或明确追溯历史时读取 change／archive。
- 完成后归档本 change，使 active change 回到空集。

## Capabilities

### New Capabilities

- `identity-access`: 内部用户、外部身份、认证、角色、授权与管理入口。
- `agent-model`: Agent 定义、模型连接、工作流模板和 Agent 管理界面。
- `business-application`: 业务应用装配、发布、访问、执行策略与运行路由。
- `channel-conversation`: Channel、钉钉、Webhook、会话、消息与附件入口。
- `execution-delivery`: Job、Agent Runtime、队列、Outbox、重试、审计与结果投递。
- `builtin-tool-resource`: 内置只读工具、资源、拓扑、数据库、Redis 与 Loki 治理。
- `governed-api-capability`: 外部连接、认证配置、个人凭据、Capability、Handler 与 ONES 能力。
- `platform-operations`: 平台配置、Secret、Migration、Compose、测试环境、验收及 canonical 读取治理。

### Modified Capabilities

- 无业务 Requirement 语义修改；现有 83 个 capability 仅改变 canonical 归属和文件路径。

## Impact

- 受影响路径：`openspec/specs/`、根级 `AGENTS.md`、`openspec/config.yaml`。
- 不修改应用代码、数据库 schema、API、运行时配置或既有归档内容。
- 依赖主规格旧路径的人工或自动化入口必须改为按 8 个领域读取。
- 验收必须证明旧 Requirement 与新 Requirement 的标题、正文和 Scenario 一一对应，并通过 OpenSpec strict validation、active change 空集和 Git 差异检查。
