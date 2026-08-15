## ADDED Requirements

### Requirement: Business Application 草稿配置任务工作区自然周期
系统 SHALL 在 Business Application 草稿中提供严格结构的 `task_workspace_retention_period`，只允许 `DAY`、`WEEK` 或 `MONTH`，新草稿默认选择 `WEEK`。该字段只控制任务工作区自然周期，MUST NOT 被解释为消息附件、保留文件、消息、Job、工具调用或审计的内容保留期。

#### Scenario: 管理员配置月工作区
- **WHEN** 管理员在业务应用前端选择 `MONTH` 并保存合法预期 revision
- **THEN** 系统创建新草稿 revision并返回规范化策略

#### Scenario: 提交未知周期
- **WHEN** 客户端提交 `ROLLING_24_HOURS`、任意天数或未知字段
- **THEN** 系统使用字段级错误拒绝
- **AND** 不创建部分草稿 revision

### Requirement: Publication 冻结任务工作区保留策略
每个新 Business Application Publication MUST 显式冻结 `task_workspace_retention_period` 并纳入 canonical snapshot、schema version、hash、有效解析结果和审计。既有 Publication 缺少该字段时 MUST 稳定解释为 `WEEK`；管理端后续修改只影响新 Revision 和新 Publication，不得追溯改写既有 Publication 或已创建工作区。

#### Scenario: 发布后修改草稿策略
- **WHEN** 已发布的 P1冻结 `DAY`，管理员随后把新草稿改为 `MONTH`
- **THEN** P1和由P1创建的工作区继续使用 `DAY`
- **AND** 只有后续新 Publication创建的新工作区使用 `MONTH`

#### Scenario: 解析旧 Publication
- **WHEN** 活动历史 Publication 的 snapshot schema 中没有任务工作区保留字段
- **THEN** Resolver 返回规范化 `WEEK`及兼容来源摘要
- **AND** 不修改历史 snapshot或hash

### Requirement: 管理端展示工作区策略的真实接线状态
业务应用列表、详情、发布预览和运行时就绪评估 SHALL 展示任务工作区保留策略及其来源。发布前 MUST 校验 File Service 与 File Worker 能执行该策略；配置已冻结但依赖未就绪时 MUST 返回明确的非敏感组件状态，不得宣称生命周期已执行。

#### Scenario: File Worker 未就绪
- **WHEN** Publication 配置合法但 File Worker 清理能力不可用
- **THEN** 管理端显示任务工作区生命周期组件未就绪及稳定 reason code
- **AND** 不把消息附件或其它 `retention_days` 状态冒充为工作区策略状态

### Requirement: 任务文件能力依赖消息附件策略
Business Application 草稿与管理前端 MUST 显式保存并展示 `session_policy.attachments_enabled` 和 `continuous_conversation_enabled`，不得因表单缺字段把既有值重置为关闭。启用任务工作区时系统 MUST 同时启用消息附件处理；后端 MUST 拒绝任务工作区已启用但消息附件已关闭的矛盾新草稿。历史 Publication 仍按其冻结快照解析，不得追溯改写。

#### Scenario: 管理员启用任务工作区
- **WHEN** 管理员在草稿中启用任一会自动启用任务工作区的任务文件能力
- **THEN** 前端同时把 `session_policy.attachments_enabled` 设置为 `true`
- **AND** 保存、发布与后续重新编辑均保留该值

#### Scenario: 客户端提交矛盾配置
- **WHEN** 客户端提交 `task_file_features.workspace_enabled=true` 且 `session_policy.attachments_enabled=false`
- **THEN** 后端以 `session_policy.attachments_enabled` 字段级错误拒绝新草稿
- **AND** 不创建部分草稿 Revision
