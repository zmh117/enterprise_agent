## ADDED Requirements

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
