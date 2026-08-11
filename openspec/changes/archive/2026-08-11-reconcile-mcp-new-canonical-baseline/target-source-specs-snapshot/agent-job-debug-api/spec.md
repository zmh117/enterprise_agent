# agent-job-debug-api Specification

## Purpose
TBD - created by archiving change wire-rabbitmq-agent-job-flow. Update Purpose after archive.
## Requirements
### Requirement: 调试 API 必须能创建 Agent Job
系统 SHALL 提供受登录态保护的调试 Job 创建 API，用于在不依赖外部 Channel 的情况下创建只读诊断 Job，并复用业务应用发布、严格 RBAC、审计、持久化和 Outbox 链路。API MUST 使用当前登录用户，且只接受该用户有权使用的已发布业务应用、Execution Scope、消息和幂等键。

#### Scenario: 当前用户提交调试问题
- **WHEN** 已登录用户具备 `agent.debug.execute`，并选择有权访问的业务应用发布和 Execution Scope
- **THEN** 系统以当前用户身份创建隔离 Session、Agent Job、用户消息、授权快照、审计和 Job Dispatch Outbox，并返回 `job_id`

#### Scenario: 请求试图覆盖运行身份或资源
- **WHEN** 调试请求提交任意 `user_id`、Agent ID、Resource Revision、Connector 或自定义 reply route
- **THEN** 系统必须拒绝这些越权字段，且不得创建 Job 或 Outbox event

#### Scenario: 调试 API 使用幂等键
- **WHEN** 同一用户在同一发布版本和 Execution Scope 下两次提交相同 `idempotency_key`
- **THEN** 系统返回同一个 `job_id`，且不重复创建 Job 或 Outbox event

### Requirement: 调试 API 必须执行权限校验
系统 SHALL 在创建调试 Job 前校验登录态、`agent.debug.execute`、业务应用角色、应用发布可用性和 Execution Scope；任一授权缺失都必须 fail closed。

#### Scenario: 授权用户创建任务
- **WHEN** 当前用户拥有调试权限、目标应用角色和目标 Execution Scope
- **THEN** 系统创建并通过 Outbox 调度 Agent Job

#### Scenario: 未授权用户被拒绝
- **WHEN** 当前用户缺少任一所需权限或范围
- **THEN** 系统返回安全拒绝，且不创建 Session、Job、消息或 Outbox event

### Requirement: Job 查询 API 必须返回任务详情
系统 SHALL 提供 `GET /api/agent/jobs/{job_id}`，返回 Agent job 的可审计详情。

#### Scenario: 查询已存在任务
- **WHEN** 调用 `GET /api/agent/jobs/{job_id}` 查询已存在 job
- **THEN** 系统返回 job id、session id、user id、project code、source、user message、status、retry count、result、error message 和时间戳

#### Scenario: 查询不存在任务
- **WHEN** 调用 `GET /api/agent/jobs/{job_id}` 查询不存在 job
- **THEN** 系统返回 404 或等价的 not found 响应

### Requirement: Step 查询 API 必须返回执行步骤
系统 SHALL 提供 `GET /api/agent/jobs/{job_id}/steps`，按创建顺序返回该 job 的可审计执行步骤。

#### Scenario: 查询任务步骤
- **WHEN** job 已经被 worker 执行并产生 `agent_step`
- **THEN** 系统返回步骤列表，包含 step type、title、content 和 created at

### Requirement: Tool Call 查询 API 必须返回安全摘要
系统 SHALL 提供 `GET /api/agent/jobs/{job_id}/tool-calls`，返回工具调用的脱敏请求摘要、响应摘要、状态、耗时、风险等级和审计关联。

#### Scenario: 查询工具调用
- **WHEN** job 执行过程中产生 `agent_tool_call`
- **THEN** 系统返回工具调用列表，且响应 MUST 不包含未脱敏 raw payload

### Requirement: 调试 API 必须支持本地 curl 验证
系统 SHALL 在 README 或等价文档中提供本地 curl 验证步骤，覆盖创建 job、轮询 job 状态、查询 steps 和查询 tool calls。

#### Scenario: 文档化 curl 验证
- **WHEN** 开发者按文档启动 Docker Compose 并执行 curl 命令
- **THEN** 开发者可以观察到 job 从 `PENDING` / `RUNNING` 变为 `SUCCEEDED`，并看到最终报告、步骤和工具调用摘要

### Requirement: 失败 job 的 tool-calls 必须包含真实运行时已发生工具调用
系统 SHALL 在真实 Claude runtime 失败、timeout、最大轮次耗尽或被 retry service 重新入队后，仍通过 `GET /api/agent/jobs/{job_id}/tool-calls` 返回失败前已经发生并被持久化的工具调用安全摘要。

#### Scenario: 最大轮次耗尽后查询工具调用
- **WHEN** 一个真实 Claude job 因最大轮次耗尽失败并进入 FAILED 或 retry-pending 状态
- **THEN** 调试 API 返回该次执行中已经发生的数据库、Redis、Loki 或 schema directory 工具调用摘要

#### Scenario: retry-pending 状态保留上次失败证据
- **WHEN** job 被 retry service 重新置为 `PENDING` 且保留上次 `error_message`
- **THEN** `GET /tool-calls` 仍返回上次执行失败前的工具调用摘要，便于开发者判断是否应继续重试

#### Scenario: 失败工具调用摘要仍然脱敏
- **WHEN** 失败路径持久化工具调用
- **THEN** 调试 API 返回的请求和响应摘要不得包含密钥、完整 raw payload、私有推理或未受限上游错误正文

### Requirement: Debug API documentation shall cover real-tools verification
系统 SHALL 在调试 API 文档中提供 real-tools 验证流程，覆盖创建 job、轮询状态、查询 steps、查询 tool-calls，并说明如何确认工具调用来自 `internal-api-platform`。

#### Scenario: 查询 real-tools tool calls
- **WHEN** 开发者按 real-tools 文档提交 debug job
- **THEN** `GET /api/agent/jobs/{job_id}/tool-calls` SHALL 返回工具名称、状态、耗时、风险等级、脱敏请求摘要、响应摘要和 metadata source

#### Scenario: 工具链失败排查
- **WHEN** debug job 失败
- **THEN** 文档 SHALL 指引开发者检查 job 状态、worker 日志、tool-calls、Internal API Platform health 和 Loki 诊断 endpoint

### Requirement: Debug jobs shall support safe real-model smoke testing
系统 SHALL 支持使用 debug API 提交真实模型 smoke test，但测试流程 MUST 明确要求使用合成问题、合成日志或脱敏证据。

#### Scenario: 提交安全真实模型测试任务
- **WHEN** 开发者启用 `FEATURE_REAL_CLAUDE=true` 并提交 debug job
- **THEN** 文档化流程 SHALL 使用合成或已脱敏测试问题
- **AND** job steps/tool-calls 可用于确认模型调用了 real-tools 工具链

### Requirement: Debug API shall prove smoke job execution
系统 SHALL 在 compose smoke 流程中使用 Debug API 创建 Agent job，并通过 job detail、steps 和 tool-calls 查询证明 worker 已消费并完成任务。

#### Scenario: Smoke creates and polls job
- **WHEN** 开发者调用 `POST /api/agent/jobs` 提交合成诊断问题
- **THEN** API SHALL 返回 `job_id`，并且文档 SHALL 指引开发者轮询 `GET /api/agent/jobs/{job_id}` 直到 `SUCCEEDED` 或明确失败状态

#### Scenario: Smoke inspects steps and tool calls
- **WHEN** job 进入终态
- **THEN** 开发者 SHALL 能调用 `GET /api/agent/jobs/{job_id}/steps` 和 `GET /api/agent/jobs/{job_id}/tool-calls` 查看可审计摘要

### Requirement: Debug smoke documentation shall include failure triage
系统 SHALL 在 smoke 文档中记录失败排查顺序，覆盖 job detail、worker logs、RabbitMQ 消费、runtime config degraded、secret 状态和 Internal API Platform 健康状态。

#### Scenario: Smoke job fails
- **WHEN** smoke job 返回 `FAILED`、`TIMEOUT` 或长时间停留在 `PENDING`
- **THEN** 文档 SHALL 提供 curl/docker compose 命令定位失败发生在 API 接收、RabbitMQ、worker、Claude runtime、secret resolver 或 internal tools 哪一段

### Requirement: 调试查询必须受当前用户授权
Job、Step 和 Tool Call 查询 MUST 要求登录，并仅允许 Job 创建人、具备该业务应用运维权限的用户或平台管理员访问；响应必须继续脱敏。

#### Scenario: 用户查询其他应用的调试 Job
- **WHEN** 当前用户不是创建人且没有目标应用运维权限
- **THEN** 系统必须拒绝查询，并且不得泄露 Job 是否存在的敏感细节

### Requirement: 运行中心必须提供受限调试入口
前端 SHALL 提供“运行中心 → 发起调试”，只列出当前用户可用的已发布业务应用与 Execution Scope；默认 Delivery 为 none，可选 Delivery 必须来自现有已授权 binding。

#### Scenario: 用户成功发起调试
- **WHEN** 用户选择允许的应用、范围并提交消息
- **THEN** 页面创建 Job 后导航到受保护的 Job 详情页

#### Scenario: 用户选择可选投递
- **WHEN** 用户选择当前应用发布已有的授权 Delivery binding
- **THEN** 系统固化该 binding；页面不得允许填写任意 Connector 或目标地址
