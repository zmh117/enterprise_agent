## Why

当前平台已经保留系统用户与 ONES 外部身份事实，但会在绑定后丢弃登录 Token，且 Runtime 只能调用无身份的 `tool-mcp`，因此 Agent 无法代表当前系统用户查询 ONES。现在需要引入可复用于 ONES、GitLab、Jira 等业务 MCP 的统一 Principal JWT，并为 ONES 提供加密个人凭据、自动重新登录、查询审计和 Mock 验收。

## What Changes

- 新增统一 Principal JWT 签发与验证：Identity Service 根据运行中的 Job、系统用户和冻结 Tool 权限签发短期、面向指定 MCP audience 的非对称 JWT；Runtime 和模型不得自行指定 `sub`、`aud` 或扩大 `scope`。
- 新增固定的 `ones-mcp` Streamable HTTP 服务，只发布 `ones_work_item_search` 查询工具；第一阶段不提供新增、修改、删除或任意 GraphQL/HTTP 执行工具。
- **BREAKING**：将当前“ONES 邮箱、密码和 Token 不得持久化”改为“不得明文持久化”；绑定成功后由统一身份模块使用平台主密钥加密保存邮箱、密码和 Token，并记录独立版本与状态。
- ONES Token 无明确过期时间时先使用加密缓存；上游返回 401 后按身份串行重新登录、替换 Token 并最多重试原查询一次，重新登录失败则标记需要重新验证。
- ONES MCP 使用 Principal JWT 中的系统用户解析已启用的 ONES 身份、默认 Team 和当前凭据，不允许 Tool 参数覆盖系统用户、ONES User ID、Team、Token 或目标 URL。
- 扩展 Python/TypeScript Runtime 协议和固定服务注册表，使 Job 能同时冻结 `tool-mcp` 与 `ones-mcp` Tool；继续拒绝任意 MCP Server URL。
- 新增 MCP 操作审计，使用 correlation ID、Job、session、JWT `jti`、系统用户、外部身份、Team、Tool、凭据版本、状态和耗时串联调用证据；所有请求、响应、错误与日志均不得保存 JWT、密码、ONES Token、Authorization Header 或原始无界响应。
- 扩展 `ones_mock` 与自动化测试，覆盖登录、绑定、JWT 签发/拒绝、查询、401 自动登录重试、权限/身份失败关闭、脱敏审计和 Python/TypeScript Runtime 合约。

## Capabilities

### New Capabilities

- `principal-jwt-authentication`: 定义 Identity Service 的短期非对称 Principal JWT、受信 Job 派生、audience/scope 约束、公钥分发、轮换和 Runtime/MCP 验证边界。
- `identity-aware-ones-mcp`: 定义固定 ONES MCP 查询 Tool、外部身份解析、加密凭据取用、Token 自动重新登录和 Mock 兼容契约。
- `mcp-operation-audit`: 定义 MCP 调用、Provider 尝试和凭据生命周期的可关联、脱敏、有界审计证据。

### Modified Capabilities

- `agent-runtime-service-contract`: Runtime 协议从仅允许 `tool-mcp` 扩展为固定允许 `tool-mcp` 与 `ones-mcp`，并仅向 `ones-mcp` 注入 Principal JWT。
- `multi-provider-external-identity-management`: 在身份事实之外增加与外部身份一对一关联的加密 Provider 凭据和状态生命周期。
- `dingtalk-ones-identity-binding`: ONES 本人绑定成功后原子保存加密邮箱、密码和登录 Token，并在解绑/停用时使运行时凭据不可用。
- `ones-identity-verification`: 登录响应中的 ONES Token 由一次性丢弃改为验证后加密持久化，且支持安全重新登录。
- `ones-work-item-search`: 从已退役的 Capability 链迁移为 `ones-mcp` Tool，并保留当前用户、默认 Team、只读 GraphQL 和失败关闭要求。
- `agent-audit-permission`: 增加 Principal JWT、MCP Provider 调用和 Token 自动重新登录的脱敏审计要求。

## Impact

- 后端：统一身份模块、ONES 本人绑定 API、加密凭据仓储、JWT issuer/JWKS、Job/授权读取、审计仓储、数据库迁移和 Bootstrap 装配。
- Runtime：共享协议 schema、Python Runtime、TypeScript Runtime、固定 MCP URL 配置、per-server Header 注入、Tool allowlist 和安全日志测试。
- MCP：新增 `services/ones_mcp_server`，复用受控网络客户端、输入/输出边界和平台数据库事实；不得恢复已删除的旧 Capability/Connection 或 HS256 MCP Token 模型。
- 前端：保持现有本人 ONES 绑定流程，状态投影增加凭据有效性/需要重验的安全状态，不返回邮箱、密码或 Token。
- 部署：增加 `ones-mcp` 私网服务、非对称签名私钥/JWKS 配置和固定 Runtime URL；生产只允许 HTTPS ONES 目标，本地 Mock 可显式允许 HTTP。
- 数据：新增加密外部凭据、JWT key metadata/审计和 MCP 操作审计结构；现有 `user_external_identity` 继续作为身份事实源。
