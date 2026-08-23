# 统一身份 ONES MCP

`ones-mcp` 是代码注册、身份感知、只读的独立 MCP Server。当前只发布两个 Tool：

| Tool identifier | 输入 | 当前 Provider 调用 |
|---|---|---|
| `ones_work_item_search` | `keyword`、`issue_type=demand|task|defect`、`limit=1..50` | 固定 GraphQL operation |
| `ones_list_project_role_members` | `project_uuid` | 固定项目角色成员 REST operation，再用固定 Team 用户 operation 补齐姓名 |

两个工具都返回有界 schema，并标记 `untrusted_data=true`。模型不能提交 Team、用户、
Token、URL、Header、GraphQL 文档或任意 HTTP 方法/路径。

## MCP 与网络边界

`ones-mcp` 镜像安装 `mcp==2.0.0`，固定提供无状态 Streamable HTTP `/mcp`：

- 支持 MCP 2026-07-28 的 `server/discover`、`tools/list`、`tools/call`；
- 保留现有 Runtime 使用的 `initialize` / 2025-06-18 调用；
- 不提供 stdio、Cursor 或独立凭据旁路；
- 拒绝无 Bearer、浏览器 Origin、错误 Host、超大请求和非授权 Tool；
- Provider 目标、登录路径、GraphQL 文档和 REST operation 都由代码固定，并受
  HTTPS/allowlist/重定向/响应大小策略约束。

`tool-mcp`、`ones-mcp` 和 File Service 当前都在各自镜像中使用 MCP v2；Python Agent
Runtime 是协议客户端，不安装服务端依赖。

## 本人绑定与加密凭据

ONES 绑定仍是两阶段本人操作，但当前实现会安全持久化业务调用凭据：

1. 当前 Web Session 用户提交邮箱和密码；服务端调用固定登录端点。
2. 服务端创建最长 30 分钟、单次使用的 Verification Challenge，公开响应只含
   Challenge ID、用户/Team 候选和安全时间。
3. Challenge 内的邮箱、密码和登录 Token 使用平台 Master Key、purpose-bound AAD 与
   AES-256-GCM 加密暂存。
4. 用户选择本次候选中的默认 Team 后，服务端原子保存/替换 ONES 外部身份，并把邮箱、
   密码和 Token 转存到当前 `external_identity_credential`；Challenge 密文立即清空。
5. API 和页面只投影 `configured/status/revision`、默认 Team、安全时间与安全错误码，
   不返回邮箱、密码、Token、密文、nonce 或 key material。

每个内部用户当前最多一个启用的 ONES 身份和一份当前凭据。本人可以重新验证或解绑；
管理员只能治理状态和查看安全摘要，不能代输密码、代验证或读取凭据。

## Job Principal 与实时授权

1. Agent Worker 从当前 Job、内部用户、Application/Agent Publication、Tool Snapshot 与
   当前授权签发最长五分钟的 Ed25519 Principal JWT。
2. JWT 只包含平台主体和精确 `mcp:invoke:ones-mcp:<tool>` scope，不包含 ONES User ID、
   Team、邮箱、密码或 Token。
3. Python Runtime 只在该 invocation 的内存 Secret Context 中持有 JWT，并把它作为
   `ones-mcp` Bearer Header；请求正文、Runtime Grant、事件和 ledger 不保存 JWT。
4. `ones-mcp` 验证 JWKS 后实时复核 Job、用户、Publication、Tool schema/scope、应用
   访问、唯一启用 ONES 身份、默认 Team 与 ACTIVE credential。任一事实失效即拒绝。

`ones_work_item_search` 与 `ones_list_project_role_members` 使用不同精确 scope；Application
Publication 只冻结其中一个时，另一个不会出现在 `tools/list` 中，也不能通过直接
`tools/call` 绕过。

## Token 刷新

Provider 首次返回 401 时，服务按 credential 加锁并重读 revision。若没有其它请求已
完成轮换，则使用加密登录材料重新登录，复核 Provider subject 与默认 Team，并通过
CAS 更新 Token；原 Tool 最多重试一次。第二次 401、身份变化、Team 消失或刷新失败会
把凭据置为 `REAUTH_REQUIRED`，要求本人重新验证，不回退旧 Token 或其他身份。

## 审计与验收边界

`mcp_operation_audit` 记录 Tool Input、固定 Provider operation 的有界请求/响应摘要、
授权决定、credential revision、耗时和稳定错误码。密码、Token、Principal JWT、
Authorization/Cookie、密文、nonce、私钥和无界 Provider 响应不得进入审计或日志。

本地 Mock 可以验证协议、授权、刷新、并发、响应边界和安全错误分类；它不证明真实
ONES GraphQL/REST 路径、Header、TLS、权限和响应 schema 兼容，也不证明钉钉到 Delivery
的真实环境 E2E。真实 Provider 验收必须使用获授权的只读账号，并分别验证两个 Tool。
