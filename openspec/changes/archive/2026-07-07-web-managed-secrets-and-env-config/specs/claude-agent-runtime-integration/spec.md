## ADDED Requirements

### Requirement: Claude runtime can load model settings from DB-backed runtime config
系统 SHALL 允许真实 Claude/DeepSeek runtime 从 DB-backed runtime config 加载 base URL、model、默认模型、effort level、max turns 和 timeout，并保留 env fallback。

#### Scenario: DB config selects DeepSeek model
- **WHEN** runtime config 配置 `ANTHROPIC_BASE_URL=https://api.deepseek.com/anthropic` 和 `ANTHROPIC_MODEL=deepseek-v4-pro[1m]`
- **THEN** RealClaudeCodeAgentClient 使用 DB-backed 配置构造 SDK runtime

#### Scenario: DB config missing
- **WHEN** DB-backed Claude runtime config 不存在
- **THEN** runtime 使用现有 env/default 逻辑，并在 ready 输出中标记来源

### Requirement: Claude runtime API key can use Web-managed secret
系统 SHALL 允许 `ANTHROPIC_API_KEY` / `ANTHROPIC_AUTH_TOKEN` 通过 Web-managed secret ref 配置，并且 ready/health 只能报告是否 configured，不能泄漏 key。

#### Scenario: API key is stored as secret ref
- **WHEN** runtime config 将 `ANTHROPIC_API_KEY` 指向 `secret://platform/deepseek_api_key`
- **THEN** RealClaudeCodeAgentClient 仅在调用 SDK 前解析 secret，日志和 ready 输出不包含明文 key

#### Scenario: API key secret is missing
- **WHEN** `FEATURE_REAL_CLAUDE=true` 但 API key secret 无法解析
- **THEN** ready 或执行前校验返回安全配置错误，不调用外部模型 API
