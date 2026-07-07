## ADDED Requirements

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
