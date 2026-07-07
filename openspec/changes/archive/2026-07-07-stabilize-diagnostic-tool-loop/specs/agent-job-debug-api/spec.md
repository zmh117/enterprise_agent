## ADDED Requirements

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
