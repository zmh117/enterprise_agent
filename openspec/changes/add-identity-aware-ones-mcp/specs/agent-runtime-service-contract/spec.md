## REMOVED Requirements

### Requirement: 双Runtime必须共享无专用密钥的标准MCP工具服务
**Reason**: 单一无认证 `tool-mcp` 无法表达需要平台用户 Principal 的业务 MCP；本变更以固定服务注册表区分无专用认证的 `tool-mcp` 与使用短期 Principal JWT 的 `ones-mcp`。

**Migration**: 现有 `tool-mcp` URL、无 Bearer Token 和 `X-Job-Id` 行为保持不变；Runtime 协议增加固定 `ones-mcp` server code，并通过独立内存 Header 只向该服务转交 Principal JWT。

### Requirement: Runtime Grant不得扩展为MCP认证
**Reason**: 该要求仍需保留 Runtime Grant 隔离，但必须明确新 Principal JWT 是独立的平台用户凭证，不是 Runtime Grant 的复用或扩展。

**Migration**: Runtime Grant 继续只用于 Worker 调用 Runtime；新增的 Principal JWT 使用独立 Ed25519 key、issuer、audience 和 scope，Runtime 不向任何 MCP 传递 Runtime Grant。

## ADDED Requirements

### Requirement: 双Runtime必须共享固定MCP服务注册表
系统 SHALL 让 Python 与 TypeScript Runtime 使用同一版本化执行协议和部署固定的 MCP 服务注册表；第一阶段只允许 `tool-mcp` 与 `ones-mcp`，请求和模型 MUST NOT 提供或覆盖任一服务 URL。

#### Scenario: Python与TypeScript调用ONES查询
- **WHEN** 两个 Runtime 分别执行冻结了 `ones-mcp:ones_work_item_search` 的 Job
- **THEN** 两端使用固定 `ones-mcp` URL、相同 Tool schema 和相同 Principal JWT Header 获得等价结果

#### Scenario: 请求提供任意MCP地址
- **WHEN** Agent、Application、用户 payload 或模型输出包含自定义 MCP Server URL 或未知 server code
- **THEN** 两个 Runtime 均拒绝该配置，只使用部署时注册的固定服务

#### Scenario: tool-mcp保持无专用Token
- **WHEN** Runtime 调用现有 `tool-mcp`
- **THEN** 请求保持现有 `X-Job-Id` 边界且不携带 Principal JWT、Runtime Grant 或新增 MCP Bearer Token

### Requirement: Runtime Grant与Principal JWT必须完全隔离
Worker→Runtime 的 Runtime Grant SHALL 继续只绑定执行、取消和终态恢复；Principal JWT SHALL 只表达平台用户对指定业务 MCP 的短期权限。两套私钥、公钥、Token、claims 和用途 MUST NOT 复用。

#### Scenario: Worker调用Runtime
- **WHEN** Worker 创建或取消一次 Runtime invocation
- **THEN** Runtime 校验绑定 Job、Publication、invocation 和 request digest 的 Runtime Grant

#### Scenario: Runtime调用ones-mcp
- **WHEN** Runtime 调用 ONES 查询
- **THEN** `Authorization` 只包含 `aud=ones-mcp` 的 Principal JWT，不包含 Runtime Grant

#### Scenario: Principal JWT缺失
- **WHEN** Job 包含 `ones-mcp` Tool 但 Worker 未提供 Principal JWT
- **THEN** Runtime 在连接 MCP 前失败关闭，且不回退到 `X-App-User-Id` 或模型参数冒充身份
