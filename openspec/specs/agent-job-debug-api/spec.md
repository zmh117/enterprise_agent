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

