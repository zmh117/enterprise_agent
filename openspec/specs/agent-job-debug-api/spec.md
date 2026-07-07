# agent-job-debug-api Specification

## Purpose
TBD - created by archiving change wire-rabbitmq-agent-job-flow. Update Purpose after archive.
## Requirements
### Requirement: 调试 API 必须能创建 Agent Job
系统 SHALL 提供 `POST /api/agent/jobs`，用于在不依赖钉钉的情况下创建只读诊断 Agent job，并复用现有权限、审计、持久化和消息投递链路。

#### Scenario: 提交调试问题
- **WHEN** 调用 `POST /api/agent/jobs` 并提供 `message`、`user_id`、`conversation_id` 和 `project_code`
- **THEN** 系统创建 Agent session、Agent job、用户消息和审计记录，并返回 `job_id`、初始状态和接收提示

#### Scenario: 调试 API 使用幂等键
- **WHEN** 两次调用 `POST /api/agent/jobs` 使用相同 `idempotency_key`
- **THEN** 系统返回同一个 `job_id`，且不重复创建 job 或重复发布正常队列消息

### Requirement: 调试 API 必须执行权限校验
系统 SHALL 对调试 API 创建的 job 执行用户和项目权限校验，不得绕过 `PermissionService`。

#### Scenario: 授权用户创建任务
- **WHEN** 调试 API 请求中的用户被允许访问目标 `project_code`
- **THEN** 系统创建并投递 Agent job

#### Scenario: 未授权用户被拒绝
- **WHEN** 调试 API 请求中的用户未被允许访问目标 `project_code`
- **THEN** 系统拒绝请求，返回安全错误信息，且不创建 job、不发布队列消息

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

