## ADDED Requirements

### Requirement: Real model tests shall use synthetic or sanitized evidence by default
系统 SHALL 默认只使用合成日志、合成业务问题或已脱敏工具摘要执行真实 Claude/DeepSeek + real-tools 端到端测试。

#### Scenario: 使用合成日志测试
- **WHEN** 开发者运行真实模型 smoke test
- **THEN** 测试输入和工具证据 SHALL 来自合成数据或明确标记为可外发的测试数据

#### Scenario: 未确认真实业务日志
- **WHEN** 测试会把真实业务日志或内部敏感证据发送到外部模型
- **THEN** 系统文档和测试流程 MUST 要求先获得显式确认

### Requirement: Tool summaries sent to external models shall be redacted
系统 SHALL 在真实模型运行时对发送给外部模型的工具摘要执行脱敏，至少覆盖 token、password、secret、authorization、个人敏感信息和过长日志片段。

#### Scenario: 工具返回包含敏感字段
- **WHEN** 工具结果中包含 token、password、secret 或 authorization 类字段
- **THEN** 发送给模型和持久化到审计摘要的内容 MUST 使用脱敏值

#### Scenario: 工具返回过长日志
- **WHEN** Loki 或数据库工具返回超过配置上限的结果
- **THEN** 系统 SHALL 截断结果并标记 truncated

### Requirement: Real model safety mode shall be visible in documentation
系统 SHALL 在 README 或测试文档中明确说明 `FEATURE_REAL_CLAUDE=true` 与 DeepSeek/Claude API 环境变量的风险边界和推荐测试数据策略。

#### Scenario: 开发者启用真实模型
- **WHEN** 开发者准备设置 `FEATURE_REAL_CLAUDE=true`
- **THEN** 文档 SHALL 提醒该模式会调用外部模型 API，并要求使用合成或脱敏数据

#### Scenario: 只验证工具链
- **WHEN** 开发者只需要验证真实 Loki/Internal API Platform 链路
- **THEN** 文档 SHALL 提供 `FEATURE_REAL_CLAUDE=false` 的测试路径
