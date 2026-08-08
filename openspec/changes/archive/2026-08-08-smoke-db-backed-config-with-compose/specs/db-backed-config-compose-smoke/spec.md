## ADDED Requirements

### Requirement: Compose smoke shall verify DB-backed config end to end
系统 SHALL 提供 Docker Compose 下的 smoke 验证流程，覆盖 PostgreSQL migration、api-server、agent-worker、Web-managed secret、DB-backed runtime config overlay、RabbitMQ 消费和 Agent job 完成状态。

#### Scenario: Smoke starts required services
- **WHEN** 开发者按 smoke 文档启动 Docker Compose
- **THEN** `postgres`、`rabbitmq`、`api-server` 和 `agent-worker` MUST 处于 running/healthy 状态

#### Scenario: Smoke proves runtime config source
- **WHEN** 开发者写入 runtime config 并重启 `api-server` 和 `agent-worker`
- **THEN** `/api/ready` SHALL 返回 `runtime_config.source=database` 或等价的 DB-backed source 信息

### Requirement: Compose smoke shall be reproducible with curl
系统 SHALL 提供中文 curl 命令，逐步验证 secret 创建、runtime config 写入、服务重启、ready 检查、job 创建、job 轮询、steps 查询和 tool-calls 查询。

#### Scenario: Developer follows curl document
- **WHEN** 开发者从文档第一条 curl 命令按顺序执行到最后一条
- **THEN** 开发者 SHALL 能获得 `job_id`，并能查询该 job 的状态、最终结果、steps 和 tool-calls

#### Scenario: Curl output records expected fields
- **WHEN** smoke 文档展示每一步预期结果
- **THEN** 文档 MUST 标明关键字段，例如 `secret_ref`、`runtime_config.source`、`job_id`、`status`、`result`、`steps` 和 `tool_calls`

### Requirement: Compose smoke shall avoid secret leakage
系统 SHALL 在 smoke 文档和可选脚本中避免打印真实 secret 明文，并提供响应检查，确认 DeepSeek API key 或 token 没有出现在 API 响应、runtime config snapshot、job steps 或 tool-calls 中。

#### Scenario: Secret create response is inspected
- **WHEN** smoke 创建 `deepseek_api_key`
- **THEN** 响应 SHALL 只展示 `secret://platform/deepseek_api_key`、版本、configured 状态和脱敏摘要，不得包含原始 API key

#### Scenario: Job debug output is inspected
- **WHEN** smoke 查询 job steps 和 tool-calls
- **THEN** 输出 MUST 不包含 DeepSeek API key、Anthropic token、数据库密码、Redis 密码或未脱敏 raw payload

### Requirement: Compose smoke shall document safe real-model mode
系统 SHALL 将真实 DeepSeek/Claude smoke 标记为显式可选路径，并要求使用 synthetic 或已脱敏输入。

#### Scenario: Real model mode is enabled
- **WHEN** 开发者选择启用 `FEATURE_REAL_CLAUDE=true`
- **THEN** 文档 MUST 提醒外部模型数据出境风险，并要求使用合成问题或脱敏上下文

#### Scenario: Default smoke does not require external model
- **WHEN** 开发者执行默认 smoke 流程
- **THEN** 流程 MUST 不要求真实 DeepSeek API key，也不得调用外部模型 API
