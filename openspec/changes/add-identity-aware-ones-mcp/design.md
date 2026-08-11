## Context

当前系统已经以 `app_user` 和 `user_external_identity` 保存统一用户及 ONES 身份事实，并通过两阶段本人验证选择默认 Team。迁移 038/039 有意删除了旧 API Capability 个人凭据和历史 HS256 MCP Token，因此现状只能验证 ONES 身份，不能让 Agent 代表当前用户查询 ONES。

Python/TypeScript Runtime 当前只接受固定 `tool-mcp`，以 `X-Job-Id` 调用私网 MCP；Runtime 执行协议、终态 ledger 和 request digest 都不得保存运行密钥。本变更需要增加第二个固定 MCP 服务、短期平台 Principal JWT 和个人 Provider 凭据，同时避免恢复任意 MCP URL、旧 Capability/Connection 控制面或通用 HTTP/GraphQL 执行器。

## Goals / Non-Goals

**Goals:**

- 建立可复用于其它业务 MCP 的统一 Principal JWT，而不是 ONES 专用 JWT。
- 让本人 ONES 绑定原子保存加密登录材料和 Token，并支持 401 后自动重新登录。
- 让两个 Runtime 通过同一固定 `ones-mcp` 和同一 Tool schema 查询 `ones_mock`。
- 在 Job、JWT、外部身份、凭据版本、Provider 尝试和 Tool Call 之间形成脱敏审计链。
- 保持身份、凭据、平台 RBAC、ONES 原生权限和 Tool 发布范围彼此独立。

**Non-Goals:**

- 第一阶段不实现 ONES 新增、修改、删除、评论或任意 GraphQL/HTTP Tool。
- 不允许 Agent、Application、用户、模型或外部请求注册任意 MCP Server、Provider URL 或 JWT audience。
- 不把 ONES Token、密码、邮箱、Principal JWT 或签名私钥写入 Prompt、RabbitMQ、Runtime ledger、审计、错误响应或 Tool 输出。
- 不恢复旧 API Capability、API Connection、`provider_credential` 历史模型或共享 HS256 MCP signing key。
- 不在本阶段拆出新的独立 Identity 微服务进程；统一身份能力先作为现有后端的明确模块边界交付。

## Decisions

### 1. 统一身份能力采用模块化 Identity Service

现有 `app_user` 继续作为平台主体事实源，`user_external_identity` 继续保存 Provider、外部 subject、Team 和默认 Team。新增通用 `external_identity_credential`，与一个外部身份一对一关联，保存 Provider 登录材料、Token、状态、版本和安全时间戳。

Identity Service 提供三类端口：本人绑定/重验控制面、Principal JWT 签发、Provider Credential 解析与轮换。首期只有 ONES Adapter，Provider 类型仍为代码注册白名单，不提供数据库驱动的任意认证模板。

选择模块化边界而非立即增加独立微服务，是为了复用当前事务、身份仓储和主密钥，同时保持未来拆分时可替换端口；ONES MCP 只依赖这些明确端口和表，不读取用户密码表或平台 Secret 目录。

### 2. 登录材料与 Token 使用独立 AES-GCM 密文

凭据表分别保存登录材料密文和 Token 密文，二者使用随机 nonce、平台主密钥、稳定 credential ID 与 purpose 组成的 AAD；表中只保存密文、nonce、key ID、算法、状态和 revision。登录材料为规范 JSON `{email,password}`，不得复制到身份 metadata。

两阶段绑定开始时，邮箱、密码和登录返回 Token 只以加密形式暂存在有 TTL 的 challenge；确认默认 Team 时，在同一数据库事务中绑定/重验身份、写入当前凭据并清除 challenge 密文。失败或过期 challenge 不产生当前凭据。

软解绑会把凭据标记为 `UNBOUND` 并清空密文；身份或用户停用时，即使凭据仍为 `ACTIVE`，运行时解析也必须失败。管理员投影只显示 `configured`、`status`、revision 和安全时间，不显示邮箱、Token 或密文元数据。

### 3. Principal JWT 使用 Ed25519 和精确 audience/scope

Worker 中的 `PrincipalTokenIssuer` 使用只挂载到可信执行进程的 PKCS#8 Ed25519 私钥签发 JWT；`kid` 由公钥指纹确定。`ones-mcp` 只加载包含当前/上一把公钥的只读 JWKS，按 `kid`、`alg=EdDSA`、`iss` 和 `aud=ones-mcp` 验证。

JWT 固定包含 `sub`、`aud`、`azp=agent-runtime`、`job_id`、`session_id`、Agent/Application Publication、精确 `scope`、授权摘要、`jti`、`iat`、`nbf` 和最长五分钟的 `exp`。Issuer 必须从数据库中的运行 Job、MCP Tool 快照和当前授权派生 claims；调用方不得提交或覆盖 `sub`、`aud`、`scope`。

JWT 只证明“哪个平台用户被允许通过哪个 Job 调用哪个 MCP Tool”，不包含 `external_identity_id`、ONES User ID、Team、邮箱、密码或 ONES Token。ONES MCP 在调用时重新读取用户、身份、默认 Team、Job 状态和 Tool 快照，以支持即时停用和撤权。

### 4. Principal JWT 通过独立 Runtime 请求 Header 传递

Worker 调用 Runtime 时把 JWT 放在 `X-MCP-Principal-Token` Header，而不是执行 JSON。这样 JWT 不参与 `request_digest`，不会因重试时重新签发而造成 invocation 冲突，也不会进入 Runtime request/terminal ledger。

Runtime request handler 在 Runtime Grant 校验成功后读取该 Header，只把它保存在当前 invocation 的内存 secret context。Runtime 只在构造 `ones-mcp` HTTP 配置时加入 `Authorization: Bearer ...`；`tool-mcp` 不接收该 Header，日志和事件 schema 也没有对应字段。

### 5. Runtime 使用固定 per-server 注册表

执行协议允许的 `server_code` 从单一字面量扩展为 `tool-mcp | ones-mcp`，但请求仍不含 URL。Python/TypeScript Runtime 在部署配置中各自维护固定映射：

```text
tool-mcp -> MCP_TOOL_SERVER_URL
ones-mcp -> ONES_MCP_SERVER_URL
```

每个服务使用独立 SDK alias，Tool 名为 `mcp__tool_mcp__*` 或 `mcp__ones_mcp__*`。缺少固定 URL、未知 server code、ONES Tool 缺少 Principal JWT、Tool 不在 Job 快照或模型尝试加入身份参数时均失败关闭。

### 6. `ones-mcp` 只发布一个业务语义查询 Tool

`ones_work_item_search(keyword, issue_type, limit)` 为唯一 Tool。公开 schema 禁止额外字段；`issue_type` 只允许 `demand|task|defect`，`limit` 为 1..50。MCP 内部把类型映射到服务端固定 issue type UUID，并调用 `ones_mock` 已有固定 GraphQL query 路径。

系统用户、ONES User ID、默认 Team、Token、Base URL、Header 和 GraphQL document 都由服务端解析，不是 Tool 参数。响应只返回有界的 `number/name/type`、total、truncated 和 `untrusted_data=true`。

### 7. 401 自动重新登录最多一次

ONES MCP 首次使用当前加密 Token 查询。收到 401 后，它先重新读取 credential revision；若其它实例已经轮换 Token，则直接使用新 Token 重试。否则解密登录材料、调用固定登录端点，严格验证返回 subject 与当前身份一致、默认 Team 仍在返回 Team 集合，然后以 optimistic revision 更新 Token。

同一进程对 credential ID 使用异步锁降低重复登录，跨实例以 revision compare-and-swap 收敛。原查询最多重试一次；登录失败、subject 改变、Team 消失或第二次 401 会把凭据标记为 `REAUTH_REQUIRED` 并返回安全错误，不回退到其它用户、Team 或共享 Token。

### 8. 审计分为平台事件、Tool Call 和 MCP 操作证据

现有 `audit_event` 记录绑定、重验、JWT 签发拒绝、凭据轮换状态；`agent_tool_call` 继续记录模型侧 Tool 摘要。新增 `mcp_operation_audit` 记录真实 MCP/Provider 操作：correlation ID、Job、session、principal `jti`、actor、外部身份、Team、server/tool、operation、credential revision、attempt、status、error code、duration、请求/响应安全摘要和时间。

搜索请求只保存 keyword hash/长度、类型和 limit；响应只保存数量、total、truncated。JWT、Authorization、邮箱、密码、Token、GraphQL 原文、原始响应和工作项完整正文均不得持久化。审计写入失败不得把成功 Provider 调用伪装为未发生；Tool 返回安全失败并保留可定位错误码。

### 9. 部署与密钥边界

`ones-mcp` 使用独立只读容器文件系统，只在私网暴露端口，连接平台 PostgreSQL 与 ONES allowlisted egress，并挂载平台主密钥和 Principal JWKS；它不挂载 Principal 私钥、Runtime Grant 或模型密钥。Agent Worker 挂载 Principal 私钥但不挂载 JWKS 之外的 MCP 认证材料。两个 Runtime 只收到短期 JWT，不挂载私钥或个人凭据主密钥。

本地测试允许固定 `ones_mock` HTTP host；生产只允许 HTTPS、禁用代理和重定向，并限制超时、请求体、响应体和解析字段。

## Risks / Trade-offs

- [Risk] 加密保存密码扩大凭据泄漏影响面。→ 使用独立表、AES-GCM AAD、主密钥文件、最小容器挂载、API 零回显、软解绑清密文和敏感扫描测试。
- [Risk] 短期 JWT 在到期前仍可重放。→ 绑定 Job/audience/scope/jti，MCP 实时校验 Job/用户/身份/Tool 快照，并依赖私网；写操作不在本阶段范围内。
- [Risk] 多实例同时遇到 401 会重复登录。→ 本地锁加数据库 revision CAS；冲突实例重新读取新 Token，不覆盖较新版本。
- [Risk] 新活动变更与正在收尾的旧平台退役变更语义冲突。→ 使用独立前向迁移和 delta spec，明确只覆盖 ONES 凭据与专用 MCP，不恢复旧 Capability/Connection/HS256 组件。
- [Risk] Runtime Header 被错误记录。→ Header 值不进入执行 schema、digest、logger、事件或 ledger，并增加全仓敏感值回归测试。
- [Risk] Mock 查询成功不等于真实 ONES 兼容。→ 第一阶段验收只声明 Mock 合约通过；真实 ONES 上线需要独立连接验证与 E2E 证据。

## Migration Plan

1. 创建新表和 challenge 加密列，迁移不修改既有身份事实；旧身份保持“已绑定但无运行凭据”，查询时返回需要重验。
2. 部署 Identity credential/JWT 代码和本人重验流程；只有新确认的 challenge 才产生 `ACTIVE` 凭据。
3. 部署 `ones-mcp`、JWKS 与 Runtime 固定 URL，但尚不把 Tool 加入任何已发布 Agent/Application。
4. 更新 MCP Tool Manifest、Runtime 合约和发布组合，重新发布明确选择 `ones_work_item_search` 的 Agent/Application。
5. 使用 `ones_mock` 验收绑定、查询、401 自动登录、失败关闭、双 Runtime 和审计脱敏。
6. 回滚应用代码时保留新表；停止发布 `ones-mcp` Tool 并停用服务即可阻断调用。已经保存的凭据由运维显式解绑或后续清理迁移处理，不自动解密导出。

## Open Questions

无。第一阶段范围、JWT、加密保存邮箱/密码/Token、自动刷新和仅 Mock 查询验收均已由用户确认。
