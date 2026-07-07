## ADDED Requirements

### Requirement: Real-tools profile shall start the topology-aware platform
系统 SHALL 提供明确的 `real-tools` 运行模式，用于启动拓扑化 `internal-api-platform`，并使 `api-server` 与 `agent-worker` 通过 `INTERNAL_API_BASE_URL=http://internal-api-platform:9000` 调用该平台。

#### Scenario: 启动 real-tools 主线
- **WHEN** 开发者按文档使用 `real-tools` profile 启动 Docker Compose
- **THEN** 系统启动 `internal-api-platform`、`api-server`、`agent-worker`、`postgres` 和 `rabbitmq`
- **AND** `agent-worker` 环境变量中的 `INTERNAL_API_BASE_URL` 指向 `http://internal-api-platform:9000`

#### Scenario: real-tools 不依赖 local platform
- **WHEN** 系统运行在 `real-tools` 模式
- **THEN** Agent 工具请求 SHALL 进入 `internal-api-platform`
- **AND** 系统 MUST NOT 要求同时启动 `local-internal-api-platform`

### Requirement: Runtime modes shall be documented and distinguishable
系统 SHALL 文档化 fake、mock-tools、local-tools、real-tools 四种运行模式的用途、启动命令、关键环境变量和验收标准。

#### Scenario: 开发者选择运行模式
- **WHEN** 开发者阅读 README 或等价文档
- **THEN** 文档明确说明 fake 用于无外部工具、mock-tools 用于假证据、local-tools 用于宿主 Loki 快速联调、real-tools 用于正式拓扑化工具平台

#### Scenario: 错误 profile 配置可被识别
- **WHEN** `FEATURE_REAL_INTERNAL_TOOLS=true` 但 `INTERNAL_API_BASE_URL` 没有指向当前已启动的平台服务
- **THEN** 文档和 smoke test SHALL 提供检查命令帮助开发者发现配置不一致

### Requirement: Real-tools smoke test shall verify platform and agent layers
系统 SHALL 提供 real-tools smoke test 流程，覆盖平台层健康检查、拓扑解析、Loki 诊断、工具查询、Agent job、steps 和 tool-calls 查询。

#### Scenario: 平台层 smoke test
- **WHEN** 开发者执行 real-tools 平台层 smoke test
- **THEN** 开发者可以验证 `internal-api-platform` health、访问控制、目标解析和 Loki 诊断 endpoint

#### Scenario: Agent 层 smoke test
- **WHEN** 开发者提交 debug Agent job
- **THEN** 开发者可以通过 `GET /api/agent/jobs/{job_id}`、`/steps` 和 `/tool-calls` 观察任务终态和工具调用摘要

### Requirement: Missing real-tools configuration shall fail safely
系统 SHALL 在 real-tools 缺少 topology、secret、Loki base URL 或访问授权时返回安全错误，不得误报为成功查询。

#### Scenario: 缺少平台 secret
- **WHEN** real-tools 请求需要的 secret env 未配置
- **THEN** Internal API Platform MUST 返回非敏感错误摘要
- **AND** 响应 MUST NOT 泄露 secret 名称对应的真实值

#### Scenario: 未授权用户访问目标
- **WHEN** 请求用户无权访问指定 environment/base/workshop
- **THEN** Internal API Platform SHALL 拒绝请求并记录访问决策
