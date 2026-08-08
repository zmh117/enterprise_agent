## ADDED Requirements

### Requirement: Secrets shall be smoke-verifiable through Compose curl
系统 SHALL 允许开发者在 Docker Compose 环境中通过 curl 创建、查询、轮换和禁用 Web-managed secret，并验证返回内容不泄漏明文。

#### Scenario: Compose curl creates DeepSeek secret
- **WHEN** 开发者调用 `POST /api/platform/secrets` 创建 `deepseek_api_key`
- **THEN** API SHALL 返回 `secret://platform/deepseek_api_key` 和脱敏摘要，且响应 MUST 不包含提交的原始 key

#### Scenario: Compose curl disables secret safely
- **WHEN** 开发者调用 `POST /api/platform/secrets/deepseek_api_key/disable`
- **THEN** 后续 runtime 解析该 secret SHALL 失败为安全配置错误，且不得回退到旧版本或空 key

### Requirement: Secret smoke documentation shall protect operator input
系统 SHALL 在 smoke 文档中要求开发者通过环境变量或交互输入提供真实 key，MUST NOT 要求把真实 key 写入命令历史、README、OpenSpec artifact 或 git tracked 文件。

#### Scenario: Real key is supplied for optional smoke
- **WHEN** 开发者执行真实 DeepSeek 可选验证
- **THEN** 文档 SHALL 使用 `DEEPSEEK_API_KEY` 或等价本地环境变量占位，不得展示真实 key
