## ADDED Requirements

### Requirement: 真实Runtime必须使用Job固定的模型连接
系统 SHALL 让 `AgentExecutor` 和 `RealClaudeCodeAgentClient` 从 Job 固定的 Agent Publication 获取模型连接 revision、config hash、Base URL、模型映射、Subagent 模型、effort 和 Credential 绑定。Worker MUST NOT 为包含模型连接快照的新 Publication 重新读取 Agent 当前发布指针或用进程启动时的全局模型 URL、模型和 Key 覆盖该快照。

#### Scenario: Job排队后发布新模型连接
- **WHEN** Job 已固定 Agent Publication 后管理员发布使用不同 Base URL 或模型的新 Agent Publication
- **THEN** 已排队 Job 和其重试继续使用原固定模型连接 revision
- **AND** 新 Job 才使用新 Agent Publication 的模型连接

#### Scenario: Publication模型连接hash不匹配
- **WHEN** Worker 读取到的模型连接 revision 与 Agent Publication 固定的 config hash 不一致
- **THEN** Job 在调用 Claude Agent SDK 前以不可重试完整性错误失败
- **AND** 不解析 Key、不启动 CLI、不调用模型或工具

### Requirement: Runtime必须安全解析并隔离每次执行的模型环境
系统 MUST 在每次 Agent attempt 开始时解析固定模型连接绑定的 active Secret，并把规范化字段映射为 Claude Agent SDK/CLI 所需的 Anthropic Base URL、API Key/Auth Token、主模型、默认模型、Subagent 模型和 effort。不同 Job 的模型环境 MUST 隔离，MUST NOT 通过无保护的进程全局环境产生跨 Job URL、模型或 Key 串用。

#### Scenario: 两个Job使用不同模型连接
- **WHEN** 同一 Worker 先后或并发处理固定到不同模型连接的 Job
- **THEN** 每个 SDK session 只继承自己的 Base URL、模型映射、effort 和 Key
- **AND** 任一 Job 的配置不会残留到另一个 Job

#### Scenario: Active Key被轮换
- **WHEN** Job 已固定 Credential 绑定，但该 Credential 在 attempt 开始前完成安全轮换
- **THEN** Worker 使用新的 active Secret 版本
- **AND** Job 的 Base URL、模型映射和 Agent Publication provenance 保持不变

### Requirement: 旧Agent Publication保留受控兼容路径
系统 SHALL 允许迁移前没有模型连接 revision 的现有 Agent Publication 继续使用既有 DB-backed runtime config/env fallback，并 MUST 在管理 API 和 Web 将其标记为 legacy global connection。所有本变更实施后新建的 Agent Publication MUST 固定模型连接，不得继续创建新的隐式全局连接 Publication。

#### Scenario: 现有业务应用引用旧Publication
- **WHEN** 已激活 Business Application 仍引用迁移前 Agent Publication
- **THEN** Runtime 继续使用现有 DB-backed 全局模型配置执行该 Job
- **AND** 管理端提示需要重新发布 Agent 并在业务应用中显式切换

#### Scenario: 发布新Agent草稿
- **WHEN** 管理员在本变更上线后发布 Agent 草稿
- **THEN** 发布校验要求草稿引用有效模型连接 revision
- **AND** 缺失连接时不得退回全局配置创建新 Publication

### Requirement: 模型运行记录必须只展示安全Provenance
系统 SHALL 在 Agent Job、运行记录和安全诊断中保存 Agent Publication、模型连接 revision/config hash、模型、effort 和脱敏 Provider Host，并 MUST NOT 持久化 API Key、Auth Token、Secret ref、完整 Base URL 查询参数、Prompt 或模型原始响应。

#### Scenario: 查看成功Job
- **WHEN** 管理员查看由新 Agent Publication 执行成功的 Job
- **THEN** 运行记录展示模型、Provider Host、模型连接 revision 和 Agent Publication
- **AND** 不提供任何能够恢复 Credential 的字段

#### Scenario: Provider认证失败
- **WHEN** Claude Agent SDK 因 Key 无效返回认证错误
- **THEN** Job 记录稳定安全错误码和脱敏 Provider Host
- **AND** 日志、审计和原会话失败投递不包含 Key、请求头或上游响应正文
