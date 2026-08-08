## ADDED Requirements

### Requirement: Runtime config overlay shall be smoke-verifiable after service restart
系统 SHALL 支持在 Docker Compose 环境中通过 curl 写入 DB-backed runtime config，并在重启服务后通过 `/api/ready` 证明 overlay 已生效。

#### Scenario: Compose smoke writes runtime config
- **WHEN** 开发者通过 `/api/platform/runtime-config/values` 写入 `ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`、`ANTHROPIC_API_KEY` 和 `AGENT_MAX_TURNS`
- **THEN** runtime config snapshot SHALL 显示这些 key 的 effective source 来自数据库，并对敏感 key 只显示 `secret_ref` 和 configured 状态

#### Scenario: Compose smoke restarts services
- **WHEN** 开发者写入 runtime config 后重启 `api-server` 和 `agent-worker`
- **THEN** `/api/ready` SHALL 报告 DB-backed runtime config source/revision/hash，且不得泄漏敏感值

### Requirement: Runtime config smoke shall document degraded fallback
系统 SHALL 在 smoke 文档中说明 runtime config 加载失败、DB 不可用、secret 缺失或类型错误时的 degraded 表现和排查命令。

#### Scenario: Secret-backed config is missing
- **WHEN** runtime config 指向不存在或禁用的 `secret://platform/<code>`
- **THEN** ready/debug 输出 SHALL 标记 degraded 或安全配置错误，并且文档 SHALL 指引开发者检查 secret 状态和 runtime config snapshot
