## ADDED Requirements

### Requirement: 失败路径必须保留真实运行时工具事件
系统 SHALL 在真实 Claude SDK 执行失败、超时或达到最大轮次时，保留失败前已经发生的工具调用安全摘要，并将这些摘要交给应用层持久化。工具事件 MUST 不包含私有推理、密钥、未脱敏 raw payload 或不受限响应正文。

#### Scenario: 最大轮次耗尽后保留工具轨迹
- **WHEN** `RealClaudeCodeAgentClient.run()` 在一个已经调用过内部工具的 job 中收到 `Reached maximum number of turns` 类错误
- **THEN** 系统持久化失败前已收集的工具调用摘要，并在 job step 中记录安全失败原因

#### Scenario: SDK timeout 后保留工具轨迹
- **WHEN** 真实 SDK 会话超时且超时前已经调用过内部工具
- **THEN** 系统持久化已完成或已失败的工具调用摘要，并继续按 timeout 错误分类处理 job

### Requirement: 最大轮次耗尽必须区别于瞬时传输故障
系统 SHALL 将明确的工具循环最大轮次耗尽识别为诊断循环收敛失败，而不是普通网络、CLI transport 或上游 5xx 瞬时故障。该错误 MUST 带有安全错误码或等价分类，供 retry 策略避免立即重复消耗同一无效工具循环。

#### Scenario: 最大轮次耗尽不作为普通 transient 重试
- **WHEN** Claude SDK 返回明确的 `Reached maximum number of turns` 错误
- **THEN** job 不得仅因为该错误被当作普通 transient transport failure 立即重复重试

#### Scenario: 网络错误仍可重试
- **WHEN** Claude SDK 返回网络超时、429、502、503、transport connection 或 CLI JSON decode transient 错误
- **THEN** 系统仍按现有 retryable 语义处理该故障
