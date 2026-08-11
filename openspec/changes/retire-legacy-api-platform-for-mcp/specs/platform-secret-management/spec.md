## ADDED Requirements

### Requirement: Internal API 与 Runtime Tool 专用密钥必须永久删除
系统 MUST 不创建、挂载、解析或展示 Internal API server/client Token、`runtime-tool-mcp` HS256 signing key、MCP access token 或相关 Secret usage；平台凭据中心只保留工具资源、模型、渠道和其它仍存在的业务 Secret。

#### Scenario: 升级已有数据库
- **WHEN** 破坏性迁移发现仅被已退役组件引用的 Internal API 或 Runtime Tool Secret metadata
- **THEN** 系统删除其 usage 和 metadata，审计不得包含 Secret 值

#### Scenario: 新配置提交旧 Secret code
- **WHEN** 管理 API 或 Compose 尝试配置已退役专用 Secret
- **THEN** 配置校验失败且不得形成兼容用途

