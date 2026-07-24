## ADDED Requirements

### Requirement: 业务应用执行策略必须固定到Agent Job
系统 MUST 在业务应用路由命中且创建 Agent Job 前，从命中的 Business Application Publication 读取 `max_turns`、`timeout_seconds` 和 `max_tool_calls`，计算有效执行策略并把请求值、有效值、策略版本及来源 Publication 一并持久化到 Job。迁移后的每个新 Agent Job MUST 具有合法 v1 Execution Policy 快照；Worker MUST 只使用 Job 固定的策略，MUST NOT 在消费、重试或执行时重新解析当前活动 Deployment。

#### Scenario: 命中业务应用并创建Job
- **WHEN** 钉钉消息命中一个活动 Business Application Publication
- **THEN** Job 在发布到 RabbitMQ 前保存不可变的业务应用 Execution Policy 快照
- **AND** 快照记录 Business Application Publication、Agent Publication 和配置 hash 来源

#### Scenario: Job入队后激活新版本
- **WHEN** Job 已入队后管理员发布或激活了不同的业务应用策略
- **THEN** 已入队 Job 及其后续重试继续使用原固定策略
- **AND** 只有新创建的 Job 使用新策略

#### Scenario: 非业务应用入口创建Job
- **WHEN** 调试入口、普通 Agent 入口或其他非 Business Application 入口创建新 Job
- **THEN** Job 创建服务从固定 Agent Publication 或运行时默认值生成合法 v1 Execution Policy 快照
- **AND** 不允许持久化空策略 Job

#### Scenario: Worker遇到缺失策略的Job
- **WHEN** Worker 读取到缺少 v1 Execution Policy 快照或快照无法通过 schema 校验的 Job
- **THEN** 系统以不可重试的 Job 完整性错误停止执行
- **AND** 不使用 Agent Publication 或全局默认值在 Worker 阶段补齐策略

### Requirement: 有效执行策略必须确定且不能扩大Agent限制
系统 SHALL 以固定 Agent Publication 的执行限制为基础，对 `max_turns` 和 `timeout_seconds` 取业务应用请求值与 Agent 限制中的更严格值；Agent Publication 缺少对应值时 SHALL 使用现有运行时默认值。`max_tool_calls` SHALL 使用业务应用快照中的规范化值，并遵守现有字段范围。管理 API 和运行记录 MUST 同时区分请求值与有效值。

#### Scenario: 业务应用策略比Agent更严格
- **WHEN** Agent Publication 允许 `max_turns=20` 且业务应用请求 `max_turns=8`
- **THEN** Job 的有效 `max_turns` 为 `8`

#### Scenario: 业务应用策略比Agent更宽松
- **WHEN** Agent Publication 允许 `timeout_seconds=180` 且业务应用请求 `timeout_seconds=300`
- **THEN** Job 的有效 `timeout_seconds` 为 `180`
- **AND** 管理端能够看到请求值 `300` 和有效值 `180`

#### Scenario: 禁止所有工具调用
- **WHEN** 业务应用配置 `max_tool_calls=0`
- **THEN** Agent 可以生成不调用工具的答复
- **AND** 第一次内部工具调用在进入 ToolRegistry 前被策略拒绝

### Requirement: Worker必须强制执行三个策略字段
系统 MUST 对每次 Agent 执行 attempt 强制执行有效 `max_turns`、`timeout_seconds` 和 `max_tool_calls`。工具调用次数 SHALL 统计该 attempt 内所有进入内部 MCP 工具桥的成功或失败调用尝试，超过上限的调用 MUST NOT 进入 ToolRegistry 或任何下游数据源。

#### Scenario: 达到最大轮次
- **WHEN** Agent 执行达到固定的 `max_turns` 且未产生有效最终结果
- **THEN** 系统以稳定的最大轮次耗尽错误结束该 attempt
- **AND** 保留耗尽前已产生的安全工具事件

#### Scenario: 达到墙钟超时
- **WHEN** Agent attempt 超过固定的 `timeout_seconds`
- **THEN** 系统取消当前 SDK 执行并记录安全超时原因
- **AND** 后续是否重试继续遵守现有 timeout retry 策略及同一固定执行策略

#### Scenario: 超过最大工具调用数
- **WHEN** 当前 attempt 已使用完 `max_tool_calls`
- **THEN** 下一次工具调用以 `execution_policy_max_tool_calls_exhausted` 或等价稳定错误码终止
- **AND** 系统不调用 ToolRegistry、不访问数据库、Redis、Loki 或其他下游
- **AND** 该策略耗尽不得作为普通瞬时传输错误重试

### Requirement: 策略耗尽必须可审计并安全通知
系统 MUST 保存策略来源、有效值、实际工具调用次数、耗尽字段、Job 状态和安全错误码，并 SHALL 复用现有失败投递链把不含内部配置或敏感数据的提示回复到原钉钉会话。

#### Scenario: 工具调用预算耗尽
- **WHEN** Job 因 `max_tool_calls` 耗尽失败
- **THEN** 运行记录显示固定有效上限、已使用次数和稳定错误码
- **AND** 原钉钉会话收到安全失败提示
- **AND** 审计不包含 Secret、Token、完整工具响应或私有模型推理

#### Scenario: 查询成功Job的策略来源
- **WHEN** 管理员查看一个由业务应用创建并成功完成的 Job
- **THEN** 运行记录展示 Business Application Publication、Agent Publication、请求策略和有效策略

### Requirement: 接管状态必须区分同步关键路径和后台治理缺口
系统 SHALL 仅使用影响消息同步执行关键路径的组件计算 `runtime_status`，并 MUST 继续逐字段报告不在关键路径上的治理能力。Trigger routing、Agent Publication、会话上下文策略、Execution Policy、声明的 Workflow 以及 Delivery 属于同步关键路径；未实现的 `retention_days` 清理属于非阻塞后台治理缺口。

#### Scenario: 执行策略全部接线但retention未接线
- **WHEN** Trigger、Agent Publication、会话上下文、三个 Execution Policy 字段和 Delivery 均已执行，未配置 Workflow 或其他未支持的同步能力，但 `retention_days` 仍为 `stored_only`
- **THEN** `runtime_wired` 为 `true` 且整体 `runtime_status` 为 `wired`
- **AND** `retention_days` 继续显示 `stored_only` 和稳定 reason code
- **AND** 管理端显示非阻塞数据治理提示，不宣称已执行历史消息清理

#### Scenario: Execution Policy仍有字段未执行
- **WHEN** 任一已配置 Execution Policy 字段未被 Worker 强制执行
- **THEN** 整体 `runtime_status` 为 `partially_wired`
- **AND** 未执行字段明确显示 `stored_only`

#### Scenario: 已配置Workflow但没有执行引擎
- **WHEN** Publication 声明了 Workflow Publication 但运行时仍不执行 Workflow
- **THEN** Workflow 保持 `stored_only`
- **AND** 整体 `runtime_status` 保持 `partially_wired`

### Requirement: 本变更不得实现retention清理
系统 MUST NOT 因本变更新增按 `retention_days` 删除或归档会话、消息、摘要、附件、Job、工具调用或审计事件的 Worker、定时任务或队列。

#### Scenario: retention_days已经到期
- **WHEN** 某会话年龄超过其保存的 `retention_days`
- **THEN** 本变更不自动删除或归档该会话数据
- **AND** 管理端继续把该字段标记为尚未接线的治理能力

### Requirement: 迁移必须删除不兼容旧Job及关联运行数据
系统 MUST 在维护窗口中删除迁移前没有 v1 Execution Policy 快照的旧 Agent Job，并 MUST 同步清理依赖这些 Job 的 session、message、step、tool call、artifact、delivery、attachment、关联 Webhook 运行事件和 Job 级 audit 数据。系统 MUST 保留用户、外部身份、RBAC、Agent、Business Application、Publication、Deployment、Connector、Secret 和其他控制面配置。

#### Scenario: 测试数据库包含旧Job
- **WHEN** 执行本变更数据库迁移且现有 Agent Job 没有 v1 Execution Policy 快照
- **THEN** 系统按外键安全顺序删除旧 Job 及其关联运行数据
- **AND** 迁移结束后 `agent_job` 不存在缺少合法策略快照的记录

#### Scenario: 旧Job包含附件对象
- **WHEN** 被删除的旧 Job 关联 MinIO 中的附件或运行产物对象
- **THEN** 一次性维护清理流程删除对应对象和数据库元数据
- **AND** 不留下能够被新会话继续引用的孤儿附件

#### Scenario: 保留控制面配置
- **WHEN** 旧运行数据清理完成
- **THEN** 已配置用户、身份绑定、Agent Publication、Business Application Publication、local Deployment 和 Connector 仍然存在
- **AND** 管理员无需重新建立控制面配置
