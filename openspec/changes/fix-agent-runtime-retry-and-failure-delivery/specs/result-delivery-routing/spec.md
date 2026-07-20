## MODIFIED Requirements

### Requirement: Agent results are delivered through reply routes
系统 SHALL 根据 Agent Job 持久化的 `reply_route` 投递最终成功报告或终态安全失败通知，而不是由 Agent runtime 直接调用特定平台 client；中间 retry 状态 MUST 不触发外部通知。

#### Scenario: Successful job has DingTalk Stream delivery
- **WHEN** Agent Job 成功且 `reply_route.type` 为 `dingtalk_stream_session_webhook`
- **THEN** 系统通过原会话 session webhook 发送最终报告并记录 delivery attempt 和 chunk

#### Scenario: Terminal failed job has DingTalk Stream delivery
- **WHEN** Agent Job 因不可重试错误或重试耗尽进入 `FAILED`，且原 session webhook 仍有效
- **THEN** 系统通过原 reply route 发送一次包含安全错误码、用户可理解原因和 Job 追踪标识的失败通知

#### Scenario: Job is waiting for retry
- **WHEN** Agent Job 处于 `RETRY_WAIT`
- **THEN** 系统不发送成功或失败通知，等待后续执行达到终态

#### Scenario: Terminal failed job has email delivery
- **WHEN** Agent Job 最终失败且 `reply_route.type` 为 `email`
- **THEN** 系统通过 email delivery adapter 发送一次安全失败通知并记录投递结果

### Requirement: Delivery failures do not re-execute Agent jobs
系统 SHALL 将 Delivery 失败与 Agent 执行失败分开处理；成功报告或终态失败通知的 Delivery 失败 MUST NOT 触发 Agent Job 重新执行，也不得修改已经到达的 Job 执行终态。

#### Scenario: Successful result delivery returns transient failure
- **WHEN** Agent Job 已经 `SUCCEEDED` 但 Delivery adapter 返回超时或临时网络错误
- **THEN** 系统记录 delivery failed 或独立 delivery retry 状态，Agent Job 保持 `SUCCEEDED` 且模型不被重新调用

#### Scenario: Failure notification delivery returns transient failure
- **WHEN** Agent Job 已经 `FAILED` 或 `TIMEOUT` 但安全失败通知投递失败
- **THEN** 系统记录 delivery failure，Job 保持原终态，且不创建 Agent execution retry

#### Scenario: DingTalk session webhook expired
- **WHEN** 终态通知使用的 `dingtalk_stream_session_webhook` 已过期
- **THEN** 系统记录脱敏 delivery failure，不自动切换到未在原 reply route 中授权的其他 DingTalk 目标，也不重新运行 Agent

#### Scenario: Duplicate RabbitMQ job delivery after terminal result
- **WHEN** 同一个已 `SUCCEEDED`、`FAILED` 或 `TIMEOUT` Job 被重复投递给 Worker
- **THEN** 系统不重新执行 Agent，也不重复发送已经成功完成的 delivery attempt

## ADDED Requirements

### Requirement: 终态失败通知必须安全且幂等
系统 SHALL 对每个 Job 的终态失败通知实施持久化幂等；通知内容 MUST 不包含堆栈、API key、认证 token、完整 provider URL、完整 session webhook、内部原始 payload 或私有推理。

#### Scenario: 同一终态失败被处理两次
- **WHEN** 重复 dead-letter、Worker 重启或恢复操作再次处理已经成功发送失败通知的 Job
- **THEN** 系统检测已完成 delivery attempt，不再次发送相同终态通知

#### Scenario: 安全失败原因被构建
- **WHEN** Claude runtime 因 `claude_inconsistent_result` 最终失败
- **THEN** 用户通知说明模型运行暂时失败并附 Job 追踪标识，不直接输出矛盾的 `error result: success`、CLI stderr 或内部异常堆栈
