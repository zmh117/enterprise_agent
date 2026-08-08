## MODIFIED Requirements

### Requirement: SDK failures are classified for retry policy
系统 SHALL 根据结构化语义分类 Claude Agent SDK/CLI 故障：网络、429/5xx、transport、CLI JSON decode 和可确认的瞬时 provider 故障映射为可重试；缺少凭据、CLI 不存在、明确无效模型配置和工具策略拒绝映射为不可重试；矛盾的 error result MUST 使用独立错误码并只允许受最大次数约束的有限重试。

#### Scenario: Transient process error triggers retry
- **WHEN** SDK 返回网络、rate limit、overloaded、transport 或 CLI JSON decode 瞬时错误
- **THEN** runtime 抛出带稳定错误码的 `RetryableExecutionError`，由 Job retry service 延迟调度

#### Scenario: SDK reports contradictory success error
- **WHEN** SDK/CLI 返回 `is_error=true`，但 errors 为空且 subtype 为 `success`，或抛出等价的 `Claude Code returned an error result: success`
- **THEN** runtime 不把该结果作为最终答案，映射为 `claude_inconsistent_result`，生成用户可理解的安全消息，并在最大重试次数内有限重试

#### Scenario: Contradictory result exhausts retries
- **WHEN** 同一 Job 持续收到 `claude_inconsistent_result` 并达到最大重试次数
- **THEN** Job 进入终态失败，不再调用模型，并通过原 reply route 发送一次安全失败通知

#### Scenario: Configuration failure does not retry
- **WHEN** runtime 确认缺少凭据、CLI runtime 不存在或模型配置明确无效
- **THEN** runtime 返回不可重试配置错误，不进入延迟 retry queue

#### Scenario: Policy violation does not retry as transport error
- **WHEN** 工具调用因为 SQL policy、只读边界或权限被拒绝
- **THEN** runtime 将安全拒绝结果返回模型或终止本次执行，不将其误分类为 SDK transport retry

## ADDED Requirements

### Requirement: Claude 错误诊断元数据必须有界、脱敏且可关联
系统 SHALL 为真实 Claude/DeepSeek 失败记录可关联 Job 的安全诊断元数据，至少包括稳定错误码、异常类、SDK/CLI 版本、模型策略引用、provider host 安全摘要、脱敏 subtype/errors 和有界 stderr；系统 MUST NOT 持久化凭据、完整敏感 URL、完整 prompt、未受限工具结果或私有推理。

#### Scenario: Inconsistent SDK result is audited
- **WHEN** runtime 识别 `claude_inconsistent_result`
- **THEN** 审计记录 Job、correlation ID、SDK/CLI 版本、模型策略引用、脱敏错误标志和稳定错误码，不记录 API key、认证 token 或 chain-of-thought

#### Scenario: CLI stderr contains credentials
- **WHEN** CLI stderr 包含 API key、authorization header、token 或带 secret/query 的 URL
- **THEN** 系统在写入 Job step、error message 或审计前屏蔽凭据并截断到配置上限

### Requirement: 真实模型兼容性 smoke 必须显式启用且使用安全输入
系统 SHALL 提供显式 opt-in 的真实模型 smoke，用合成或已脱敏问题对照 provider/model/SDK 组合；常规单元测试、Compose 启动和 readiness MUST NOT 自动调用外部模型。

#### Scenario: 常规测试运行
- **WHEN** 开发者运行默认测试或启动 readiness
- **THEN** 系统使用 fake/stub 或仅报告配置状态，不产生外部模型请求和费用

#### Scenario: 开发者显式运行对照 smoke
- **WHEN** 开发者提供明确开关和凭据并选择当前 DeepSeek 配置与基线配置
- **THEN** smoke 使用 synthetic prompt，分别记录成功或安全错误分类，不输出凭据和完整 provider 响应
