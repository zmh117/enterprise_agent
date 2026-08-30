## ADDED Requirements

### Requirement: Application 可显式冻结受确认保护的 mutation Tool
Agent/Application Publication SHALL 仅在代码 Manifest 同时声明稳定 Tool identifier、schema hash、`effect=mutation` 和受支持确认策略时选择 mutation Tool，并 MUST 将 effect 与确认策略冻结到 Job Tool Snapshot。未知、缺失或漂移的策略 MUST 阻止发布、Job 创建和调用。

#### Scenario: 发布创建待办 Tool
- **WHEN** Agent Envelope 与 Application 子集都选择合法 `dingtalk_create_todo`
- **THEN** Publication 和 Job 冻结其 schema、mutation effect 与卡片确认策略

#### Scenario: mutation 没有确认策略
- **WHEN** 代码或管理请求提供 mutation Tool 但确认策略为空或未知
- **THEN** 发布失败且不得降级为普通只读 Tool

### Requirement: mutation 授权不得替代用户逐次确认
角色 Tool grant、Application 选择和 Job 快照 SHALL 只表示用户可以提出目标 mutation；每一个具体参数集仍 MUST 产生独立 Action Intent 并获得逐次确认，既有确认不得授权后续调用。

#### Scenario: 用户已确认过一次创建待办
- **WHEN** 同一用户在后续 Job 提出另一待办
- **THEN** 系统创建新的待确认意图而不复用旧确认

