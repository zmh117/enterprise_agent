## ADDED Requirements

### Requirement: Claude runtime DB-backed settings shall be smoke-verifiable
系统 SHALL 提供 smoke 流程，验证 Claude/DeepSeek runtime 的 base URL、model、max turns 和 API key secret ref 可从 DB-backed runtime config 进入 `agent-worker`。

#### Scenario: Stub runtime validates config overlay without external API
- **WHEN** 默认 smoke 使用 `FEATURE_REAL_CLAUDE=false`
- **THEN** 流程 SHALL 仍能验证 DB-backed runtime config 被 `api-server` 和 `agent-worker` 读取，而不调用外部模型 API

#### Scenario: Optional real DeepSeek runtime uses secret ref
- **WHEN** 开发者显式启用 `FEATURE_REAL_CLAUDE=true` 并配置 `ANTHROPIC_API_KEY=secret://platform/deepseek_api_key`
- **THEN** `agent-worker` SHALL 在执行前通过 SecretResolver 解析 key，并且 ready/job/debug 输出 MUST 不包含明文 key

### Requirement: Real-model smoke shall fail safely when credentials are invalid
系统 SHALL 在真实 DeepSeek/Claude smoke 中，当 API key 缺失、禁用或仍为占位符时，返回安全配置错误并避免无限重试。

#### Scenario: API key secret is disabled before job execution
- **WHEN** `FEATURE_REAL_CLAUDE=true` 且 runtime config 指向 disabled secret
- **THEN** Agent job SHALL 失败为安全配置错误，且 debug API SHALL 提供可排查的 job/error 信息但不泄漏 key
