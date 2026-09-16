## ADDED Requirements

### Requirement: 日志扫描失败必须保留安全可行动的错误事实
Runtime SHALL 将已知日志扫描错误码、固定中文提示及重试分类传递至既有工具事件和控制面安全摘要；参数/路径等确定性错误 MUST 为 `NEVER`，不得被通用瞬时失败覆盖。普通事件 MUST NOT 因此保存实际路径、关键词、日志正文或动态异常文本。未知错误码 MUST 保持安全通用回退；其他工具和 Job 终态语义保持不变。

#### Scenario: 输入与路径错误可定位
- **WHEN** File bridge 返回 `log_evidence_input_invalid` 或 `log_evidence_path_invalid`
- **THEN** SDK 事件至控制面工具失败摘要保留对应码和固定中文纠正提示，retry class 为 `NEVER`，不再只显示 `runtime_tool_failed`

#### Scenario: 伪造错误载荷不进入普通审计
- **WHEN** 扫描结果载荷带有未知错误码或伪造的动态错误文本
- **THEN** Runtime 不将其原样传播到普通工具事件，已知码只使用固定提示，未知码使用通用失败

#### Scenario: 工具失败与 Job 完成分离
- **WHEN** 扫描失败后 Agent 使用已授权的 Grep/Read 完成有界分析
- **THEN** 保留扫描工具失败事实，但不因此改写 Job 已有成功终态规则，成功状态不得被解释为扫描成功或全量语义覆盖
