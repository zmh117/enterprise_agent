## MODIFIED Requirements

### Requirement: Job 查询 API 必须返回任务详情
系统 SHALL 提供受授权的 Job 详情查询，返回范围过滤、白名单化且可审计的任务事实。响应 MUST 根据当前用户权限和保留策略脱敏消息与结果，并 MUST NOT 返回 Credential、MCP Token、连接配置、私有推理或未脱敏上游响应。

#### Scenario: 查询已存在且有权任务
- **WHEN** Job 创建人、目标 Application 运维人员或平台管理员查询允许范围内的 Job
- **THEN** 系统返回 Job、Session、Application/Agent Publication、状态、重试、结果/错误安全摘要和时间戳

#### Scenario: 查询不存在或无权任务
- **WHEN** 当前用户查询不存在或不在其可见范围内的 Job
- **THEN** 系统返回不可枚举的 not found/拒绝语义，不泄露 Job 是否存在

### Requirement: 失败 job 的 tool-calls 必须包含真实运行时已发生工具调用
系统 SHALL 在真实 TypeScript Agent Runtime 失败、timeout、最大轮次耗尽或被 retry service 重新入队后，仍通过 Tool Call 查询返回失败前已经发生并被持久化的 MCP 调用安全摘要。

#### Scenario: 最大轮次耗尽后查询工具调用
- **WHEN** 一个真实 Agent Job 因最大轮次耗尽失败并进入 FAILED 或 retry-pending 状态
- **THEN** 查询返回该次执行中已经发生的 ONES、Database、Redis 或 Loki MCP Tool 调用摘要

#### Scenario: retry-pending 状态保留上次失败证据
- **WHEN** Job 被 retry service 重新置为 `PENDING` 且保留上次安全错误
- **THEN** Tool Call 查询仍返回上次执行失败前的调用摘要，便于判断是否继续重试

#### Scenario: 失败工具调用摘要仍然脱敏
- **WHEN** 失败路径持久化 MCP Tool Call
- **THEN** 响应不得包含密钥、Token、连接信息、完整 raw payload、私有推理或未受限上游错误正文

### Requirement: Debug API documentation shall cover real-tools verification
系统 SHALL 在调试 API 文档中提供真实 MCP Tool 验证流程，覆盖创建 Job、轮询状态、查询 Step、查询 Tool Call，并说明如何确认调用来自受信 MCP Server、精确 Tool Publication 和冻结 Resource Generation。

#### Scenario: 查询真实 MCP Tool Calls
- **WHEN** 开发者按文档提交合成数据 Debug Job
- **THEN** Tool Call 查询返回 Tool 名称、受信 Server 标识、Publication/Generation 安全标识、状态、耗时、风险等级和脱敏摘要

#### Scenario: MCP 工具链失败排查
- **WHEN** Debug Job 失败
- **THEN** 文档指引开发者检查 Job、Worker、TypeScript Runtime、MCP Server、Tool Publication、Resource Generation 和 Credential 状态，不再检查 Internal API Platform

### Requirement: Debug jobs shall support safe real-model smoke testing
系统 SHALL 支持使用 Debug API 提交真实模型 smoke test，但测试流程 MUST 明确要求使用合成问题、合成数据或已脱敏证据，并 MUST 只使用当前 Publication 允许的 MCP Tool。

#### Scenario: 提交安全真实模型测试任务
- **WHEN** 开发者显式启用真实模型并提交 Debug Job
- **THEN** 文档化流程使用合成或已脱敏测试问题，且 Step/Tool Call 可确认模型只调用受信 MCP 链路

### Requirement: Debug smoke documentation shall include failure triage
系统 SHALL 在 smoke 文档中记录失败排查顺序，覆盖 Job detail、Worker logs、RabbitMQ 消费、TypeScript Runtime、MCP 配置、MCP Server、Resource Generation、Credential 状态和 Delivery；文档 MUST NOT 要求恢复或检查 Internal API Platform。

#### Scenario: Smoke job fails
- **WHEN** Smoke Job 返回 `FAILED`、`TIMEOUT` 或长时间停留在 `PENDING`
- **THEN** 文档提供命令定位失败发生在 API 接收、RabbitMQ、Worker、Runtime、MCP Server、Resource/Credential 或 Delivery 哪一段

### Requirement: 运行中心必须提供受限调试入口
前端 SHALL 提供“调试与运行历史 → 发起调试”，只列出当前用户可用的已激活 Application、Agent 入口和 Execution Scope；默认 Delivery 为 none，可选 Delivery MUST 来自当前 Publication 已授权 Binding。客户端 MUST NOT 覆盖主体、Publication、Resource、Credential、MCP Server 或 Tool allowlist。

#### Scenario: 用户成功发起调试
- **WHEN** 用户选择允许的 Application、Execution Scope 并提交消息和幂等键
- **THEN** 服务端从当前登录主体和活动 Publication 解析冻结事实，创建 Job 后页面导航到受保护详情

#### Scenario: 用户选择可选投递
- **WHEN** 用户选择当前 Application Publication 已有的授权 Delivery Binding
- **THEN** 系统固化该 Binding；页面不得允许填写任意 Connector 或目标地址

#### Scenario: 客户端覆盖 MCP 运行依赖
- **WHEN** 调试请求提交 Resource、Credential、MCP Server、Tool 或 Publication revision
- **THEN** 系统拒绝越权字段且不创建 Job

## ADDED Requirements

### Requirement: 运行历史页面提供范围过滤列表和详情
系统 SHALL 提供 Job/Session 历史列表和详情，支持按允许的 Application、Agent、状态、来源和时间范围筛选，并 MUST 使用稳定分页、确定性排序和不可枚举 ID。

#### Scenario: 用户查看自己的历史
- **WHEN** 普通用户打开运行历史
- **THEN** 页面只列出其有权查看的 Job/Session，并可进入脱敏详情、Step、Tool Call 和 Delivery 时间线

#### Scenario: Application 运维人员查看历史
- **WHEN** 用户具有目标 Application 的运维读取权限
- **THEN** 页面列出该 Application 范围内的 Job，不泄露其它 Application 的数量或错误

### Requirement: Job 详情展示冻结运行依赖摘要
系统 SHALL 在 Job 详情只读展示创建时冻结的 Application/Agent Publication、主体快照、MCP Server/Tool、Resource Generation 和 Delivery Binding 安全标识，且 MUST NOT 允许从历史页面修改或重新解析这些事实。

#### Scenario: 当前 Publication 已变化
- **WHEN** 管理员查看由旧 Publication 创建的历史 Job
- **THEN** 页面显示旧冻结版本和“历史快照”标记，不自动替换为当前 Publication

### Requirement: 取消 Job 只适用于允许取消的状态
系统 SHALL 只允许具备权限的用户取消处于可取消状态的 Job，并 MUST 通过现有 Job 状态机、expected revision、幂等和审计执行。取消不得删除历史消息、Step、Tool Call 或 Delivery 证据。

#### Scenario: 取消正在等待的 Job
- **WHEN** 有权限用户取消 `PENDING` Job 且 revision 当前
- **THEN** 系统进入受控取消状态、阻止后续执行并保留历史证据

#### Scenario: 取消终态 Job
- **WHEN** 用户尝试取消已成功、失败或已取消 Job
- **THEN** 系统拒绝状态变更且不改写历史

